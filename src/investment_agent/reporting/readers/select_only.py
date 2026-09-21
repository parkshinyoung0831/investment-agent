"""화면과 알림이 쓰는 Supabase SELECT 전용 gateway와 공통 조회 helper.

SELECT 계열만 조합하고 쓰기·RPC 경로가 코드에 없다. 조회 로더는 이 gateway로만 저장소를 연다.
"""
from __future__ import annotations

import os
import re
from collections.abc import Iterator, Mapping, Sequence
from itertools import product
from datetime import date, datetime, timezone
from typing import Any
from investment_agent.platform.logging import get_logger
from investment_agent.reporting.models import DataResult, normalize_observed_at

log = get_logger(__name__)

DB_SOURCE = "DB 저장 데이터 · v1 Supabase"


_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


SCHEMA_UNIVERSE = "universe"


T_SECURITIES = "securities"


def membership_chunks(
    filters: Mapping[str, Sequence[Any]],
) -> Iterator[dict[str, Sequence[Any]]]:
    """`in` 목록을 URL 한도 안에 들어가는 조각들의 조합으로 나눈다.

    조각 크기는 platform이 정한 것 하나를 쓴다 — 여기서 따로 정하면 두 경계가
    서로 다른 한도를 주장하게 된다.
    """
    from investment_agent.platform.db.postgres import IN_FILTER_CHUNK

    columns = list(filters)
    pieces = [
        [tuple(values[at:at + IN_FILTER_CHUNK]) for at in range(0, len(values), IN_FILTER_CHUNK)]
        for values in (filters[column] for column in columns)
    ]
    for combination in product(*pieces) if columns else [()]:
        yield dict(zip(columns, combination))


def security_identity(gateway: Any, tickers: Sequence[str]) -> tuple[dict[str, dict], dict[str, dict]]:
    """화면의 ticker를 canonical security_id/CIK로 해석한다."""
    wanted = sorted({str(ticker).upper() for ticker in tickers if str(ticker).strip()})
    if not wanted:
        return {}, {}
    rows = gateway.select_rows(
        schema=SCHEMA_UNIVERSE,
        table=T_SECURITIES,
        columns="security_id,ticker,cik,is_active_listing",
        in_values={"ticker": wanted},
        # 같은 ticker를 옛 종목과 지금 종목이 함께 가질 수 있다 — 상장 중인 행이 마지막에 와 이긴다.
        order=(("ticker", False), ("is_active_listing", False), ("security_id", False)),
        page_size=1_000,
        max_rows=2_000,
    )
    by_ticker = {str(row["ticker"]).upper(): row for row in rows}
    by_cik = {
        str(row["cik"]).zfill(10): row
        for row in rows if row.get("cik")
    }
    # `by_cik`는 회사당 한 행이다 — 같은 CIK의 종목(GOOG/GOOGL 등)을 함께 넘기면 하나가 조용히 사라진다.
    # 호출자는 회사당 대표 종목 하나만 넘긴다는 계약이라(`watchlist_members`), 어기면 드러낸다.
    tickers_by_cik: dict[str, set[str]] = {}
    for row in rows:
        if row.get("cik"):
            tickers_by_cik.setdefault(str(row["cik"]).zfill(10), set()).add(str(row["ticker"]).upper())
    shared = {cik: sorted(names) for cik, names in tickers_by_cik.items() if len(names) > 1}
    if shared:
        log.warning("security_identity: 같은 CIK에 종목이 둘 이상이라 by_cik에는 하나만 남는다: %s", shared)
    return by_ticker, by_cik


class DashboardDataError(RuntimeError):
    """읽기 결과의 구조가 계약과 다를 때 사용하는 안전한 오류."""


