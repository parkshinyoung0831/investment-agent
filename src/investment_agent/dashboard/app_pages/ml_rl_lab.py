"""AI·강화학습(ML/RL) 자율진화 관제 랩 대시보드 페이지.

하네스 7대 전자동 잡의 실제 실행 상태, PPO 강화학습 챔피언 정책 파일(active_policy.json),
Lopez de Prado의 DSR 과적합 검정 게이지, RL 연구 후보의 역할 설명,
그리고 실제 시장·매크로 DB 데이터를 조회하는 근거 묶음(Evidence Bundle)을 제공한다.
가짜 목업이나 하드코딩된 더미 수치는 일체 사용하지 않는다.
"""
from __future__ import annotations

import json
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from investment_agent.dashboard.ops import read_harness_state
from investment_agent.platform.storage_paths import rl_policy_dir
from investment_agent.reporting.readers.dashboard import load_guru_data, load_macro_window, load_price_history
from investment_agent.dashboard.components.theme import dashboard_palette
from investment_agent.dashboard.components.ui import result_payload

ACTIVE_POLICY_PATH = rl_policy_dir() / "active_policy.json"


class ActivePolicyUnreadable(RuntimeError):
    """정책 파일은 있는데 읽거나 해석하지 못했다 — '아직 챔피언 없음'과 다른 상태다."""


def _load_real_active_policy() -> dict[str, Any] | None:
    """실제 강화학습 승격 정책 메타데이터 로드. 파일이 없으면 None, 있는데 손상됐으면 예외."""
    if not ACTIVE_POLICY_PATH.exists():
        return None
    try:
        payload = json.loads(ACTIVE_POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ActivePolicyUnreadable(f"{ACTIVE_POLICY_PATH.name}을 읽지 못했습니다({type(exc).__name__})") from exc
    if not isinstance(payload, dict):
        raise ActivePolicyUnreadable(f"{ACTIVE_POLICY_PATH.name}의 형식이 올바르지 않습니다")
    return payload


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


def show() -> None:
    """대시보드 페이지 렌더링."""
    st.title("AI & 강화학습(RL) 자율진화 관제 센터")
    st.caption("하네스 잡의 실제 가동 상태와 PPO 연구 후보의 검증 결과를 봅니다. RL은 연구 후보이며 System·실계좌 비중을 바꾸지 않습니다.")

    # 1. 하네스 잡 관제판
    st.subheader("1. 하네스 잡 파이프라인")
    harness_res = read_harness_state()
    harness_state = result_payload(harness_res, default={}) or {}
    jobs = harness_state.get("jobs", {})

    job_specs = [
        ("local_mirror", "Supabase 원본 로컬 사본 동기화", "2시간"),
        ("feature_store", "피처 및 학습 데이터 생성", "24시간"),
        ("investment_analysis", "TradingAgents 논지 분석", "3시간"),
        ("event_reanalysis", "사건 기반 재분석", "10분"),
        ("system_portfolio", "System Portfolio 평가·목표", "1시간"),
        ("my_portfolio_follow", "My Portfolio 추종 승인·주문", "승인 모드"),
        ("ml_challengers", "ML 후보 학습·비교", "7일"),
        ("continuous_learning", "PPO 연구 후보(새 성숙 구간 있을 때만)", "7일"),
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
    try:
        real_policy = _load_real_active_policy()
        policy_error = None
    except ActivePolicyUnreadable as exc:
        real_policy, policy_error = None, str(exc)

    if policy_error is not None:
        st.error(f"활성 정책 파일 오류: {policy_error}", icon=":material/error:")
    elif real_policy is None:
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

    # 3. RL의 역할
    st.subheader("3. RL 정책의 역할 — 오프라인 연구 후보")
    st.info(
        "RL 정책은 System Portfolio를 움직이지 않는 연구 후보입니다. 과거 재현·walk-forward 평가로만 "
        "System과 비교하고, 별도 가상계좌를 운영하지 않습니다. 비중을 기대수익으로 되돌려 섞으면 이미 "
        "반영된 위험·비용을 두 번 세기 때문입니다.",
        icon=":material/science:",
    )

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
