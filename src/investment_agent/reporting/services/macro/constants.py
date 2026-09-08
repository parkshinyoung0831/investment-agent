"""매크로 화면 표시에 쓰는 고정값(분류·아이콘·색상 등) 모음.

Dashboard와 매일 알림(core), 평일 알림(watch)이 함께 가져다 쓴다.
실제 '임계값 판단'은 thresholds.py, 숫자·카드 꾸미기는 format.py, HTML 렌더는 render.py가 맡는다.
이 파일은 외부 의존 없는 순수 정적 데이터만 둔다.
"""
from __future__ import annotations

from investment_agent.reporting.services.macro.palette import (
    ALERT, CAUTION, MUTED, PRIMARY, SEMANTIC_DOWN, SEMANTIC_UP, STALE, WATCH,
)

# 경고 등급 순서: 빨강 > 노랑 > 초록 (센 것부터).
TIER_ORDER = ["🔴 alert", "🟡 caution", "🟢 watch"]

# 채널 구분 SSOT: DB가 아니라 이 series_id 집합이 소유한다.
# CORE/WATCH 채널은 아래 집합이 소유한다. 발표 알림은 econ_calendar가 별도로 소유한다.
# 코어 카드 4열 레이아웃 SSOT — (섹션명, 아이콘, series 순서). 표시 순서가 곧 이 순서.
CORE_LAYOUT = [
    ("주식 · 크립토", "📈", ["SPY", "QQQ", "SOX", "RUT", "KOSPI", "KOSDAQ", "KR_FOREIGN_NET", "BTC"]),
    ("금리",          "💵", ["TNX", "US02Y", "KR_TB3Y", "KR_CD91"]),       # 미 곡선(2·10Y)+한 곡선(3Y·CD91)
    ("환율 · 금리차", "💱", ["DXY", "USDKRW", "JPYKRW", "SPREAD_10Y2Y"]),   # FX 3 + 장단기 스프레드
    ("원자재",        "🛢", ["WTI", "GOLD", "COPPER", "NATGAS"]),
]
# 카드 그리드 밖(헤더 리본)에 따로 표시: FEAR_GREED=레짐 게이지, VIX=리본 우측.
CORE_SENTIMENT = ["VIX", "FEAR_GREED"]
# CORE_SERIES는 레이아웃에서 파생 — 표시 목록과 채널 소유 집합이 어긋나지 않게.
CORE_SERIES = frozenset(
    [s for _n, _i, sids in CORE_LAYOUT for s in sids] + CORE_SENTIMENT
)  # 22 — 매일 보는 핵심 지표(항상 표시). 4섹션×4열 + 리본 심리 2.

WATCH_SERIES = frozenset({
    # 금리·FX 보조 (1) — JPYKRW는 코어 환율로 이동
    "TYX",
    # 스프레드·신용 (2) — SPREAD_10Y2Y는 코어 금리로 이동, 신용/3M 스프레드는 감시 유지
    "SPREAD_10Y3M", "HY_SPREAD",
    # 국내금리 (1) — KR_CD91은 코어 금리로 이동
    "KR_CORP_AA3Y",
    # 밸류에이션·시장 구조 (2)
    "CAPE", "BREADTH_200DMA",
    # 심리·기대 (3)
    "MOVE", "PCC", "BEI_10Y",
    # 크립토 (1)
    "ETH",
})  # 10 — 매일 평가하되 임계 통과한 것만 발송하는 감시 지표

# 시장 지표 카테고리 7종. DB엔 영문 키로 저장, 화면엔 CAT_LABEL로 한글 표기.
CAT_LABEL = {
    "equity_index": "주식·지수", "valuation": "밸류에이션", "rates": "금리",
    "fx_liquidity": "환율·유동성", "commodity": "원자재", "sentiment": "심리",
    "crypto": "크립토",
}
CAT_ICON = {
    "equity_index": "📈", "valuation": "📐", "rates": "💵",
    "fx_liquidity": "💱", "commodity": "🛢", "sentiment": "🧭",
    "crypto": "₿",
}

# watch 카드 순서: 등급 안에서 카테고리별로 묶음.
WATCH_CAT_ORDER = [
    "valuation", "rates", "fx_liquidity", "sentiment",
    "commodity", "crypto", "equity_index",
]

# core 상단 '시장 분위기' 줄에 쓰는 대표 지표 6종.
TONE_ALIAS = {
    "spy": "SPY", "tnx": "TNX", "dxy": "DXY",
    "gold": "GOLD", "wti": "WTI", "btc": "BTC",
}
# 200일 이동평균(MA200) 대비 위치를 표시할 종목.
MA200_TAG = {"SPY", "KOSPI", "BTC", "GOLD"}

# 올라가는 것이 나쁜 신호인 지표. 등락 색을 반대로 준다(상승=빨강).
# series_kind로는 갈리지 않는다 — HY_SPREAD는 spread, VIX·MOVE는 oscillator다.
INVERSE_SERIES = frozenset({"VIX", "MOVE", "HY_SPREAD"})

# 등급별 색상
LEVEL_COLOR = {"alert": ALERT, "caution": CAUTION, "watch": WATCH, None: PRIMARY}
DEFAULT_COLOR = PRIMARY
STALE_COLOR = STALE

SPARK_UP = SPARK_DOWN = PRIMARY

# 카드 배지 라벨 (core·watch 공용 SSOT).
BADGE_LABEL = {"alert": "ALERT", "caution": "CAUTION", "watch": "WATCH"}

# watch 등급 섹션 헤더(아이콘·라벨).
WATCH_TIER_LABEL = {
    "🔴 alert":   ("🔴", "ALERT — 즉시 주의"),
    "🟡 caution": ("🟠", "CAUTION — 주의"),
    "🟢 watch":   ("🟡", "WATCH — 관찰"),
}
