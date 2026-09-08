"""전략 계산용 상수 모음 (매매 대상 종목·계산 기간)."""
from __future__ import annotations

from investment_agent.research.strategies.catalog import TICKER_LABELS

# 분석 대상 ETF 23종
TICKERS = list(TICKER_LABELS)
SPDR_SECTORS         = ["XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY"]
GTAA5_ASSETS         = ["SPY", "EFA", "IEF", "DBC", "VNQ"]
# HAA 카나리아(위험 신호등): TIP 점수 0 이하면 안전자산 대피
HAA_CANARY           = ["TIP"]
HAA_BAL_OFFENSIVE    = ["SPY", "IWM", "EFA", "EEM", "VNQ", "DBC", "IEF", "TLT"]
HAA_SIM_OFFENSIVE    = ["SPY", "EFA", "VNQ", "IEF"]
MIN_MONTHS           = 13     # 최소 데이터 13개월 (미만 종목 제외)
SMA_MONTHS           = 10     # 추세 판단용 10개월 평균선

# 백필 기본 시작 월(apply_date 기준). 워크플로가 아니라 여기가 SSOT다.
BACKFILL_FROM = "2017-01"
