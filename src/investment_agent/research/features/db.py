"""기술지표의 v1 입력 조회와 Research 로컬 저장소 경계."""
from __future__ import annotations

import math
from datetime import datetime, timezone

import pandas as pd

from investment_agent.platform.logging import get_logger
from investment_agent.platform.db.postgres import sb, select_all_paged
from investment_agent.operations.runtime import utc_now_iso
from investment_agent.research.storage.repository import ResearchStore
from investment_agent.data.market.infrastructure.change_manifest import earliest_change_since as _manifest_change_since

from . import _UPSERT_BATCH

SCHEMA_MARKET = "market"
SCHEMA_UNIVERSE = "universe"
T_PRICES_DAILY = "prices_daily"
T_SECURITIES = "securities"
_VALUE_COLUMNS = ("rsi14", "macd", "macd_signal")
log = get_logger(__name__)


def _store() -> ResearchStore:
    """쓰기용. 배타 잠금을 잡으므로 실제로 적재하는 경로에서만 쓴다."""
    return ResearchStore()


def _read_store() -> ResearchStore:
    """조회용. 읽기 연결끼리는 서로를 막지 않는다."""
    return ResearchStore(read_only=True)


def _latest_date(schema: str, table: str, column: str) -> str | None:
    rows = (
        sb.schema(schema).table(table).select(column).order(column, desc=True)
        .limit(1).execute().data or []
    )
    return str(rows[0][column]) if rows else None


def latest_market_date() -> str | None:
    return _latest_date(SCHEMA_MARKET, T_PRICES_DAILY, "trade_date")


def latest_indicator_date() -> str | None:
    return _read_store().latest_feature_date()


def latest_indicator_write_at() -> str | None:
    return _read_store().latest_feature_write_at()


def earliest_market_change_since(since: str, *, after_ingested_at: str | None) -> str | None:
    return _manifest_change_since(since, after_recorded_at=after_ingested_at)


def load_market_prices_since(since: str) -> list[dict]:
    """v1 market 봉을 현재 ticker 표기로 투영해 끝까지 읽는다."""
    securities = select_all_paged(
        lambda: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES).select("security_id,ticker"),
        order_by="security_id",
    )
    ticker_by_security = {
        int(row["security_id"]): str(row["ticker"])
        for row in securities if row.get("ticker")
    }
    price_rows = select_all_paged(
        lambda: sb.schema(SCHEMA_MARKET).table(T_PRICES_DAILY)
        .select("security_id,trade_date,close").gte("trade_date", since),
        order_by="security_id,trade_date",
    )
    missing = sorted({int(row["security_id"]) for row in price_rows} - set(ticker_by_security))
    if missing:
        raise RuntimeError(
            "market price rows reference securities without a universe ticker: "
            + ", ".join(map(str, missing[:10]))
        )
    return [
        {"ticker": ticker_by_security[int(row["security_id"])],
         "trade_date": str(row["trade_date"]), "close": row["close"]}
        for row in price_rows
    ]


def existing_indicators_since(since: str) -> dict[tuple[str, str], dict[str, float | None]]:
    rows = _read_store().features_since(since)
    return {
        (str(row["ticker"]), str(row["trade_date"])): {
            column: float(row[column]) if row.get(column) is not None else None
            for column in _VALUE_COLUMNS
        } for row in rows
    }


def features_for_ticker(ticker: str, *, limit: int = 520) -> list[dict]:
    """Research 로컬 feature 행을 읽는다. production schema에는 접근하지 않는다."""
    return _read_store().features_for_ticker(str(ticker).upper(), limit=limit)


def features_since(since: str) -> list[dict]:
    """한 창의 feature를 종목 구분 없이 한 번에 읽는다.

    종목마다 부르면 연결이 종목 수만큼 열린다 — 후보 선정이 실제로 463번 열었다.
    """
    return _read_store().features_since(since)


def changed_indicators(df: pd.DataFrame, existing: dict[tuple[str, str], dict[str, float | None]]) -> pd.DataFrame:
    if df.empty:
        return df
    keep: list[bool] = []
    for row in df.itertuples(index=False):
        trade_date = pd.Timestamp(row.trade_date).date().isoformat()
        current = existing.get((str(row.ticker), trade_date))
        changed = current is None
        if current is not None:
            for column in _VALUE_COLUMNS:
                candidate = getattr(row, column)
                candidate_value = None if pd.isna(candidate) else float(candidate)
                stored_value = current[column]
                if candidate_value is None or stored_value is None:
                    if candidate_value is not stored_value:
                        changed = True
                        break
                elif not math.isclose(candidate_value, stored_value, rel_tol=1e-10, abs_tol=1e-10):
                    changed = True
                    break
        keep.append(changed)
    return df.loc[keep].copy()


def upsert_indicators(df: pd.DataFrame) -> int:
    """기술지표를 Research 로컬 DuckDB에 멱등적으로 기록한다."""
    if df.empty:
        log.info("no indicator rows — skip upsert")
        return 0
    out = df.copy()
    out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.strftime("%Y-%m-%d")
    if out.duplicated(["ticker", "trade_date"]).any():
        raise ValueError("duplicate indicator keys in one upsert")
    values = out[list(_VALUE_COLUMNS)].astype("float64")
    if not values.map(math.isfinite).all().all():
        raise ValueError("non-finite indicator value in one upsert")
    if not out["rsi14"].between(0, 100).all():
        raise ValueError("RSI outside [0, 100] in one upsert")
    out = out.astype(object).where(pd.notna(out), None)
    records = out[["ticker", "trade_date", *_VALUE_COLUMNS]].to_dict("records")
    ingested_at = utc_now_iso()
    affected = 0
    for start in range(0, len(records), _UPSERT_BATCH):
        affected += _store().upsert_features(
            records[start:start + _UPSERT_BATCH], ingested_at=ingested_at
        )
    log.info("indicator upsert received=%d affected=%d", len(records), affected)
    return affected


def delete_before(cutoff: str) -> int:
    return _store().delete_features_before(cutoff)


def latest_signal_as_of(ticker: str, as_of_at: datetime) -> list[dict]:
    """as_of 시점에 확정돼 있던 최신 로컬 기술지표 한 행."""
    if as_of_at.tzinfo is None:
        raise ValueError("as_of_at must include timezone")
    return _read_store().latest_feature_as_of(
        ticker, trade_date=as_of_at.date(), as_of_at=as_of_at.astimezone(timezone.utc)
    )


__all__ = [
    "SCHEMA_MARKET", "SCHEMA_UNIVERSE", "T_PRICES_DAILY", "T_SECURITIES",
    "changed_indicators", "delete_before", "earliest_market_change_since",
    "existing_indicators_since", "latest_indicator_date", "latest_indicator_write_at",
    "features_for_ticker", "features_since",
    "latest_market_date", "latest_signal_as_of", "load_market_prices_since",
    "upsert_indicators",
]
