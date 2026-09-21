"""v1 market 저장·조회 계층.

외부 경계는 ticker지만 market 표에는 항상 ``security_id``를 쓴다. 쓰기 경로는 수집
계획(`PriceTarget`)이 이미 고정한 security_id만 받는다 — 여기서 ticker를 다시 풀지 않는다.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from datetime import date, datetime, timedelta

import pandas as pd
from dateutil.relativedelta import relativedelta

from investment_agent.platform.clock import us_market_today
from investment_agent.platform.db.postgres import sb
from investment_agent.data.market.domain.actions import merge_corporate_actions
from investment_agent.data.market.domain.models import DailyBar, PriceTarget
from investment_agent.data.market.repository import (
    SCHEMA as SCHEMA_MARKET,
    T_ACTIONS,
    T_PRICES,
    MarketRepository,
)
from investment_agent.data.market import REFERENCE_PRICE_TICKERS
from investment_agent.data.universe.repository import SCHEMA as SCHEMA_UNIVERSE
from investment_agent.data.universe.repository import UniverseRepository
from investment_agent.platform.db.postgres import Database

SCHEMA_MARKET = SCHEMA_MARKET
T_PRICES_DAILY = T_PRICES
T_ACTIONS_DAILY = T_ACTIONS

_database: Database | None = None


def configure(db: Database) -> None:
    global _database
    _database = db


def _db() -> Database:
    return _database or Database(sb)


def _universe() -> UniverseRepository:
    return UniverseRepository(_db())


# ticker → security_id 기억 시간. 한 실행 안에서 같은 종목을 가격·배당·분할마다 다시 풀면 종목당 왕복이
# 두세 번 늘어난다. 신원 교체(상장 전환)는 드물고 하루 단위라, 짧게만 기억해 교체 뒤 오래 틀리지 않게 한다.
_ID_CACHE_SECONDS = 600.0
_id_cache: dict[str, tuple[int, float]] = {}
_id_cache_lock = threading.Lock()


def _ids(tickers: list[str]) -> dict[str, int]:
    """못 찾은 종목은 기억하지 않는다 — 곧 적재될 종목이 계속 없는 것으로 남지 않게.

    `configure`로 다른 DB를 주입한 경우(테스트·검증 도구)는 기억하지 않는다. 기억은 DB마다 다르다.
    """
    if _database is not None:
        return _universe().security_ids(tickers)
    now = time.monotonic()
    wanted = [str(ticker).upper() for ticker in tickers]
    found: dict[str, int] = {}
    with _id_cache_lock:
        for ticker in wanted:
            cached = _id_cache.get(ticker)
            if cached is not None and cached[1] > now:
                found[ticker] = cached[0]
    missing = sorted({ticker for ticker in wanted if ticker not in found})
    if missing:
        fetched = _universe().security_ids(missing)
        with _id_cache_lock:
            for ticker, security_id in fetched.items():
                _id_cache[str(ticker).upper()] = (int(security_id), now + _ID_CACHE_SECONDS)
        found.update({str(ticker).upper(): int(security_id) for ticker, security_id in fetched.items()})
    return found


def clear_id_cache() -> None:
    with _id_cache_lock:
        _id_cache.clear()


def universe_company_tickers() -> list[str]:
    return _universe().tracked_tickers()


def universe_tracked() -> list[str]:
    return sorted(set(universe_company_tickers()) | set(REFERENCE_PRICE_TICKERS))


def price_targets() -> list[PriceTarget]:
    """수집 계획: 게이트가 켜진 종목 + 참조 ETF. 참조 ETF는 상장·신원 확인된 종목만 쓴다."""
    universe = _universe()
    targets = {s.security_id: PriceTarget(s.security_id, s.ticker) for s in universe.tracked_securities()}
    reference = universe.securities_by_ticker(list(REFERENCE_PRICE_TICKERS))
    missing = sorted(set(REFERENCE_PRICE_TICKERS) - set(reference))
    if missing:
        raise RuntimeError(f"reference price securities are missing from universe: {missing}")
    for security in reference.values():
        if security.is_active_listing and security.is_identity_verified:
            targets.setdefault(security.security_id, PriceTarget(security.security_id, security.ticker))
    return sorted(targets.values(), key=lambda target: target.symbol)


def missing_price_targets() -> list[PriceTarget]:
    """가격이 한 행도 없는 수집 대상."""
    targets = price_targets()
    present = MarketRepository(_db()).security_ids_with_prices([t.security_id for t in targets])
    return [target for target in targets if target.security_id not in present]


def targets_for_tickers(tickers: Sequence[str]) -> list[PriceTarget]:
    """명시한 ticker를 지금 상장·신원 확인된 종목의 계획으로 만든다. 모르는 ticker는 실패다."""
    found = _universe().securities_by_ticker(list(tickers))
    usable = {t: s for t, s in found.items() if s.is_active_listing and s.is_identity_verified}
    unknown = sorted({str(t).upper() for t in tickers} - set(usable))
    if unknown:
        raise ValueError(f"tickers are not active verified securities: {unknown}")
    return sorted((PriceTarget(s.security_id, s.ticker) for s in usable.values()), key=lambda t: t.symbol)


def universe_missing_prices() -> list[str]:
    return [target.symbol for target in missing_price_targets()]


def latest_price_date() -> str | None:
    result = MarketRepository(_db()).latest_price_date()
    return result.isoformat() if result else None


def prices_since(since: str) -> dict[tuple[int, str], dict]:
    """(security_id, 거래일) → 저장된 가격. 증분 수집이 바뀐 행만 고를 때 쓴다."""
    rows = MarketRepository(_db()).prices_since(date.fromisoformat(since))
    return {
        (int(row["security_id"]), str(row["trade_date"])): {
            key: row.get(key) for key in ("security_id", "trade_date", "open", "high", "low", "close", "volume", "is_repaired")
        }
        for row in rows
    }


def upsert_prices(rows: list[dict]) -> int:
    """계획의 security_id가 붙은 가격 행을 저장한다. security_id 없는 행은 거절한다."""
    if not rows:
        return 0
    if any(row.get("security_id") is None for row in rows):
        raise ValueError("price rows must carry the planned security_id")
    return MarketRepository(_db()).upsert_bars(DailyBar.from_row(row) for row in rows)


def merge_actions(rows: list[dict]) -> int:
    return MarketRepository(_db()).merge_actions(rows) if rows else 0


def split_keys(security_ids: Sequence[int]) -> set[tuple[int, str]]:
    """이미 저장된 분할 (security_id, 날짜). 새 분할만 전체 이력 재수집을 부른다."""
    if not security_ids:
        return set()
    return {
        (event.security_id, event.action_date.isoformat())
        for event in MarketRepository(_db()).splits(list(security_ids))
    }


def bars_for_securities(security_ids: Sequence[int], *, start: date, end: date) -> list[dict]:
    """security_id 목록의 구간 봉. 로컬 사본 동기화가 쓴다."""
    if not security_ids:
        return []
    return [bar.as_row() for bar in MarketRepository(_db()).bars(list(security_ids), start=start, end=end)]


def actions_for_securities(security_ids: Sequence[int]) -> list[dict]:
    """security_id 목록의 전체 배당·분할을 (종목, 날짜) 한 행으로. 로컬 사본 동기화가 쓴다."""
    if not security_ids:
        return []
    repo = MarketRepository(_db())
    merged: dict[tuple[int, str], dict] = {}
    for event in repo.dividends(list(security_ids)):
        key = (event.security_id, event.ex_date.isoformat())
        merged.setdefault(key, {"security_id": key[0], "action_date": key[1], "split_ratio": None,
                                "dividend_amount": None})["dividend_amount"] = event.div_amount
    for event in repo.splits(list(security_ids)):
        key = (event.security_id, event.action_date.isoformat())
        merged.setdefault(key, {"security_id": key[0], "action_date": key[1], "split_ratio": None,
                                "dividend_amount": None})["split_ratio"] = event.split_ratio
    return [merged[key] for key in sorted(merged)]


def split_history(ticker: str) -> list[dict]:
    """종목의 전체 분할 이력. 저장 종가가 따르는 분할 기준을 되짚을 때 쓴다."""
    security_id = _ticker_id(ticker)
    if security_id is None:
        return []
    return [
        {"ticker": ticker.upper(), "action_date": event.action_date.isoformat(), "split_ratio": event.split_ratio}
        for event in MarketRepository(_db()).splits([security_id])
    ]


def _ticker_id(ticker: str) -> int | None:
    return _ids([ticker]).get(str(ticker).upper())


def _price_rows(ticker: str, *, start: date, end: date, known_at: datetime | None = None,
                security_id: int | None = None) -> list[dict]:
    security_id = security_id if security_id is not None else _ticker_id(ticker)
    if security_id is None:
        return []
    bars = MarketRepository(_db()).bars([security_id], start=start, end=end, known_at=known_at)
    return [
        {"ticker": ticker.upper(), **bar.as_row(), "trade_date": bar.trade_date.isoformat()}
        for bar in bars
    ]


_EARLIEST_BAR = date(1900, 1, 1)


def _history_window_start(end: date, limit: int) -> date:
    """`limit` 거래일을 넉넉히 덮는 달력 시작일. 거래일은 주 5일, 휴장은 연 10일 안팎이다."""
    return end - timedelta(days=int(limit * 1.5) + 30)


def price_history_as_of(ticker: str, as_of_at: datetime, *, limit: int = 260) -> list[dict]:
    """판단 시점까지의 마지막 `limit`개 봉과 그 구간의 배당·분할.

    전체 이력을 읽고 뒤를 자르는 대신 창만 읽는다. 창 안의 봉이 `limit`보다 적으면(상장이 짧거나 긴 거래정지)
    전체 이력으로 다시 읽어, 결과는 전체를 읽고 자른 것과 항상 같다.
    """
    if as_of_at.tzinfo is None:
        raise ValueError("as_of_at must include timezone")
    security_id = _ticker_id(ticker)
    if security_id is None:
        return []
    end = as_of_at.date()
    rows = _price_rows(ticker, start=_history_window_start(end, limit), end=end, known_at=as_of_at,
                       security_id=security_id)
    if len(rows) < limit:
        rows = _price_rows(ticker, start=_EARLIEST_BAR, end=end, known_at=as_of_at, security_id=security_id)
    rows = rows[-limit:]
    if not rows:
        return []
    first = date.fromisoformat(str(rows[0]["trade_date"]))
    last = date.fromisoformat(str(rows[-1]["trade_date"]))
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


def closes_on_date(tickers: Sequence[str], trade_date: date) -> dict[str, float]:
    """한 거래일의 여러 종목 종가. 과거 시점들의 횡단면 수익률을 잴 때 창 전체를 읽지 않으려고 둔다."""
    ids = _ids(sorted({str(value).upper() for value in tickers}))
    if not ids:
        return {}
    ticker_by_id = {int(security_id): ticker for ticker, security_id in ids.items()}
    closes = MarketRepository(_db()).closes_on(trade_date, sorted(ticker_by_id))
    return {ticker_by_id[security_id]: close for security_id, close in closes.items() if security_id in ticker_by_id}


def trading_dates(reference_ticker: str, *, start: date, end: date) -> list[date]:
    """기준 종목(보통 SPY)에 봉이 있는 날을 거래일 달력으로 쓴다."""
    return [date.fromisoformat(str(row["trade_date"])) for row in _price_rows(reference_ticker, start=start, end=end)]


def forward_closes_after(ticker: str, *, after_date: str, limit: int = 40) -> list[dict]:
    rows = _price_rows(ticker, start=date.fromisoformat(after_date), end=us_market_today())
    return [
        {"ticker": ticker.upper(), "trade_date": row["trade_date"], "close": row["close"]}
        for row in rows
        if str(row["trade_date"]) > str(after_date)
    ][:limit]


def close_window_for_labels(tickers: Sequence[str], *, start: date, end: date) -> list[dict]:
    """연구 라벨 전용 미래 포함 종가 창. evidence 판단 경로에서는 사용하지 않는다."""
    ids = _ids(sorted({str(ticker).upper() for ticker in tickers}))
    if not ids:
        return []
    ticker_by_id = {int(security_id): ticker for ticker, security_id in ids.items()}
    bars = MarketRepository(_db()).bars(sorted(ticker_by_id), start=start, end=end)
    return sorted([
        {"ticker": ticker_by_id[int(bar.security_id)], "trade_date": bar.trade_date.isoformat(),
         "close": bar.close}
        for bar in bars if int(bar.security_id) in ticker_by_id and bar.close is not None
    ], key=lambda row: (row["ticker"], row["trade_date"]))


def price_path_from(ticker: str, start_date: date, *, limit: int = 80) -> list[dict]:
    rows = _price_rows(ticker, start=start_date, end=us_market_today())[:limit]
    if not rows:
        return []
    last = date.fromisoformat(str(rows[-1]["trade_date"]))
    security_id = _ticker_id(ticker)
    dividends = [event.as_row() for event in MarketRepository(_db()).dividends([security_id], since=start_date) if event.ex_date <= last]
    for row in dividends:
        row["ticker"] = ticker.upper()
        row["ex_date"] = str(row["ex_date"])
    splits = [event.as_row() for event in MarketRepository(_db()).splits([security_id], since=start_date) if event.action_date <= last]
    for row in splits:
        row["ticker"] = ticker.upper()
        row["action_date"] = str(row["action_date"])
    return merge_corporate_actions(rows, dividends, splits)


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
        start = us_market_today() - relativedelta(years=int(period[:-1]))
    else:
        raise ValueError(f"unsupported market monthly history period: {period}")
    ids = _ids(requested)
    missing = sorted(set(requested) - set(ids))
    if missing:
        raise RuntimeError(f"market has unknown strategy securities: {missing}")
    bars = MarketRepository(_db()).bars(list(ids.values()), start=start, end=us_market_today())
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
    "SCHEMA_MARKET", "SCHEMA_UNIVERSE", "T_ACTIONS_DAILY", "T_PRICES_DAILY", "configure",
    "universe_tracked", "universe_company_tickers", "universe_missing_prices", "price_targets",
    "missing_price_targets", "targets_for_tickers", "latest_price_date", "prices_since",
    "upsert_prices", "merge_actions", "split_keys", "split_history", "price_history_as_of",
    "closes_on_date", "trading_dates",
    "forward_closes_after", "price_path_from", "monthly_close_history",
]
