"""market 스키마를 읽고 쓰는 유일한 자리.

## 시장 가격의 PIT 경계

일별 종가는 거래일 종료 뒤 공개된 사실이다. 로컬 적재 시각은 그 사실의 공개 시각이
아니므로, historical reader는 `trade_date`만 경계로 사용한다. 공급자 정정과 backfill은
Parquet 배치 manifest가 feature 재계산 범위를 결정한다.

## ticker가 아니라 security_id로 저장한다

ticker는 바뀌고 재사용된다. 개명 한 번에 같은 회사의 과거와 현재가 갈라지면 그 시계열은
어떤 계산에도 못 쓴다. ticker↔security_id 변환은 universe가 한다.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Any

from investment_agent.data.market.domain.models import DailyBar, DividendEvent, SplitEvent
from investment_agent.data.market.infrastructure.change_manifest import record_change_dates
from investment_agent.platform.db.postgres import Database
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

SCHEMA = "market"

T_PRICES = "prices_daily"
T_SPLITS = "split_events"
T_DIVIDENDS = "dividend_events"

_PRICE_COLUMNS = "security_id, trade_date, open, high, low, close, volume, is_repaired"


class MarketRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ── 읽기 ──────────────────────────────────────────────────────────────
    def bars(
        self,
        security_ids: Sequence[int],
        *,
        start: date,
        end: date,
        known_at: datetime | None = None,
    ) -> list[DailyBar]:
        """구간 봉.

        ``known_at``은 API 호환성을 위해 받지만 시장 가격에는 적용하지 않는다. 일별
        가격의 공개 가능성은 거래 세션으로 결정되며, 수집 시각으로 과거 가격을 숨기면
        늦은 backfill이 역사적 사실을 지워 버린다.
        """
        def configure(query: Any) -> Any:
            query = query.gte("trade_date", start.isoformat()).lte("trade_date", end.isoformat())
            return query

        rows = self._db.select_in_chunks(
            schema=SCHEMA,
            table=T_PRICES,
            columns=_PRICE_COLUMNS,
            filter_column="security_id",
            values=[str(value) for value in security_ids],
            configure=configure,
            # 종목×날짜라 금방 1,000행을 넘는다. 정렬 없이 페이지를 넘기면 봉이 빠진다.
            order_by="security_id, trade_date",
        )
        return [DailyBar.from_row(row) for row in rows]

    def closes_on(self, trade_date: date, security_ids: Sequence[int]) -> dict[int, float]:
        """그날 종가만. 횡단면 조회의 주 경로다."""
        rows = self._db.select_in_chunks(
            schema=SCHEMA,
            table=T_PRICES,
            columns="security_id, close",
            filter_column="security_id",
            values=[str(value) for value in security_ids],
            configure=lambda query: query.eq("trade_date", trade_date.isoformat()),
            order_by="security_id",
        )
        return {int(row["security_id"]): float(row["close"]) for row in rows}

    def latest_trade_date(self, security_id: int) -> date | None:
        """이 종목의 마지막 적재일. 증분 수집이 어디서부터 볼지 정할 때 쓴다."""
        rows = (
            self._db.table(SCHEMA, T_PRICES)
            .select("trade_date")
            .eq("security_id", security_id)
            .order("trade_date", desc=True)
            .limit(1)
            .execute()
            .data
        )
        from investment_agent.platform.clock import as_date

        return as_date(rows[0]["trade_date"]) if rows else None

    def splits(self, security_ids: Sequence[int], *, since: date | None = None) -> list[SplitEvent]:
        rows = self._db.select_in_chunks(
            schema=SCHEMA,
            table=T_SPLITS,
            columns="security_id, action_date, split_ratio",
            filter_column="security_id",
            values=[str(value) for value in security_ids],
            configure=(lambda query: query.gte("action_date", since.isoformat()))
            if since is not None else None,
            order_by="security_id, action_date",
        )
        return [SplitEvent.from_row(row) for row in rows]

    def dividends(
        self, security_ids: Sequence[int], *, since: date | None = None
    ) -> list[DividendEvent]:
        rows = self._db.select_in_chunks(
            schema=SCHEMA,
            table=T_DIVIDENDS,
            columns="security_id, ex_date, div_amount",
            filter_column="security_id",
            values=[str(value) for value in security_ids],
            configure=(lambda query: query.gte("ex_date", since.isoformat()))
            if since is not None else None,
            order_by="security_id, ex_date",
        )
        return [DividendEvent.from_row(row) for row in rows]

    # ── 쓰기 ──────────────────────────────────────────────────────────────
    def upsert_bars(self, bars: Iterable[DailyBar]) -> int:
        """일별 사실을 canonical 가격 표에 upsert한다."""
        rows = [bar.as_row() for bar in bars]
        written = self._db.upsert(
            schema=SCHEMA, table=T_PRICES, rows=rows, on_conflict="security_id,trade_date"
        )
        record_change_dates([str(row["trade_date"]) for row in rows])
        return written

    def upsert_splits(self, events: Iterable[SplitEvent]) -> int:
        return self._db.upsert(
            schema=SCHEMA,
            table=T_SPLITS,
            rows=[event.as_row() for event in events],
            on_conflict="security_id,action_date",
        )

    def upsert_dividends(self, events: Iterable[DividendEvent]) -> int:
        return self._db.upsert(
            schema=SCHEMA,
            table=T_DIVIDENDS,
            rows=[event.as_row() for event in events],
            on_conflict="security_id,ex_date",
        )

    # ── 전체 조회 ─────────────────────────────────────────────────────────
    def latest_price_date(self) -> date | None:
        """전체 market에서 가장 최근 거래일. 수집 잡의 진행 상태 로그용이다."""
        rows = (
            self._db.table(SCHEMA, T_PRICES).select("trade_date")
            .order("trade_date", desc=True).limit(1).execute().data or []
        )
        from investment_agent.platform.clock import as_date

        return as_date(rows[0]["trade_date"]) if rows else None

    def prices_since(self, since: date) -> list[dict[str, Any]]:
        """전체 종목의 특정 날짜 이후 시세 원시 행.

        `DailyBar.from_row()` 검증을 거치지 않는다 — 일별 수집이 기존 값과
        비교만 하는 자리라, 검증 실패로 그 비교 자체가 죽으면 안 된다.
        """
        return self._db.select_paged(
            lambda: self._db.table(SCHEMA, T_PRICES).select(_PRICE_COLUMNS)
            .gte("trade_date", since.isoformat()),
            order_by="security_id, trade_date",
        )

    def security_ids_with_prices(self, security_ids: Sequence[int]) -> set[int]:
        """주어진 종목 중 가격이 하나라도 있는 종목의 identity."""
        wanted = sorted({int(value) for value in security_ids})
        if not wanted:
            return set()
        rows = self._db.select_in_chunks(
            schema=SCHEMA,
            table=T_PRICES,
            columns="security_id",
            filter_column="security_id",
            values=wanted,
            order_by="security_id",
        )
        return {int(row["security_id"]) for row in rows}


__all__ = ["MarketRepository", "SCHEMA", "T_DIVIDENDS", "T_PRICES", "T_SPLITS"]
