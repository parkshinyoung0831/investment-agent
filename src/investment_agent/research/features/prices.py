"""지표 계산에 필요한 만큼의 market.prices_daily 롤링 윈도우를 읽어 온다.

Supabase 접근은 이 패키지의 db.py를 통해서만 한다(자체 클라이언트 생성 금지).
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from investment_agent.platform.logging import get_logger
from investment_agent.research.features import db

from . import ROLLING_DAYS

log = get_logger(__name__)


def load_prices(
    rolling_days: int = ROLLING_DAYS,
    *,
    end_date: dt.date | None = None,
) -> pd.DataFrame:
    """최근 rolling_days 거래일 분량의 prices_daily(전 종목) → DataFrame.

    반환 컬럼: ticker · trade_date · close (ticker·trade_date 오름차순)
    재귀 지표(RSI·MACD)는 종목별 시계열이 연속이어야 하므로 정렬이 필수.
    """
    # 거래일 → 달력일 환산(주말·휴장 여유) + 워밍업 버퍼.
    anchor = end_date or dt.datetime.now(dt.timezone.utc).date()
    since = (
        anchor - dt.timedelta(days=rolling_days * 7 // 5 + 15)
    ).isoformat()
    rows = db.load_market_prices_since(since)
    df = pd.DataFrame(rows)
    log.info("loaded %d price rows since %s", len(df), since)
    if not df.empty:
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        df.sort_values(["ticker", "trade_date"], inplace=True, ignore_index=True)
    return df
