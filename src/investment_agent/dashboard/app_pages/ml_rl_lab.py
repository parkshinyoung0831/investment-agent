"""AI 관제 랩 대시보드 페이지.

하네스 잡의 실제 실행 상태와, 실제 시장·매크로 DB 데이터를 조회하는 근거 묶음(Evidence Bundle)을 보여 준다.
가짜 목업이나 하드코딩된 더미 수치는 일체 사용하지 않는다.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from investment_agent.dashboard.ops import read_harness_state
from investment_agent.reporting.readers.dashboard import load_guru_data, load_macro_window, load_price_history
from investment_agent.dashboard.components.ui import result_payload


def show() -> None:
    """대시보드 페이지 렌더링."""
    st.title("AI 관제 센터")
    st.caption("하네스 잡의 실제 가동 상태와, 판단이 읽는 근거 묶음을 봅니다.")

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
        ("my_portfolio_follow", "My Portfolio 추종 승인 요청·주문", "1분"),
        ("ml_challengers", "ML 후보 학습·비교", "7일"),
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

    # 2. 실제 시장/매크로 DB 연동 근거 묶음(Evidence Bundle) 탐색기
    st.subheader("2. 실제 DB 연동 근거 묶음 (Evidence Bundle) 탐색기")
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
