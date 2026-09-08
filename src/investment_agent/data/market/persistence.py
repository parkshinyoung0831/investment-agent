"""v1 market 저장·조회 계층.

외부 경계는 ticker지만 market 표에는 항상 ``security_id``를 쓴다.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

import pandas as pd
from dateutil.relativedelta import relativedelta

from investment_agent.platform.db.postgres import sb
from investment_agent.data.market.domain.actions import merge_corporate_actions
from investment_agent.data.market.domain.models import DailyBar, DividendEvent, SplitEvent
from investment_agent.data.market.repository import (
    SCHEMA as SCHEMA_MARKET,
    T_DIVIDENDS,
    T_PRICES,
    T_SPLITS,
    MarketRepository,
)
from investment_agent.data.market import REFERENCE_PRICE_TICKERS
from investment_agent.data.universe.repository import SCHEMA as SCHEMA_UNIVERSE
from investment_agent.data.universe.repository import UniverseRepository
from investment_agent.platform.db.postgres import Database

SCHEMA_MARKET = SCHEMA_MARKET
T_PRICES_DAILY = T_PRICES
T_SPLIT_EVENTS = T_SPLITS
T_DIVIDEND_EVENTS = T_DIVIDENDS

_database: Database | None = None


def configure(db: Database) -> None:
    global _database
    _database = db


def _db() -> Database:
    return _database or Database(sb)


def _universe() -> UniverseRepository:
    return UniverseRepository(_db())


def _ids(tickers: list[str]) -> dict[str, int]:
    return _universe().security_ids(tickers)


def universe_company_tickers() -> list[str]:
    return _universe().tracked_tickers()


def universe_tracked() -> list[str]:
    return sorted(set(universe_company_tickers()) | set(REFERENCE_PRICE_TICKERS))


def universe_missing_prices() -> list[str]:
    securities = _universe().tracked_securities()
    if not securities:
        return []
    present = MarketRepository(_db()).security_ids_with_prices(
        [security.security_id for security in securities]
    )
    return [security.ticker for security in securities if security.security_id not in present]


def latest_price_date() -> str | None:
    result = MarketRepository(_db()).latest_price_date()
    return result.isoformat() if result else None


def prices_since(since: str) -> dict[tuple[str, str], dict]:
    rows = MarketRepository(_db()).prices_since(date.fromisoformat(since))
    security_ids = {int(row["security_id"]) for row in rows}
    id_to_ticker = _universe().tickers_by_security_id(security_ids)
    return {
        (id_to_ticker[int(row["security_id"])], str(row["trade_date"])): {
            "ticker": id_to_ticker[int(row["security_id"])],
            **{key: row.get(key) for key in ("trade_date", "open", "high", "low", "close", "volume", "is_repaired")},
        }
        for row in rows
        if int(row["security_id"]) in id_to_ticker
    }


def upsert_prices(rows: list[dict]) -> int:
    if not rows:
        return 0
    ids = _ids([str(row["ticker"]) for row in rows])
    bars = [
        DailyBar.from_row({**row, "security_id": ids[str(row["ticker"]).upper()]})
        for row in rows
        if str(row["ticker"]).upper() in ids
    ]
    if len(bars) != len(rows):
        missing = sorted({str(row["ticker"]).upper() for row in rows} - set(ids))
        raise RuntimeError(f"market write has unknown securities: {missing[:10]}")
    return MarketRepository(_db()).upsert_bars(bars)


def _event_rows(rows: list[dict], *, kind: str) -> list[SplitEvent | DividendEvent]:
    ids = _ids([str(row["ticker"]) for row in rows])
    result = []
    for row in rows:
        ticker = str(row["ticker"]).upper()
        if ticker not in ids:
            raise RuntimeError(f"market event has unknown security: {ticker}")
        payload = {**row, "security_id": ids[ticker]}
        result.append(SplitEvent.from_row(payload) if kind == "split" else DividendEvent.from_row(payload))
    return result


def upsert_split_events(rows: list[dict]) -> int:
    return MarketRepository(_db()).upsert_splits(_event_rows(rows, kind="split")) if rows else 0


def upsert_dividend_events(rows: list[dict]) -> int:
    return MarketRepository(_db()).upsert_dividends(_event_rows(rows, kind="dividend")) if rows else 0


def _events_as_tickers(tickers: list[str] | None, *, kind: str) -> list[dict]:
    db = _db()
    repo = _universe()
    ids = _ids(tickers or universe_tracked())
    if not ids:
        return []
    table = T_SPLITS if kind == "split" else T_DIVIDENDS
    columns = "security_id,action_date,split_ratio" if kind == "split" else "security_id,ex_date,div_amount"
    rows = db.select_in_chunks(
        schema=SCHEMA_MARKET,
        table=table,
        columns=columns,
        filter_column="security_id",
        values=list(ids.values()),
        order_by="security_id",
    )
    by_id = {security.security_id: security.ticker for security in repo.securities_by_ticker(list(ids)).values()}
    output = []
    for row in rows:
        ticker = by_id.get(int(row["security_id"]))
        if not ticker:
            continue
        output.append({"ticker": ticker, **{key: value for key, value in row.items() if key != "security_id"}})
    return output


def select_split_events(tickers: list[str] | None = None) -> list[dict]:
    return _events_as_tickers(tickers, kind="split")


def select_dividend_events(tickers: list[str] | None = None) -> list[dict]:
    return _events_as_tickers(tickers, kind="dividend")


def _ticker_id(ticker: str) -> int | None:
    return _ids([ticker]).get(str(ticker).upper())


def _price_rows(ticker: str, *, start: date, end: date, known_at: datetime | None = None) -> list[dict]:
    security_id = _ticker_id(ticker)
    if security_id is None:
        return []
    bars = MarketRepository(_db()).bars([security_id], start=start, end=end, known_at=known_at)
    return [
        {"ticker": ticker.upper(), **bar.as_row(), "trade_date": bar.trade_date.isoformat()}
        for bar in bars
    ]


def price_history_as_of(ticker: str, as_of_at: datetime, *, limit: int = 260) -> list[dict]:
    if as_of_at.tzinfo is None:
        raise ValueError("as_of_at must include timezone")
    rows = _price_rows(ticker, start=date(1900, 1, 1), end=as_of_at.date(), known_at=as_of_at)
    rows = rows[-limit:]
    if not rows:
        return []
    first = date.fromisoformat(str(rows[0]["trade_date"]))
    last = date.fromisoformat(str(rows[-1]["trade_date"]))
    security_id = _ticker_id(ticker)
    repo = MarketRepository(_db())
    dividends = [event.as_row() for event in repo.dividends([security_id], since=first) if event.ex_date <= last]
    splits = [event.as_row() for event in repo.splits([security_id], since=first) if event.action_date <= last]
    for row in dividends:
        row["ticker"] = ticker.upper()
        row["ex_date"] = str(row["ex_date"])
    for row in splits:
        row["ticker"] = ticker.upper()
        row["action_date"] = str(row["action_date"])
    return merge_corporate_actions(rows, dividends, splits)


def price_window_as_of(
    tickers: Sequence[str], *, start: date, as_of_at: datetime
) -> list[dict]:
    """여러 종목의 한 창을 한 번에 읽는다.

    종목마다 `price_history_as_of`를 부르면 종목당 왕복이 네 번이고(증권 id·봉·
    배당·분할), 봉은 1900년부터 전부 읽은 뒤 뒤에서 잘라 낸다. 후보 선정은 창
    안의 종가·거래량만 보므로 그 값을 치를 이유가 없다 — 실측 106초가 여기였다.

    배당·분할은 붙이지 않는다. 필요하면 `price_history_as_of`가 그 계약을 갖는다.
    """
    if as_of_at.tzinfo is None:
        raise ValueError("as_of_at must include timezone")
    ids = _ids(sorted({str(value).upper() for value in tickers}))
    if not ids:
        return []
    ticker_by_id = {int(security_id): ticker for ticker, security_id in ids.items()}
    bars = MarketRepository(_db()).bars(
        sorted(ticker_by_id), start=start, end=as_of_at.date(), known_at=as_of_at
    )
    rows = [
        {**bar.as_row(), "ticker": ticker_by_id[int(bar.security_id)],
         "trade_date": bar.trade_date.isoformat()}
        for bar in bars
        if int(bar.security_id) in ticker_by_id
    ]
    return sorted(rows, key=lambda row: (row["ticker"], row["trade_date"]))


def close_history_as_of(ticker: str, as_of_at: datetime, *, max_bars: int = 2100) -> list[dict]:
    rows = _price_rows(ticker, start=date(1900, 1, 1), end=as_of_at.date(), known_at=as_of_at)
    return [{"ticker": ticker.upper(), "trade_date": row["trade_date"], "close": row["close"]} for row in rows[-max_bars:]]


def forward_closes_after(ticker: str, *, after_date: str, limit: int = 40) -> list[dict]:
    rows = _price_rows(ticker, start=date.fromisoformat(after_date), end=date.today())
    return [
        {"ticker": ticker.upper(), "trade_date": row["trade_date"], "close": row["close"]}
        for row in rows
        if str(row["trade_date"]) > str(after_date)
    ][:limit]


def price_path_from(ticker: str, start_date: date, *, limit: int = 80) -> list[dict]:
    rows = _price_rows(ticker, start=start_date, end=date.today())[:limit]
    if not rows:
        return []
    last = date.fromisoformat(str(rows[-1]["trade_date"]))
    security_id = _ticker_id(ticker)
    dividends = [event.as_row() for event in MarketRepository(_db()).dividends([security_id], since=start_date) if event.ex_date <= last]
    for row in dividends:
        row["ticker"] = ticker.upper()
        row["ex_date"] = str(row["ex_date"])
    return merge_corporate_actions(rows, dividends, [])


def monthly_close_history(tickers: list[str], *, period: str = "2y") -> pd.DataFrame:
    """저장된 일봉을 완료 월말 종가 표로 변환한다.

    전략은 외부 provider가 아니라 market owner가 검증·적재한 관측값만 읽는다.
    ``period='max'``는 market의 보존 범위 전체를 뜻한다.
    """
    requested = [str(ticker).upper().strip() for ticker in tickers]
    if not requested or any(not ticker for ticker in requested):
        raise ValueError("market monthly history requires at least one ticker")
    if len(requested) != len(set(requested)):
        raise ValueError("market monthly history ticker list contains duplicates")
    if period == "max":
        start = date(1900, 1, 1)
    elif period.endswith("y") and period[:-1].isdigit() and int(period[:-1]) > 0:
        start = date.today() - relativedelta(years=int(period[:-1]))
    else:
        raise ValueError(f"unsupported market monthly history period: {period}")
    ids = _ids(requested)
    missing = sorted(set(requested) - set(ids))
    if missing:
        raise RuntimeError(f"market has unknown strategy securities: {missing}")
    bars = MarketRepository(_db()).bars(list(ids.values()), start=start, end=date.today())
    rows = [
        {"ticker": ticker, "trade_date": bar.trade_date, "close": bar.close}
        for ticker, security_id in ids.items()
        for bar in bars if bar.security_id == security_id
    ]
    if not rows:
        return pd.DataFrame(columns=requested, dtype=float)
    daily = pd.DataFrame(rows)
    monthly = daily.pivot(index="trade_date", columns="ticker", values="close")
    monthly.index = pd.to_datetime(monthly.index)
    return monthly.sort_index().resample("ME").last().reindex(columns=requested)


__all__ = [
    "SCHEMA_MARKET", "SCHEMA_UNIVERSE", "T_PRICES_DAILY", "T_SPLIT_EVENTS",
    "T_DIVIDEND_EVENTS", "configure", "universe_tracked", "universe_company_tickers",
    "universe_missing_prices", "latest_price_date", "prices_since", "upsert_prices",
    "upsert_split_events", "upsert_dividend_events", "select_split_events",
    "select_dividend_events", "price_history_as_of", "close_history_as_of",
    "forward_closes_after", "price_path_from", "monthly_close_history",
]
