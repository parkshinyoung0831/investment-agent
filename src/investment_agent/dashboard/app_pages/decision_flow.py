"""판단 과정 — 데이터에서 주문까지 어느 단계까지 갔는지 한 화면에서 본다.

내부 로직이 복잡해져도 "무엇을 보고 → 어떻게 판단해서 → 무엇을 했는가"는
단순하게 읽혀야 한다. 그래서 단계마다 실제 원장 건수만 먼저 보여주고, 고른
단계의 기록만 펼친다. 세부 화면은 각 단계의 담당 페이지가 따로 갖는다.
"""
from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from investment_agent.dashboard.db import load_alpha_lab_data
from investment_agent.reporting.readers.dashboard import load_execution_data
from investment_agent.dashboard.components.ui import (
    awaiting_data,
    compact_json,
    dataframe,
    format_time,
    page_header,
    result_payload,
)

# 단계 정의가 곧 화면이다. (payload 키, 이름, 원장, 이 단계가 답하는 질문)
STAGES: tuple[tuple[str, str, str, str], ...] = (
    ("ticker_signals", "① 종목 판단", "trading.signals",
     "무슨 근거를 보고 종목별로 어떤 신호를 냈나"),
    ("portfolio_proposals", "② 포트폴리오", "trading.portfolio_proposals",
     "그 신호들을 합쳐 목표 비중을 어떻게 잡았나"),
    ("risk_decisions", "③ 위험 심사", "trading.risk_decisions",
     "한도를 넘지 않는지 검사해 승인했나 거절했나"),
    ("intents", "④ 실행 의도", "execution.intents",
     "승인된 비중을 실제 주문안으로 바꿨나"),
    ("orders", "⑤ 주문·체결", "execution.orders",
     "실제로 무엇을 사고 팔았나"),
)


def _rows(payload: Mapping[str, Any] | None, key: str) -> list[dict[str, Any]]:
    value = (payload or {}).get(key)
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _flatten(row: Mapping[str, Any]) -> dict[str, Any]:
    """중첩 값은 표에 그대로 못 넣으므로 한 줄 JSON으로 접는다."""
    return {
        key: compact_json(value) if isinstance(value, (dict, list)) else value
        for key, value in row.items()
    }


def _render_signals(rows: list[dict[str, Any]]) -> None:
    dataframe(
        [
            {
                "종목": row.get("ticker"),
                "신호": (row.get("proposal") or {}).get("signal"),
                "신뢰도": (row.get("proposal") or {}).get("confidence"),
                "기대 초과수익": (row.get("proposal") or {}).get("expected_excess_return"),
                "목표 비중": (row.get("proposal") or {}).get("target_weight"),
                "기록 시각": format_time(row.get("recorded_at")),
            }
            for row in rows[:50]
        ],
        key="flow_signals",
    )


def _render_risk(rows: list[dict[str, Any]]) -> None:
    for row in rows[:10]:
        approved = bool(row.get("is_approved"))
        st.write(f"**{'승인' if approved else '거절'}** · `{row.get('risk_decision_id', '—')}`")
        violations = [str(item) for item in (row.get("violations") or ())]
        if violations:
            for item in violations:
                st.write(f"- {item}")
        elif not approved:
            st.caption("거절 사유가 기록되지 않았어요")


page_header(
    "판단 과정",
    "데이터에서 주문까지 어느 단계까지 갔는지 봅니다. 단계를 고르면 그 단계의 기록이 열려요.",
    discord="#투자-리포트",
)

alpha_result = load_alpha_lab_data()
execution_result = load_execution_data()
alpha_payload = result_payload(alpha_result, default={}) or {}
execution_payload = result_payload(execution_result, default={}) or {}
by_stage = {
    key: _rows(execution_payload if key in {"intents", "orders"} else alpha_payload, key)
    for key, _name, _table, _question in STAGES
}

for column, (key, name, _table, _question) in zip(st.columns(len(STAGES)), STAGES, strict=True):
    with column:
        st.metric(name, f"{len(by_stage[key]):,}건", border=True)

if not any(by_stage.values()):
    awaiting_data(
        "판단 기록",
        reason="아직 저장된 판단이 없어요",
        fills_when="하네스가 분석을 한 번 끝내면 ①부터 채워져요",
    )
    st.stop()

selected = st.radio(
    "자세히 볼 단계",
    [name for _key, name, _table, _question in STAGES],
    horizontal=True,
    key="decision_flow_stage",
)
for key, name, table, question in STAGES:
    if name != selected:
        continue
    st.caption(f"{question} · 원장 `{table}`")
    rows = by_stage[key]
    if not rows:
        awaiting_data(
            "이 단계",
            reason="아직 기록이 없어요",
            fills_when="앞 단계가 끝나면 여기부터 채워져요",
        )
    elif key == "ticker_signals":
        _render_signals(rows)
    elif key == "risk_decisions":
        _render_risk(rows)
    else:
        dataframe([_flatten(row) for row in rows[:50]], key=f"flow_{key}")
