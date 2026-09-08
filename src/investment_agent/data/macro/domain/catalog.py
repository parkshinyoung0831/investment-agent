"""v1 시장 거시지표의 선언형 원천 카탈로그.

카탈로그는 DB seed와 같은 계약을 코드에서 재현한다. 수집 시에는 DB에 실제로 seed된
source identity를 다시 읽으므로, 코드가 존재하지 않는 source를 만들어 쓰지 않는다.
"""
from __future__ import annotations

from typing import Any


def _row(series_id: str, name_ko: str, source: str, source_params: dict[str, Any],
         series_kind: str, category: str, unit: str) -> dict[str, Any]:
    return {
        "series_id": series_id, "name_ko": name_ko, "source": source,
        "source_params": source_params, "series_kind": series_kind,
        "category": category, "frequency": "daily", "unit": unit,
    }


MARKET_INDICATOR_CATALOG: tuple[dict[str, Any], ...] = (
    _row("SPY", "S&P 500", "yfinance", {"ticker": "^GSPC"}, "price", "equity_index", "pts"),
    _row("QQQ", "NASDAQ 100", "yfinance", {"ticker": "^NDX"}, "price", "equity_index", "pts"),
    _row("RUT", "러셀 2000", "yfinance", {"ticker": "^RUT"}, "price", "equity_index", "pts"),
    _row("SOX", "필라델피아 반도체", "yfinance", {"ticker": "^SOX"}, "price", "equity_index", "pts"),
    _row("KOSPI", "KOSPI", "ecos", {"stat": "802Y001", "item": "0001000", "cycle": "D"}, "price", "equity_index", "pts"),
    _row("KOSDAQ", "KOSDAQ", "ecos", {"stat": "802Y001", "item": "0089000", "cycle": "D"}, "price", "equity_index", "pts"),
    _row("KR_FOREIGN_NET", "외국인 순매수", "ecos", {"stat": "802Y001", "item": "0030000", "cycle": "D"}, "flow", "equity_index", "억원"),
    _row("BREADTH_200DMA", "200일선 상회 비율", "market", {"ma_window": 200, "min_periods": 180, "min_coverage": 0.75, "validation": {"min_value": 0, "max_value": 100}}, "ratio", "valuation", "%"),
    _row("CAPE", "Shiller CAPE", "web_crawling", {"source": "multpl", "parser": "shiller_pe"}, "valuation", "valuation", "배"),
    _row("US02Y", "미 2년물 금리", "web_crawling", {"source": "treasury", "parser": "2y"}, "rate", "rates", "%"),
    _row("TNX", "미 10년물 금리", "web_crawling", {"source": "treasury", "parser": "10y"}, "rate", "rates", "%"),
    _row("TYX", "미 30년물 금리", "web_crawling", {"source": "treasury", "parser": "30y"}, "rate", "rates", "%"),
    _row("SPREAD_10Y2Y", "10Y-2Y 스프레드", "web_crawling", {"source": "treasury", "parser": "10y2y"}, "spread", "rates", "%"),
    _row("SPREAD_10Y3M", "10Y-3M 스프레드", "web_crawling", {"source": "treasury", "parser": "10y3m"}, "spread", "rates", "%"),
    _row("HY_SPREAD", "HY OAS", "fred", {"fred_id": "BAMLH0A0HYM2"}, "spread", "rates", "%"),
    _row("KR_TB3Y", "국고채 3년", "ecos", {"stat": "817Y002", "item": "010200000", "cycle": "D"}, "rate", "rates", "%"),
    _row("KR_CD91", "CD 91일", "ecos", {"stat": "817Y002", "item": "010502000", "cycle": "D"}, "rate", "rates", "%"),
    _row("KR_CORP_AA3Y", "회사채 AA- 3년", "ecos", {"stat": "817Y002", "item": "010300000", "cycle": "D"}, "rate", "rates", "%"),
    _row("DXY", "DXY", "yfinance", {"ticker": "DX-Y.NYB", "validation": {"min_value": 40, "max_value": 200, "max_abs_change_pct": 10}}, "fx", "fx_liquidity", "idx"),
    _row("USDKRW", "원/달러", "ecos", {"stat": "731Y001", "item": "0000001", "cycle": "D", "expected_item_name": "원/미국달러(매매기준율)", "expected_unit": "원", "validation": {"min_value": 500, "max_value": 3000, "max_abs_change_pct": 10}}, "fx", "fx_liquidity", "원/달러"),
    _row("JPYKRW", "원/100엔", "ecos", {"stat": "731Y001", "item": "0000002", "cycle": "D", "expected_item_name": "원/일본엔(100엔)", "expected_unit": "원", "validation": {"min_value": 300, "max_value": 2000, "max_abs_change_pct": 10}}, "fx", "fx_liquidity", "원/100엔"),
    _row("WTI", "WTI 원유", "yfinance", {"ticker": "CL=F"}, "price", "commodity", "$"),
    _row("GOLD", "금 선물", "yfinance", {"ticker": "GC=F"}, "price", "commodity", "$"),
    _row("COPPER", "구리 선물", "yfinance", {"ticker": "HG=F"}, "price", "commodity", "$"),
    _row("NATGAS", "천연가스", "yfinance", {"ticker": "NG=F"}, "price", "commodity", "$"),
    _row("BEI_10Y", "10Y BEI", "fred", {"fred_id": "T10YIE"}, "rate", "sentiment", "%"),
    _row("VIX", "VIX", "web_crawling", {"source": "cboe", "parser": "vix"}, "oscillator", "sentiment", "pts"),
    _row("MOVE", "MOVE", "yfinance", {"ticker": "^MOVE"}, "oscillator", "sentiment", "pts"),
    _row("PCC", "Put/Call 비율", "web_crawling", {"source": "cboe", "parser": "put_call"}, "oscillator", "sentiment", "배"),
    _row("FEAR_GREED", "CNN 공포탐욕", "web_crawling", {"source": "cnn", "parser": "fear_greed"}, "oscillator", "sentiment", "pts"),
    _row("BTC", "비트코인", "yfinance", {"ticker": "BTC-USD"}, "price", "crypto", "$"),
    _row("ETH", "이더리움", "yfinance", {"ticker": "ETH-USD"}, "price", "crypto", "$"),
)

SOURCE_CODES = tuple(sorted({str(row["source"]) for row in MARKET_INDICATOR_CATALOG}))

__all__ = ["MARKET_INDICATOR_CATALOG", "SOURCE_CODES"]
