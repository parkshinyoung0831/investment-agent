"""무엇을 다룰 것인가 — 회사·증권 identity와 지수 membership.

여기 없는 종목은 수집도 판단도 하지 않는다. 다른 모든 데이터가 이 게이트를 지난다.
"""
from __future__ import annotations

SP500_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
# S&P 500 구성종목이 아니지만 시세를 들고 있어야 하는 벤치마크들. 대부분은 자산배분
# 전략이 읽는 자산군·섹터 ETF다 — SEC의 기업 상장 목록에는 없어서 투자회사 클래스
# 목록으로 따로 등록하고, 빠지면 market 수집 계획이 security_id를 못 찾아 멈춘다.
# QQQ는 전략 자산이 아니라 화면이 비교 대상으로 읽는 벤치마크다.
REFERENCE_PRICE_TICKERS = (
    "SPY", "QQQ", "DBC",
    "AGG", "BIL", "IEF", "TIP", "TLT",
    "EEM", "EFA", "IWM", "SCZ", "VNQ",
    "XLB", "XLC", "XLE", "XLF", "XLI",
    "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY",
)

__all__ = ["REFERENCE_PRICE_TICKERS", "SP500_WIKI_URL"]