class SelectOnlyGateway:
    """허용된 PostgREST SELECT 연산만 조합하는 좁은 게이트웨이.

    v1 관심 기업은 공개 읽기 전용인 ``universe.entities``의 관심 컬럼에서
    직접 읽는다.
    """

    #: 이름 -> 허용된 인자 이름. SQL 정의가 STABLE이고 본문이 SELECT 하나인 함수만 둔다.

    def __init__(self, client: Any) -> None:
        from investment_agent.platform.db.postgres import SchemaClients

        self._client = client
        self._schemas = SchemaClients(client)

    @staticmethod
    def _identifier(value: str) -> str:
        current = str(value).strip()
        if not _IDENTIFIER_RE.fullmatch(current):
            raise DashboardDataError("허용되지 않은 DB 식별자입니다.")
        return current

    @classmethod
    def _columns(cls, value: str) -> str:
        columns = [item.strip() for item in str(value).split(",") if item.strip()]
        if not columns or any(not _IDENTIFIER_RE.fullmatch(item) for item in columns):
            raise DashboardDataError("명시적이고 단순한 SELECT 컬럼만 허용합니다.")
        return ",".join(columns)

    @staticmethod
    def _response_rows(response: Any) -> list[dict[str, Any]]:
        data = getattr(response, "data", None)
        if data is None:
            return []
        if not isinstance(data, list) or any(not isinstance(row, Mapping) for row in data):
            raise DashboardDataError("Supabase SELECT 응답이 행 배열이 아닙니다.")
        return [dict(row) for row in data]

    def select_rows(
        self,
        *,
        schema: str,
        table: str,
        columns: str,
        equal: Mapping[str, Any] | None = None,
        in_values: Mapping[str, Sequence[Any]] | None = None,
        order: Sequence[tuple[str, bool]] = (),
        limit: int | None = None,
        page_size: int | None = None,
        max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        """SELECT와 허용된 필터·정렬·범위만 사용해 행을 읽는다."""

        schema_name = self._identifier(schema)
        table_name = self._identifier(table)
        selected_columns = self._columns(columns)
        equal_filters = {
            self._identifier(column): value for column, value in (equal or {}).items()
        }
        membership_filters = {
            self._identifier(column): tuple(values)
            for column, values in (in_values or {}).items()
        }
        order_fields = tuple((self._identifier(column), bool(desc)) for column, desc in order)

        if any(not values for values in membership_filters.values()):
            return []
        if limit is not None and not 1 <= int(limit) <= 20_000:
            raise DashboardDataError("SELECT limit 범위를 벗어났습니다.")
        if page_size is not None:
            if not 1 <= int(page_size) <= 1_000:
                raise DashboardDataError("SELECT page_size 범위를 벗어났습니다.")
            if not order_fields:
                raise DashboardDataError("페이지 조회에는 안정적인 정렬 컬럼이 필요합니다.")
        if max_rows is not None and not 1 <= int(max_rows) <= 200_000:
            raise DashboardDataError("SELECT max_rows 범위를 벗어났습니다.")

        def build(subsets: Mapping[str, Sequence[Any]]) -> Any:
            query = self._schemas.get(schema_name).table(table_name).select(selected_columns)
            for column, value in equal_filters.items():
                query = query.eq(column, value)
            for column, values in subsets.items():
                query = query.in_(column, list(values))
            for column, descending in order_fields:
                query = query.order(column, desc=descending)
            return query

        def read(subsets: Mapping[str, Sequence[Any]], ceiling: int) -> list[dict[str, Any]]:
            if page_size is None:
                query = build(subsets)
                if limit is not None:
                    query = query.limit(int(limit))
                return self._response_rows(query.execute())
            rows: list[dict[str, Any]] = []
            start = 0
            batch_size = int(page_size)
            while start < ceiling:
                end = min(start + batch_size, ceiling) - 1
                chunk = self._response_rows(build(subsets).range(start, end).execute())
                rows.extend(chunk)
                if len(chunk) < end - start + 1:
                    break
                start = end + 1
            else:
                # 마지막 페이지까지 가득 차서 상한에 닿았다 — 더 있었을 수 있는데 호출자는 잘린 줄 모른다.
                log.warning("select_rows reached its row ceiling: %s.%s ceiling=%d", schema_name, table_name, ceiling)
            return rows[:ceiling]

        ceiling = int(max_rows or limit or 20_000)
        splits = list(membership_chunks(membership_filters))
        if len(splits) == 1:
            return read(splits[0], ceiling)

        # `in` 값은 URL에 그대로 실린다. 행 상한과 다른 벽이라 페이지네이션으로는
        # 풀리지 않고, 넘기면 PostgREST가 400을 준다 — 대시보드에서는 "실적 DB
        # 조회 실패" 한 줄로만 보인다. 한 행은 각 컬럼에서 정확히 한 조각에만
        # 속하므로 조각을 합쳐도 중복이 생기지 않는다.
        merged: list[dict[str, Any]] = []
        for subsets in splits:
            merged.extend(read(subsets, ceiling))
        for column, descending in reversed(order_fields):
            merged.sort(key=lambda row, c=column: (row.get(c) is None, row.get(c)), reverse=descending)
        return merged[:ceiling]


def offline_mode() -> bool:
    return os.environ.get("DASHBOARD_OFFLINE", "").strip().lower() in _TRUE_VALUES


def configured() -> bool:
    return bool(
        os.environ.get("SUPABASE_URL", "").strip()
        and os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    )


def open_gateway() -> SelectOnlyGateway:
    from investment_agent.platform.db.postgres import service_client

    return SelectOnlyGateway(service_client())


def preflight() -> DataResult | None:
    if offline_mode():
        return DataResult.offline(source=DB_SOURCE)
    if not configured():
        return DataResult.unconfigured(
            source=DB_SOURCE,
            message="SUPABASE_URL 또는 SUPABASE_SERVICE_KEY가 설정되지 않았습니다.",
        )
    return None


def as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        current = value
        return current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        current = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current
    except ValueError:
        try:
            current_date = date.fromisoformat(text)
        except ValueError:
            return None
        return datetime(current_date.year, current_date.month, current_date.day, tzinfo=timezone.utc)


def latest_at(groups: Sequence[tuple[Sequence[Mapping[str, Any]], Sequence[str]]]) -> str | None:
    candidates: list[datetime] = []
    for rows, fields in groups:
        for row in rows:
            for field in fields:
                parsed = as_datetime(row.get(field))
                if parsed is not None:
                    candidates.append(parsed.astimezone(timezone.utc))
                    break
    return normalize_observed_at(max(candidates)) if candidates else None
