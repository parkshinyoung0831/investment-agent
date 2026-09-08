"""ATLAS 읽기 전용 투자 대시보드 진입점."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 대시보드도 진입점이다 — `.env`를 여기서 한 번 읽는다. 빠뜨리면 모든 화면이
# "필수 연결 설정이 없습니다"로만 뜨고, 그것은 연결 실패와 구분되지 않는다.
# OS 환경변수가 이미 있으면 그것을 덮지 않는다(start_cli는 override=False).
from investment_agent.bootstrap import start_cli  # noqa: E402 - sys.path 설정 뒤여야 한다

start_cli()

st.set_page_config(
    page_title="ATLAS 투자 터미널",
    page_icon=":material/monitoring:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 화면 폭만 줄이는 대신, 실제 사용 기기 다섯 종류의 읽기 밀도를 공통 규칙으로 둔다.
# 24형 모니터 · MacBook 15형 · MacBook 13형 · iPad mini · iPhone 17 순서다.
st.html("""
    <style>
    /* 24형 모니터: 넓은 작업 공간을 쓰되 좌우 여백은 일정하게 유지한다. */
    @media (min-width: 1920px) {
        [data-testid="stMainBlockContainer"] {
            padding-left: 48px !important;
            padding-right: 48px !important;
        }
        [data-testid="stMainBlockContainer"] h1 {
            font-size: 2.15rem !important;
        }
    }
    /* MacBook 15형은 기본 wide 레이아웃을 그대로 사용한다. */
    /* MacBook 13형: 넓은 3열 구조는 유지하되 여백과 긴 문장의 밀도를 낮춘다. */
    @media (max-width: 1439px) {
        [data-testid="stMainBlockContainer"] {
            padding-left: 24px !important;
            padding-right: 24px !important;
        }
        [data-testid="stMainBlockContainer"] h1 {
            font-size: 1.9rem !important;
            line-height: 1.25 !important;
        }
        [data-testid="stMainBlockContainer"] h2 {
            font-size: 1.45rem !important;
        }
        [data-testid="stMainBlockContainer"] h3 {
            font-size: 1.2rem !important;
            line-height: 1.4 !important;
        }
        [data-testid="stMainBlockContainer"] [data-testid="stMarkdownContainer"] p,
        [data-testid="stMainBlockContainer"] [data-testid="stCaptionContainer"] {
            line-height: 1.5 !important;
        }
    }
    /* iPad mini: 카드와 주요 지표를 두 칸으로 재배치한다. */
    @media (max-width: 1023px) {
        [data-testid="stMainBlockContainer"] {
            padding-left: 20px !important;
            padding-right: 20px !important;
        }
        [data-testid="stMainBlockContainer"] h1 {
            font-size: 1.75rem !important;
        }
        [data-testid="stMainBlockContainer"] h2 {
            font-size: 1.35rem !important;
        }
        [data-testid="stMainBlockContainer"] h3 {
            font-size: 1.12rem !important;
        }
        [data-testid="stMainBlockContainer"] [data-testid="stMetricValue"] {
            font-size: 1.65rem !important;
        }
        [data-testid="stMainBlockContainer"] [data-testid="stButton"] > button {
            min-height: 44px;
        }
        [data-testid="stMainBlockContainer"] .stHorizontalBlock:has([data-testid="stMetric"]) {
            display: grid !important;
            grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
            gap: 12px !important;
        }
        [data-testid="stMainBlockContainer"] .stHorizontalBlock:has([data-testid="stMetric"]) > [data-testid="stColumn"] {
            width: auto !important;
            min-width: 0 !important;
        }
        [data-testid="stDataFrame"] {
            max-width: 100% !important;
            overflow-x: auto !important;
        }
        /* 카드 목록은 태블릿에서 두 칸, 좁은 휴대폰에서는 한 칸으로 읽는다. */
        div[class*="st-key-macro_card_grid_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"],
        div[class*="st-key-guru_manager_grid_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"],
        div[class*="st-key-quant_strategy_grid_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] {
            display: grid !important;
            grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
            gap: 12px !important;
        }
        div[class*="st-key-macro_card_grid_"] [data-testid="stColumn"],
        div[class*="st-key-guru_manager_grid_"] [data-testid="stColumn"],
        div[class*="st-key-quant_strategy_grid_"] [data-testid="stColumn"] {
            width: auto !important;
            min-width: 0 !important;
        }
        div[class*="st-key-macro_overview_grid"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"],
        div[class*="st-key-home_overview_grid"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"],
        div[class*="st-key-intel_query_inputs"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] {
            display: grid !important;
            grid-template-columns: minmax(0, 1fr) !important;
            gap: 12px !important;
        }
        div[class*="st-key-macro_overview_grid"] [data-testid="stColumn"],
        div[class*="st-key-home_overview_grid"] [data-testid="stColumn"],
        div[class*="st-key-intel_query_inputs"] [data-testid="stColumn"] {
            width: auto !important;
            min-width: 0 !important;
        }
        [data-testid="stDialog"] > div[role="dialog"] {
            width: calc(100vw - 40px) !important;
            max-width: 620px !important;
        }
        div[class*="st-key-guru_portfolio_donut_"] {
            display: none !important;
        }
    }
    /* iPhone 17: 한 손으로 읽는 순서로 전환하고 수치가 잘리지 않게 한다. */
    @media (max-width: 743px) {
        [data-testid="stMainBlockContainer"] {
            padding-left: 16px !important;
            padding-right: 16px !important;
        }
        [data-testid="stMainBlockContainer"] h1 {
            font-size: 1.55rem !important;
        }
        [data-testid="stMainBlockContainer"] h2 {
            font-size: 1.25rem !important;
        }
        [data-testid="stMainBlockContainer"] h3 {
            font-size: 1.05rem !important;
        }
        [data-testid="stMainBlockContainer"] [data-testid="stMetricValue"] {
            font-size: 1.5rem !important;
            line-height: 1.15 !important;
        }
        /* 13F 상세의 네 가지 요약값은 한 번에 비교할 수 있게 작은 4열로 압축한다. */
        div[class*="st-key-guru_portfolio_summary_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] {
            display: grid !important;
            grid-template-columns: repeat(4, minmax(0, 1fr)) !important;
            gap: 6px !important;
        }
        div[class*="st-key-guru_portfolio_summary_"] [data-testid="stColumn"] {
            width: auto !important;
            min-width: 0 !important;
        }
        div[class*="st-key-guru_portfolio_summary_"] [data-testid="stMetric"] {
            min-width: 0 !important;
            padding: 0.5rem !important;
        }
        div[class*="st-key-guru_portfolio_summary_"] [data-testid="stMetricLabel"] {
            font-size: 0.68rem !important;
            line-height: 1.3 !important;
        }
        div[class*="st-key-guru_portfolio_summary_"] [data-testid="stMetricValue"] {
            font-size: 1rem !important;
            line-height: 1.15 !important;
        }
        [data-testid="stMainBlockContainer"] [data-testid="stMarkdownContainer"] p {
            font-size: 0.95rem !important;
            line-height: 1.55 !important;
        }
        [data-testid="stMainBlockContainer"] [data-testid="stCaptionContainer"] {
            font-size: 0.84rem !important;
            line-height: 1.5 !important;
        }
        div[class*="st-key-macro_card_grid_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"],
        div[class*="st-key-guru_manager_grid_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"],
        div[class*="st-key-quant_strategy_grid_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] {
            grid-template-columns: minmax(0, 1fr) !important;
        }
        div[class*="st-key-home_action_grid"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] {
            display: grid !important;
            grid-template-columns: minmax(0, 1fr) !important;
            gap: 12px !important;
        }
        div[class*="st-key-home_action_grid"] [data-testid="stColumn"] {
            width: auto !important;
            min-width: 0 !important;
        }
        [data-testid="stDialog"] > div[role="dialog"] {
            width: calc(100vw - 24px) !important;
            max-width: none !important;
        }
    }
    @media (min-width: 1024px) {
        div[class*="st-key-guru_portfolio_bar_"] {
            display: none !important;
        }
    }
    </style>
""")

from investment_agent.dashboard.components.ui import format_time  # noqa: E402


def _sidebar_status() -> None:
    """사이드바에 현재 하네스 상태만 간결하게 표시한다."""

    state_path = ROOT / "artifacts" / "ops" / "investment_harness" / "state.json"
    st.sidebar.caption("운영 상태")
    offline = os.getenv("DASHBOARD_OFFLINE", "").strip().lower() in {"1", "true", "yes", "on"}
    if offline:
        st.sidebar.badge("오프라인", icon=":material/cloud_off:", color="orange")
    # 상태 문구는 하네스의 실제 상태를 그대로 보여 주되, 좁은 사이드바에서도
    # 잘리지 않도록 이 카드의 값 크기만 유동적으로 제한한다.
    st.html("""
        <style>
        div[class*="st-key-sidebar_harness_metric"] [data-testid="stMetricValue"] {
            font-size: clamp(1.1rem, 2.4vw, 1.35rem);
            line-height: 1.2;
            overflow-wrap: anywhere;
        }
        </style>
    """)
    try:
        from investment_agent.dashboard.ops import read_harness_state

        result = read_harness_state(state_path)
        payload = getattr(result, "value", None) or {}
        health = payload.get("health", {}) if isinstance(payload, dict) else {}
        label = health.get("label") or health.get("status") or getattr(result, "status", "unknown")
        with st.sidebar.container(key="sidebar_harness_metric"):
            st.metric("하네스", str(label), border=True)
        heartbeat = payload.get("process_heartbeat_at") if isinstance(payload, dict) else None
        st.sidebar.caption("최근 상태 신호")
        st.sidebar.caption(format_time(heartbeat))
    except (ImportError, OSError, ValueError, TypeError) as exc:
        with st.sidebar.container(key="sidebar_harness_metric"):
            st.metric("하네스", "상태를 읽지 못했어요", border=True)
        st.sidebar.caption(type(exc).__name__)
navigation = st.navigation(
    {
        # 세 갈래로만 나눈다 — 가진 데이터 / 내 돈 / 그 둘을 잇는 판단.
        # 홈과 시스템은 어디에도 속하지 않아 단독으로 둔다.
        "": [
            st.Page(
                "app_pages/home.py",
                title="홈",
                icon=":material/space_dashboard:",
                default=True,
            ),
        ],
        "가지고 있는 데이터": [
            st.Page("app_pages/macro.py", title="매크로", icon=":material/public:"),
            st.Page("app_pages/econ_calendar.py", title="지표 발표", icon=":material/event:"),
            st.Page("app_pages/earnings.py", title="실적", icon=":material/finance:"),
            st.Page("app_pages/gurus.py", title="13F", icon=":material/radar:"),
            st.Page("app_pages/news_social.py", title="뉴스·소셜", icon=":material/newspaper:"),
            st.Page("app_pages/quant.py", title="시세·지표", icon=":material/query_stats:"),
        ],
        "내 포트폴리오": [
            st.Page("app_pages/portfolio.py", title="보유·계좌", icon=":material/account_balance_wallet:"),
            st.Page("app_pages/execution.py", title="주문·체결", icon=":material/route:"),
        ],
        "투자·매매 로직": [
            st.Page("app_pages/decision_flow.py", title="판단 과정", icon=":material/account_tree:"),
            st.Page("app_pages/ml_rl_lab.py", title="모델·학습", icon=":material/psychology:"),
        ],
        "시스템": [
            st.Page("app_pages/system.py", title="시스템", icon=":material/settings_input_component:"),
        ],
    },
    position="sidebar",
)
_sidebar_status()
navigation.run()
