"""승인 이후 주문·체결·TCA·정산 상태를 읽기 전용으로 관측한다."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import plotly.graph_objects as go
import streamlit as st

from investment_agent.dashboard.components.animated_pipeline import animated_pipeline
from investment_agent.reporting.readers.dashboard import load_execution_data
from investment_agent.dashboard.components.execution_view import execution_summary, trace_for_intent
from investment_agent.dashboard.components.theme import dashboard_palette, plotly_layout
from investment_agent.dashboard.components.ui import (
    SOURCE_CALC,
    SOURCE_DB,
    compact_json,
    dataframe,
    display_money,
    display_number,
    format_time,
    page_header,
    render_source_help,
    result_payload,
    result_status,
    source_note,
    view_selector,
)


def _rows(payload: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    values = payload.get(key)
    if not isinstance(values, list):
        return []
    return [dict(row) for row in values if isinstance(row, Mapping)]


def _status_label(value: Any) -> str:
    labels = {
        "approved": "승인됨",
        "claimed": "처리 예약",
        "executing": "실행 중",
        "completed": "완료",
        "failed": "실패",
        "expired": "만료",
        "cancelled": "취소",
        "pending": "승인 대기",
        "rejected": "거절",
        "consumed": "승인 사용됨",
        "planned": "계획됨",
        "submitted": "브로커 제출",
        "partially_filled": "부분 체결",
        "filled": "체결 완료",
        "outcome_unknown": "결과 불명",
        "reconciling": "정산 확인 중",
        "replaced": "대체 주문",
        "running": "진행 중",
        "matched": "일치",
        "repaired": "복구됨",
        "lockdown": "잠금",
    }
    current = str(value or "").strip()
    return labels.get(current, current or "—")


def _pipeline_steps(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    intents = _rows(payload, "intents")
    approvals = _rows(payload, "approvals")
    orders = _rows(payload, "orders")
    fills = _rows(payload, "fills")
    tca_rows = _rows(payload, "tca_reports")
    reconciliations = _rows(payload, "reconciliations")
    return [
        {
            "title": "Execution intent",
            "value": f"{len(intents)}건",
            "detail": "RiskGate 승인 비중과 유효시간을 실행 경계에 고정해요.",
            "status": _status_label(intents[0].get("status")) if intents else "기록 없음",
        },
        {
            "title": "사람 승인",
            "value": f"{len(approvals)}건",
            "detail": "Discord 승인도 특정 manifest와 주문 ID에 한 번만 유효해요.",
            "status": _status_label(approvals[0].get("status")) if approvals else "요청 없음",
        },
        {
            "title": "브로커 주문",
            "value": f"{len(orders)}건",
            "detail": "네트워크 시도 전에 append-only 원장에 주문을 예약해요.",
            "status": _status_label(orders[0].get("status")) if orders else "주문 없음",
        },
        {
            "title": "체결",
            "value": f"{len(fills)}건",
            "detail": "브로커가 확인한 체결만 별도 사실로 보존해요.",
            "status": "체결 있음" if fills else "체결 없음",
        },
        {
            "title": "TCA",
            "value": f"{len(tca_rows)}건",
            "detail": "결정가·도착가·체결가의 비용을 같은 cost convention으로 계산해요.",
            "status": "계산됨" if tca_rows else "미계산",
        },
        {
            "title": "Reconciliation",
            "value": f"{len(reconciliations)}회",
            "detail": "브로커 주문 상태를 진실 원천으로 삼아 내부 원장과 맞춰요.",
            "status": _status_label(reconciliations[0].get("status")) if reconciliations else "기록 없음",
        },
    ]


page_header(
    "실행 관제",
    "승인된 결정이 주문·체결·비용·정산으로 이어지는 과정을 한 원장으로 확인해요",
    discord="#투자-승인",
)
render_source_help()
st.caption(":material/lock: 읽기 전용 · 시작·정지는 로컬 ATLAS 제어센터")

result = load_execution_data()
payload = result_payload(result, default={}) or {}
available = result_status(result, empty_text="아직 실행·체결·정산 기록이 없어요")
if getattr(result, "message", None) and getattr(result, "status", None) == "ok":
    st.warning(str(result.message), icon=":material/warning:")

summary = execution_summary(payload)
with st.container(border=True):
    with st.container(horizontal=True):
        if summary["kill_switch_on"] is True:
            st.badge("킬스위치 ON", icon=":material/emergency_home:", color="red")
        elif summary["kill_switch_on"] is False:
            st.badge("킬스위치 OFF", icon=":material/warning:", color="orange")
        else:
            st.badge("킬스위치 미확인", icon=":material/help:", color="gray")
        if summary["durable_lockdown_on"] is True:
            st.badge("Durable lockdown", icon=":material/lock:", color="gray")
        if summary["live_enabled"] is True:
            st.badge("Live 설정 활성", icon=":material/warning:", color="orange")
        else:
            st.badge("Live 비활성", icon=":material/shield:", color="blue")
    st.subheader("실행 경계 현재 상태")
    st.caption("제안·승인·주문·체결을 하나의 완료 상태로 합치지 않아요.")
    with st.container(horizontal=True):
        st.metric("Intent", f"{summary['intent_count']}건", border=True)
        st.metric("승인 대기", f"{summary['pending_approval_count']}건", border=True)
        st.metric("열린 주문", f"{summary['open_order_count']}건", border=True)
        st.metric("체결", f"{summary['fill_count']}건", border=True)

view = view_selector(
    "실행 관제 보기",
    ("실행 흐름", "주문·체결", "TCA", "정산"),
    key="execution_adaptive_view",
    default="실행 흐름",
)

if view == "실행 흐름":
    animated_pipeline(
        _pipeline_steps(payload),
        key="execution_observability_pipeline",
        preview=False,
        show_note=False,
    )
    intents = _rows(payload, "intents")
    if intents:
        intent_ids = [str(row.get("intent_id")) for row in intents if row.get("intent_id")]
        selected_intent = st.selectbox(
            "Execution intent 추적",
            intent_ids,
            format_func=lambda value: next(
                (
                    f"{value} · {_status_label(row.get('status'))} · {row.get('execution_mode') or '—'}"
                    for row in intents
                    if str(row.get("intent_id")) == value
                ),
                value,
            ),
            key="execution_trace_intent",
        )
        trace = trace_for_intent(payload, selected_intent)
        intent = trace["intent"]
        approval = trace["approval"]
        with st.container(horizontal=True):
            st.metric("Intent 상태", _status_label(intent.get("status")), border=True)
            st.metric("실행 모드", str(intent.get("execution_mode") or "—"), border=True)
            st.metric("승인 상태", _status_label(approval.get("status")), border=True)
            st.metric("연결 주문", f"{len(trace['orders'])}건", border=True)
        dataframe(
            [
                {
                    "단계": "Intent",
                    "상태": _status_label(intent.get("status")),
                    "시각": format_time(intent.get("created_at")),
                    "식별자": intent.get("intent_id"),
                },
                {
                    "단계": "사람 승인",
                    "상태": _status_label(approval.get("status")),
                    "시각": format_time(approval.get("updated_at")),
                    "식별자": approval.get("approval_id"),
                },
                {
                    "단계": "주문",
                    "상태": " · ".join(
                        _status_label(row.get("status")) for row in trace["orders"]
                    ) or "주문 없음",
                    "시각": format_time(
                        trace["orders"][0].get("updated_at") if trace["orders"] else None
                    ),
                    "식별자": " · ".join(
                        str(row.get("client_order_id")) for row in trace["orders"]
                    ) or "—",
                },
                {
                    "단계": "체결·TCA",
                    "상태": f"체결 {len(trace['fills'])}건 · TCA {len(trace['tca_reports'])}건",
                    "시각": format_time(
                        trace["tca_reports"][0].get("created_at")
                        if trace["tca_reports"]
                        else trace["fills"][0].get("filled_at") if trace["fills"] else None
                    ),
                    "식별자": "—",
                },
            ],
            key="execution_intent_trace",
        )
    elif available:
        st.info("표시 가능한 execution intent가 없어요.")

elif view == "주문·체결":
    orders = _rows(payload, "orders")
    fills = _rows(payload, "fills")
    with st.container(horizontal=True):
        st.metric("전체 주문", f"{len(orders)}건", border=True)
        st.metric("열린 주문", f"{summary['open_order_count']}건", border=True)
        st.metric("확인 필요", f"{summary['order_incident_count']}건", border=True)
        st.metric("체결 이벤트", f"{len(fills)}건", border=True)
    if orders:
        dataframe(
            [
                {
                    "종목": row.get("ticker"),
                    "방향": "매수" if row.get("side") == "buy" else "매도",
                    "수량": row.get("quantity"),
                    "기준가": row.get("reference_price"),
                    "주문금액": row.get("notional"),
                    "상태": _status_label(row.get("status")),
                    "브로커 상태": row.get("raw_broker_status") or "—",
                    "최근 갱신": format_time(row.get("updated_at")),
                    "주문 ID": row.get("client_order_id"),
                }
                for row in orders
            ],
            key="execution_orders",
        )
    else:
        st.info("저장된 주문이 없어요.")
    if fills:
        st.subheader(":material/check_circle: 브로커 확인 체결")
        dataframe(
            [
                {
                    "종목": row.get("ticker"),
                    "방향": "매수" if row.get("side") == "buy" else "매도",
                    "수량": row.get("quantity"),
                    "체결가": row.get("price"),
                    "수수료": row.get("commission"),
                    "체결 시각": format_time(row.get("filled_at")),
                    "주문 ID": row.get("client_order_id"),
                }
                for row in fills
            ],
            key="execution_fills",
        )

elif view == "TCA":
    tca_rows = _rows(payload, "tca_reports")
    with st.container(horizontal=True):
        st.metric("TCA 보고서", f"{summary['tca_count']}건", border=True)
        st.metric(
            "총 Implementation shortfall",
            display_money(summary["implementation_shortfall"]),
            border=True,
        )
        st.metric(
            "거래대금 대비 비용",
            display_number(summary["implementation_shortfall_bps"], suffix=" bps"),
            border=True,
        )
    if tca_rows:
        colors = dashboard_palette()
        figure = go.Figure(
            go.Bar(
                x=[str(row.get("ticker") or "—") for row in tca_rows],
                y=[row.get("implementation_shortfall") for row in tca_rows],
                marker_color=colors.primary,
                customdata=[
                    [
                        row.get("source_kind") or "—",
                        row.get("client_order_id") or "—",
                    ]
                    for row in tca_rows
                ],
                hovertemplate=(
                    "%{x}<br>shortfall $%{y:,.2f}<br>%{customdata[0]} · "
                    "%{customdata[1]}<extra></extra>"
                ),
            )
        )
        layout = plotly_layout(height=340)
        layout["yaxis_title"] = "비용 (USD, 양수 cost convention)"
        figure.update_layout(**layout)
        st.plotly_chart(figure, width="stretch", config={"displaylogo": False})
        dataframe(
            [
                {
                    "종목": row.get("ticker"),
                    "방향": "매수" if row.get("side") == "buy" else "매도",
                    "결정가": row.get("decision_price"),
                    "도착가": row.get("arrival_price"),
                    "체결가": row.get("fill_price"),
                    "스프레드 비용": row.get("spread_cost"),
                    "Slippage": row.get("slippage"),
                    "지연 비용": row.get("delay_cost"),
                    "수수료": row.get("fees"),
                    "총 Shortfall": row.get("implementation_shortfall"),
                    "체결 시간": display_number(row.get("time_to_fill"), suffix="초"),
                    "소스": row.get("source_kind"),
                }
                for row in tca_rows
            ],
            key="execution_tca",
        )
    else:
        st.info("체결에 연결된 TCA 보고서가 아직 없어요.")

else:
    reconciliations = _rows(payload, "reconciliations")
    with st.container(horizontal=True):
        st.metric(
            "최근 정산",
            _status_label(summary["reconciliation_status"]),
            border=True,
        )
        st.metric(
            "불일치",
            display_number(summary["reconciliation_mismatch_count"], digits=0, suffix="건"),
            border=True,
        )
        st.metric(
            "복구",
            display_number(summary["reconciliation_repair_count"], digits=0, suffix="건"),
            border=True,
        )
    if reconciliations:
        dataframe(
            [
                {
                    "시작": format_time(row.get("started_at")),
                    "완료": format_time(row.get("completed_at")),
                    "모드": row.get("execution_mode"),
                    "브로커": row.get("broker"),
                    "상태": _status_label(row.get("status")),
                    "불일치": row.get("mismatch_count"),
                    "복구": row.get("repair_count"),
                    "상세": compact_json(row.get("details") or {}),
                }
                for row in reconciliations
            ],
            key="execution_reconciliations",
        )
    else:
        st.info("저장된 reconciliation 실행이 없어요.")

source_note(
    SOURCE_DB,
    SOURCE_CALC,
    observed_at=getattr(result, "observed_at", None),
    detail="계좌 식별자·원시 브로커 응답 제외 · 최대 2분 캐시",
)


# 승인은 주문 흐름의 한 단계지 별도 영역이 아니다 — Discord도 같은 이유로
# 판단→승인→체결을 한 카테고리에 뒀다.
from investment_agent.dashboard.app_pages import ai_approval  # noqa: E402

st.divider()
with st.expander("AI 승인 검토", expanded=False):
    ai_approval.render()
