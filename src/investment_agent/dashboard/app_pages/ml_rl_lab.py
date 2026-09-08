"""AI·강화학습(ML/RL) 자율진화 관제 랩 대시보드 페이지.

하네스 7대 전자동 잡의 실제 실행 상태, PPO 강화학습 챔피언 정책 파일(active_policy.json),
Lopez de Prado의 DSR 과적합 검정 게이지, 실제 SignalBlender 앙상블,
그리고 실제 시장·매크로 DB 데이터를 조회하는 근거 묶음(Evidence Bundle)을 제공한다.
가짜 목업이나 하드코딩된 더미 수치는 일체 사용하지 않는다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from investment_agent.dashboard.ops import read_harness_state
from investment_agent.reporting.readers.dashboard import load_guru_data, load_macro_window, load_price_history
from investment_agent.dashboard.components.theme import dashboard_palette
from investment_agent.dashboard.components.ui import result_payload
from investment_agent.trading.decision.signal_blender import SignalBlender

ROOT = Path(__file__).resolve().parents[3]
ACTIVE_POLICY_PATH = ROOT / "artifacts" / "trading" / "rl_policies" / "active_policy.json"


def _load_real_active_policy() -> dict[str, Any] | None:
    """실제 강화학습 승격 정책 메타데이터 로드 (없으면 None)."""
    if not ACTIVE_POLICY_PATH.exists():
        return None
    try:
        payload = json.loads(ACTIVE_POLICY_PATH.read_text(encoding="utf-8"))
        return payload
    except Exception:
        return None


def render_dsr_gauge(probability: float) -> go.Figure:
    """DSR 과적합 검정 반원형 게이지 차트 생성."""
    colors = dashboard_palette()
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=round(probability * 100, 1),
            number={"suffix": "%", "font": {"size": 36, "family": "JetBrains Mono"}},
            title={"text": "DSR 통계 신뢰도 (과적합 검정)", "font": {"size": 16}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": "#999"},
                "bar": {"color": colors.primary, "thickness": 0.25},
                "bgcolor": colors.surface,
                "borderwidth": 1,
                "bordercolor": colors.border,
                "steps": [
                    {"range": [0, 90], "color": "#ffebe8"},
                    {"range": [90, 95], "color": "#fbf0ea"},
                    {"range": [95, 100], "color": "#e8f7ee"},
                ],
                "threshold": {
                    "line": {"color": "#05b169", "width": 4},
                    "thickness": 0.8,
                    "value": 95,
                },
            },
        )
    )
    fig.update_layout(
        height=260,
        margin={"l": 20, "r": 20, "t": 40, "b": 20},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# 아래 차트는 **규칙을 보여주는 예시**다. 원장에서 읽은 값이 아니라 고정 입력이며,
# 화면이 사실이 아닌 것을 사실처럼 말하지 않도록 이름과 캡션에 그대로 적는다.
# 실제 판단에 쓰인 융합 결과는 portfolio proposal 원장에 남으므로, 그것을 읽는
# Reporting 계약이 준비되면 이 예시를 실제 값으로 교체한다.
_BLEND_EXAMPLE_RETURNS = {"AAPL": 0.05, "MSFT": 0.04, "NVDA": 0.08, "AMZN": 0.06, "GOOGL": 0.03}
_BLEND_EXAMPLE_CONFIDENCES = {"AAPL": 0.60, "MSFT": 0.55, "NVDA": 0.70, "AMZN": 0.50, "GOOGL": 0.45}


def render_blending_rule_chart(policy: dict[str, Any] | None) -> go.Figure:
    """예시 입력에 SignalBlender 규칙을 적용해 융합 방식을 보여주는 차트.

    DSR 확률만 실제 승격 정책에서 읽는다 — 그 값이 LLM/RL 가중치를 정하므로,
    규칙이 지금 어느 쪽에 무게를 두는지는 실제 상태를 반영한다.
    """
    colors = dashboard_palette()
    tickers = list(_BLEND_EXAMPLE_RETURNS)

    blender = SignalBlender(base_rl_weight=0.40, max_rl_weight=0.50, min_rl_weight=0.10)
    score = policy.get("score", {}) if policy else {}
    dsr_probability = score.get("dsr_probability", 0.95)

    # 실제 판단 경로(portfolio_shadow)와 같은 인자로 부른다 — 거기서 쓰지 않는
    # rl_target_weights를 넣으면 화면이 다른 규칙을 보여주게 된다.
    blended_map = blender.blend(
        llm_expected_returns=_BLEND_EXAMPLE_RETURNS,
        llm_confidences=_BLEND_EXAMPLE_CONFIDENCES,
        rl_dsr_probability=dsr_probability,
    )

    llm_vals = [_BLEND_EXAMPLE_RETURNS[t] * 100 for t in tickers]
    blended_vals = [blended_map[t].expected_return * 100 for t in tickers]

    fig = go.Figure()
    fig.add_trace(go.Bar(name="예시 LLM 기대수익률 (%)", x=tickers, y=llm_vals, marker_color=colors.muted))
    fig.add_trace(go.Bar(name="융합 결과 기대수익률 (%)", x=tickers, y=blended_vals, marker_color=colors.up))

    fig.update_layout(
        barmode="group",
        height=280,
        margin={"l": 20, "r": 20, "t": 20, "b": 20},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        xaxis={"title": "종목"},
        yaxis={"title": "신호 강도 (%)", "showgrid": True, "gridcolor": colors.border},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def blending_weights(policy: dict[str, Any] | None) -> tuple[float, float] | None:
    """승격된 정책의 DSR 확률이 만드는 (LLM 가중치, RL 가중치). 정책이 없으면 None.

    실제 판단 경로가 RL 목표비중을 넘기지 않으므로 RL 쪽 신호는 LLM 신호로 대체된다
    — 그래서 융합 결과 자체는 입력과 같아지고, DSR이 실제로 움직이는 것은 이 가중치뿐이다.

    정책이 없을 때 기본값으로 숫자를 만들어 내지 않는다. 승격된 것이 없는데 "RL 가중치 46%"가
    떠 있으면 강화학습이 배분에 관여하고 있다고 읽힌다 — 지금은 사실이 아니다.
    """
    score = policy.get("score", {}) if policy else {}
    dsr_probability = score.get("dsr_probability")
    if dsr_probability is None:
        return None
    blender = SignalBlender(base_rl_weight=0.40, max_rl_weight=0.50, min_rl_weight=0.10)
    rl_weight = blender.calculate_rl_weight(dsr_probability)
    return round(1.0 - rl_weight, 4), rl_weight


def show() -> None:
    """대시보드 페이지 렌더링."""
    st.title("AI & 강화학습(RL) 자율진화 관제 센터")
    st.caption("하네스 7대 전자동 잡의 실제 가동 상태와 PPO 자율 재학습 엔진의 실제 승격 결과를 모니터링합니다.")

    # 1. 하네스 7대 전자동 잡 실제 관제판
    st.subheader("1. 하네스 7대 전자동 잡 파이프라인")
    harness_res = read_harness_state()
    harness_state = result_payload(harness_res, default={}) or {}
    jobs = harness_state.get("jobs", {})

    job_specs = [
        ("scheduled_analysis", "종목 발굴 및 AI 분석", "24시간"),
        ("autonomous_investment", "CVXPY 최적화 및 주문", "1분"),
        ("feature_store", "피처 및 학습 데이터 생성", "24시간"),
        ("continuous_learning", "PPO 자율 재학습 및 승격", "24시간"),
        ("account_risk_snapshot", "계좌 잔고 리스크 스냅샷", "5분"),
        ("earnings_watch", "SEC 실시간 공시 감시", "1분"),
        ("toss_reconciliation", "체결 내역 및 잔고 대사", "1분"),
    ]

    cols = st.columns(4)
    for idx, (jid, title, interval) in enumerate(job_specs):
        col = cols[idx % 4]
        job_info = jobs.get(jid, {})
        status = job_info.get("last_status") or job_info.get("stage") or "대기 중"
        completed_at = job_info.get("completed_at") or job_info.get("heartbeat_at") or "미실행"
        if completed_at != "미실행" and len(completed_at) >= 19:
            completed_at = completed_at[:19].replace("T", " ")
        with col:
            st.metric(
                label=f"{title} ({interval})",
                value="가동 중" if status in {"succeeded", "capture", "idle"} else str(status),
                delta=f"최근: {completed_at}",
                border=True,
            )

    st.divider()

    # 2. 실제 PPO 강화학습 챔피언 정책 및 과적합 검정
    st.subheader("2. PPO 강화학습 챔피언 정책 & DSR 과적합 검정")
    real_policy = _load_real_active_policy()

    if real_policy is None:
        st.warning(
            "⚠️ **현재 승격된 실제 PPO 정책 파일이 없습니다.**\n\n"
            "아직 강화학습 재학습이 실행되지 않았습니다. 터미널에서 아래 명령을 실행하면 실제 훈련된 모델이 생성됩니다:\n"
            "`python -m investment_agent.research.commands.continuous_retrain`",
            icon=":material/warning:",
        )
    else:
        score = real_policy.get("score", {})
        col_g, col_s = st.columns([1, 1.4])
        with col_g:
            probability = float(score.get("dsr_probability", 0.0))
            st.plotly_chart(render_dsr_gauge(probability), width="stretch")
            if probability >= 0.95:
                st.success("✅ **검증된 알파(True Alpha)**: DSR 확률이 0.95 이상으로 다중 시험 과적합 기준을 통과했습니다.")
            else:
                st.warning(
                    f"⚠️ **과적합 주의 (DSR 확률={probability:.2f})**: "
                    "기준치(0.95) 미만으로 표본 검증이 더 필요합니다."
                )

        with col_s:
            st.markdown(f"**활성 정책 버전**: `{real_policy.get('policy_version', 'N/A')}`")
            st.caption(f"승격 일시: {real_policy.get('promoted_at', 'N/A')}")
            st.info(f"승격 사유: {real_policy.get('reason', 'N/A')}")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("샤프 비율", f"{score.get('sharpe_ratio', 0.0):.2f}")
            m2.metric("최대 낙폭(MDD)", f"-{score.get('max_drawdown', 0.0)*100:.1f}%")
            m3.metric("초과 수익률", f"+{score.get('excess_return', 0.0)*100:.1f}%")
            m4.metric("연간 턴오버", f"{score.get('turnover', 0.0):.1f}x")

    st.divider()

    # 3. SignalBlender 융합 규칙 (예시 입력)
    st.subheader("3. SignalBlender 동적 신호 융합 규칙")
    st.caption(
        "융합 알고리즘은 실제 SignalBlender이고, RL 가중치를 정하는 DSR 확률도 승격된 정책에서 읽습니다. "
        "다만 종목별 입력값은 규칙을 보여주기 위한 **예시**이며 실제 판단 기록이 아닙니다."
    )
    weights = blending_weights(real_policy)
    w1, w2 = st.columns(2)
    w1.metric("LLM 신호 가중치", f"{weights[0]:.0%}" if weights else "—", border=True)
    w2.metric("RL 정책 가중치", f"{weights[1]:.0%}" if weights else "—", border=True)
    if weights is None:
        st.warning(
            "승격된 PPO 정책이 없어 가중치를 계산할 값이 없습니다. 아래 그림은 "
            "**규칙이 어떻게 생겼는지**만 보여주는 예시이며, 지금 배분에 적용되는 값이 아닙니다.",
            icon=":material/warning:",
        )
    st.info(
        "현재 판단 경로는 RL 목표비중을 융합에 넘기지 않습니다. 그러면 RL 쪽 신호가 LLM 신호로 "
        "대체되어 **융합 결과는 입력과 같아집니다** — 아래 막대 두 개가 같은 이유입니다. "
        "DSR 확률이 실제로 움직이는 것은 위 가중치뿐입니다. 실제 판단에 쓰인 값은 포트폴리오 "
        "제안 원장에 남으며, 그것을 읽는 Reporting 계약이 준비되면 이 예시는 실제 값으로 바뀝니다.",
        icon=":material/science:",
    )
    st.plotly_chart(render_blending_rule_chart(real_policy), width="stretch")

    st.divider()

    # 4. 실제 시장/매크로 DB 연동 근거 묶음(Evidence Bundle) 탐색기
    st.subheader("4. 실제 DB 연동 근거 묶음 (Evidence Bundle) 탐색기")
    st.caption("저장된 market.prices_daily와 거시경제 DB에서 미래 데이터가 차단된 관측값을 조회합니다.")

    selected_ticker = st.selectbox(
        "분석 종목 선택",
        ("AAPL", "MSFT", "NVDA", "SPY", "QQQ"),
        key="real_evidence_ticker",
    )

    with st.expander(f"📈 [1] 실제 시장 주가 데이터 ({selected_ticker})", expanded=True):
        res = load_price_history((selected_ticker,), period="3mo")
        df_prices = result_payload(res)
        col_close = "Close" if isinstance(df_prices, pd.DataFrame) and "Close" in df_prices.columns else "close"
        if isinstance(df_prices, pd.DataFrame) and not df_prices.empty and col_close in df_prices.columns:
            last_close = float(df_prices[col_close].iloc[-1])
            prev_close = float(df_prices[col_close].iloc[0])
            ret_3m = ((last_close - prev_close) / prev_close) * 100
            
            c1, c2, c3 = st.columns(3)
            c1.metric("최근 종가", f"${last_close:.2f}")
            c2.metric("3개월 누적 수익률", f"{ret_3m:+.2f}%")
            c3.metric("총 관측 거래일수", f"{len(df_prices)}일")
            st.caption(f"원천: 저장된 market.prices_daily · 최근 관측일: {df_prices.index[-1]}")
        else:
            st.info(f"{selected_ticker}의 주가 데이터를 불러오는 중이거나 오프라인 상태입니다.")

    with st.expander("🌐 [2] 실제 거시경제 지표 (FRED DB)"):
        macro_res = load_macro_window()
        macro_rows = result_payload(macro_res, default=[]) or []
        latest = {}
        for row in macro_rows if isinstance(macro_rows, list) else []:
            key = str(row.get("series_id") or "")
            if key:
                latest[key] = row.get("value")
        if latest:
            cols = st.columns(min(4, len(latest)))
            for idx, (key, value) in enumerate(list(latest.items())[:4]):
                cols[idx % len(cols)].metric(key, str(value) if value is not None else "—")
        else:
            st.info("거시경제 DB(FRED) 연결 대기 중입니다.")

    with st.expander("🧙‍♂️ [3] 실제 13F 기관 슈퍼 인베스터 지분 (SEC EDGAR DB)"):
        guru_res = load_guru_data()
        guru_payload = result_payload(guru_res, default=[]) or []
        if guru_payload:
            st.write(guru_payload)
        else:
            st.info("Supabase 13F 기관 지분 원장 데이터 대기 중입니다.")


# Alpha Lab은 연구 파생물과 trading attribution read model을 함께 읽는다.
# 모델·학습 화면과 같은 관심사이므로 별도 탭으로 제공한다.
from investment_agent.dashboard.app_pages import intelligence  # noqa: E402

_lab_tab, _engine_tab = st.tabs(["모델·강화학습", "투자 엔진(Alpha Lab)"])
with _lab_tab:
    show()
with _engine_tab:
    intelligence.render()
