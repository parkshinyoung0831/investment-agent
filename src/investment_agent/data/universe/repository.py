"""universe 스키마를 읽고 쓰는 유일한 자리.

## 왜 저장소 접근을 한 곳에 모으는가

쿼리가 여기저기 흩어지면 스키마를 바꿀 때 고쳐야 할 자리를 찾을 수 없고, 그중
하나를 놓치면 그 경로만 조용히 빈 결과를 준다. 실제로 컬럼을 옮긴 뒤 한 화면만
빈 표를 그리던 적이 있다.

## 표·컬럼 이름은 상수로 둔다

문자열 리터럴을 흩뿌리면 오타가 `PGRST205`(없는 표)로 런타임에야 드러난다. 상수로
모으면 잘못된 이름이 한 자리에만 있고, 스키마를 바꿀 때 무엇을 고쳐야 하는지가
파일 위쪽만 봐도 보인다.

## ticker로 묻고 security_id로 답한다

밖에서 들어오는 이름은 여전히 ticker다(사람이 쓰는 이름이므로). 하지만 다른
스키마에 넘기는 것은 `security_id`다 — ticker는 바뀌고 재사용되므로 저장된 관계의
기준이 될 수 없다.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

from investment_agent.data.universe.domain.identifiers import normalize_ticker
from investment_agent.data.universe.domain.models import (
    Entity,
    MembershipSnapshot,
    Security,
    WatchlistMember,
)
from investment_agent.platform.db.postgres import Database
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

SCHEMA = "universe"

T_ENTITIES = "entities"
T_SECURITIES = "securities"
T_IDENTIFIERS = "security_identifiers"
T_MEMBERSHIPS = "index_memberships"
RPC_REPLACE_MEMBERSHIP = "replace_index_membership"

# 지수 코드. 저장소 CHECK가 SP500의 정원 범위를 따로 갖고 있다.
INDEX_SP500 = "SP500"

_SECURITY_COLUMNS = (
    "security_id, ticker, cik, exchange_code, security_type, security_title, is_active_listing, is_tracked"
)


class UniverseRepository:
    """universe 스키마 접근. 진입점이 `Database`를 만들어 넘긴다."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── 게이트 ────────────────────────────────────────────────────────────
    def tracked_securities(self) -> list[Security]:
        """수집·판단 대상. 다른 파이프라인은 전부 이 목록에서 시작한다."""
        rows = self._db.select_paged(
            lambda: self._db.table(SCHEMA, T_SECURITIES)
            .select(_SECURITY_COLUMNS)
            .eq("is_tracked", True),
            # 500건이 넘을 수 있고, 정렬 없이 페이지를 넘기면 종목이 조용히 빠진다.
            order_by="ticker",
        )
        return [Security.from_row(row) for row in rows]

    def tracked_tickers(self) -> list[str]:
        return [security.ticker for security in self.tracked_securities()]

    def securities_by_ticker(self, tickers: Sequence[str]) -> dict[str, Security]:
        """ticker → Security. 없는 ticker는 결과에 없다 — 빈 껍데기를 만들지 않는다."""
        wanted = [t for t in (normalize_ticker(v) for v in tickers) if t]
        if not wanted:
            return {}
        rows = self._db.select_in_chunks(
            schema=SCHEMA,
            table=T_SECURITIES,
            columns=_SECURITY_COLUMNS,
            filter_column="ticker",
            values=wanted,
            order_by="ticker",
        )
        return {row["ticker"]: Security.from_row(row) for row in rows}

    def security_ids(self, tickers: Sequence[str]) -> dict[str, int]:
        """다른 스키마에 넘길 키. 못 찾은 것은 부르는 쪽이 보고 판단한다."""
        return {
            ticker: security.security_id
            for ticker, security in self.securities_by_ticker(tickers).items()
        }

    def all_securities(self) -> list[Security]:
        """추적 여부와 무관한 전체 증권. entity 후보 선정처럼 전체 집합이
        필요한 자리에서만 쓴다 — 일반 조회는 `tracked_securities()`를 쓴다."""
        rows = self._db.select_paged(
            lambda: self._db.table(SCHEMA, T_SECURITIES).select(_SECURITY_COLUMNS),
            order_by="ticker",
        )
        return [Security.from_row(row) for row in rows]

    def tickers_by_security_id(self, security_ids: Sequence[int]) -> dict[int, str]:
        """다른 스키마에서 받은 identity를 사람이 읽는 현재 ticker로 되돌린다."""
        wanted = sorted({int(value) for value in security_ids})
        if not wanted:
            return {}
        rows = self._db.select_in_chunks(
            schema=SCHEMA,
            table=T_SECURITIES,
            columns="security_id,ticker",
            filter_column="security_id",
            values=wanted,
            order_by="security_id",
        )
        return {int(row["security_id"]): str(row["ticker"]) for row in rows}

    # ── 식별자 ────────────────────────────────────────────────────────────
    def resolve_identifiers(
        self,
        identifiers: Sequence[str],
        identifier_type: str,
        *,
        on_date: date | None = None,
    ) -> dict[str, int]:
        """CUSIP·과거 ticker 같은 외부 식별자를 security_id로 옮긴다.

        `on_date`를 주면 그 시점에 유효했던 매핑만 본다. 시점 없이 매핑하면 재사용된
        ticker 때문에 **서로 다른 회사가 한 종목으로 합쳐진다** — 13F처럼 몇 년치를
        한꺼번에 읽는 자리에서 실제로 일어난다.
        """
        values = [str(v).strip().upper() for v in identifiers if str(v or "").strip()]
        if not values:
            return {}

        def configure(query: Any) -> Any:
            query = query.eq("identifier_type", identifier_type).not_.is_("security_id", "null")
            if on_date is not None:
                query = query.lte("valid_from", on_date.isoformat())
            return query

        rows = self._db.select_in_chunks(
            schema=SCHEMA,
            table=T_IDENTIFIERS,
            columns="identifier, security_id, valid_from, valid_to",
            filter_column="identifier",
            values=values,
            configure=configure,
            order_by="identifier",
        )
        resolved: dict[str, int] = {}
        for row in rows:
            # valid_to는 PostgREST에서 `gte` 필터와 NULL을 함께 걸 수 없어 여기서 판정한다.
            if on_date is not None and row.get("valid_to"):
                if str(row["valid_to"]) <= on_date.isoformat():
                    continue
            resolved[row["identifier"]] = int(row["security_id"])
        return resolved

    # ── 지수 membership ───────────────────────────────────────────────────
    def membership_on(
        self, effective_date: date, *, index_code: str = INDEX_SP500
    ) -> MembershipSnapshot | None:
        """그날(또는 그 이전 마지막) 구성 종목.

        정확히 그날 스냅샷이 없을 수 있다(휴장·수집 실패). 그때 `None`을 주면 부르는
        쪽이 "그날은 지수가 비었다"로 읽으므로, **직전 스냅샷**을 준다. 언제 것인지는
        `effective_date`에 그대로 담겨 나간다.
        """
        rows = self._db.select_paged(
            lambda: self._db.table(SCHEMA, T_MEMBERSHIPS)
            .select("index_code,valid_from,valid_to,source,securities(ticker)")
            .eq("index_code", index_code).lte("valid_from", effective_date.isoformat()),
            order_by="valid_from,security_id",
        )
        active = [row for row in rows if not row.get("valid_to") or str(row["valid_to"]) > effective_date.isoformat()]
        if not active:
            return None
        return MembershipSnapshot.from_row({
            "index_code": index_code, "effective_date": max(str(row["valid_from"]) for row in active),
            "tickers": [((row.get(T_SECURITIES) or {}).get("ticker")) for row in active],
            "source": str(active[0].get("source") or ""),
        })

    def latest_membership(self, *, index_code: str = INDEX_SP500) -> MembershipSnapshot | None:
        rows = self._db.select_paged(
            lambda: self._db.table(SCHEMA, T_MEMBERSHIPS).select("valid_from,valid_to").eq("index_code", index_code),
            order_by="valid_from",
        )
        if not rows:
            return None
        boundary = max(date.fromisoformat(str(value)) for row in rows for value in (row["valid_from"], row.get("valid_to")) if value)
        return self.membership_on(boundary, index_code=index_code)

    # ── 관심 기업 ──────────────────────────────────────────────────────────
    def _representative_securities(self, ciks: Sequence[str]) -> dict[str, Security]:
        """관심 기업의 대표 종목. 한 CIK에 여러 클래스가 상장돼 있어도(GOOG/GOOGL)
        회사 하나에 카드 하나가 나가야 하므로 ticker 오름차순 첫 tracked 종목만 낸다.
        """
        wanted = sorted({str(cik) for cik in ciks if cik})
        if not wanted:
            return {}
        rows = self._db.select_in_chunks(
            schema=SCHEMA,
            table=T_SECURITIES,
            columns=_SECURITY_COLUMNS,
            filter_column="cik",
            values=wanted,
            # 대표를 뽑는 기준이 정렬이다. 정렬이 없으면 실행마다 대표가 바뀐다.
            order_by="ticker",
        )
        representatives: dict[str, Security] = {}
        for row in rows:
            security = Security.from_row(row)
            if security.is_tracked and security.cik:
                representatives.setdefault(str(security.cik), security)
        return representatives

    def watchlist_members(self, watchlist_name: str) -> list[WatchlistMember]:
        """활성 관심 기업. 비활성은 내지 않는다 — 부르는 쪽이 매번 거르게 두면
        한 곳에서 그것을 빠뜨린다."""
        if watchlist_name != "fundamentals":
            return []
        rows = self._db.select_paged(
            lambda: self._db.table(SCHEMA, T_ENTITIES)
            .select("cik, watchlist_sources, watch_from")
            .eq("is_watchlisted", True),
            order_by="cik",
        )
        representatives = self._representative_securities([row["cik"] for row in rows])
        members = []
        for row in rows:
            security = representatives.get(str(row["cik"]))
            # tracked 종목이 하나도 없는 회사는 보여줄 ticker가 없다. 빈 껍데기를
            # 만들지 않고 건너뛴다.
            if security is None:
                continue
            members.append(WatchlistMember.from_row({
                "cik": row["cik"],
                "ticker": security.ticker,
                "security_id": security.security_id,
                "sources": row.get("watchlist_sources"),
                "watch_from": row.get("watch_from"),
            }))
        return members

    def watchlist_member_rows(self, *, include_inactive: bool) -> list[dict[str, Any]]:
        """관심 기업 원시 행. CLI 조회·토스 동기화처럼 활성 여부를 직접 고르거나
        해제 이력까지 봐야 하는 자리에서 쓴다."""
        def factory() -> Any:
            query = self._db.table(SCHEMA, T_ENTITIES).select(
                "cik,watchlist_sources,watch_from,is_watchlisted,watchlist_removed_at"
            )
            return query if include_inactive else query.eq("is_watchlisted", True)

        rows = self._db.select_paged(factory, order_by="cik")
        if include_inactive:
            # 관심에서 빠진 적조차 없는 회사까지 내면 전 종목이 목록에 들어온다.
            rows = [
                row for row in rows
                if row.get("is_watchlisted") or row.get("watchlist_removed_at")
            ]
        representatives = self._representative_securities([row["cik"] for row in rows])
        out = []
        for row in rows:
            security = representatives.get(str(row["cik"]))
            if security is None:
                continue
            out.append({
                "cik": str(row["cik"]),
                "security_id": security.security_id,
                "ticker": security.ticker,
                "sources": list(row.get("watchlist_sources") or []),
                "is_active": bool(row.get("is_watchlisted")),
                "watch_from": row.get("watch_from"),
                "removed_at": row.get("watchlist_removed_at"),
            })
        return sorted(out, key=lambda item: item["ticker"])

    def watchlist_member_row(self, cik: str) -> dict[str, Any] | None:
        """관심 기업 원장의 원시 행 하나. 관심종목이었던 적이 없으면 `None`."""
        rows = self._db.select_paged(
            lambda: self._db.table(SCHEMA, T_ENTITIES)
            .select("cik,watchlist_sources,watch_from,is_watchlisted,watchlist_removed_at")
            .eq("cik", cik),
            order_by="cik",
        )
        if not rows:
            return None
        row = rows[0]
        if not row.get("is_watchlisted") and not row.get("watchlist_removed_at"):
            return None
        return {
            "cik": str(row["cik"]),
            "sources": list(row.get("watchlist_sources") or []),
            "is_active": bool(row.get("is_watchlisted")),
            "watch_from": row.get("watch_from"),
            "removed_at": row.get("watchlist_removed_at"),
        }

    # ── 쓰기 ──────────────────────────────────────────────────────────────
    def upsert_watchlist_member(
        self, *, cik: str, sources: list[str], watch_from: str, removed_at: str | None
    ) -> None:
        """CIK로 키를 잡아 발행사 행의 관심 상태를 갱신한다.

        관심은 회사에 대한 것이라 발행사 행의 상태다. 여기서 회사 사실(이름·SIC)을
        같이 보내면 SEC metadata 수집 결과를 덮어쓴다 — 관심 컬럼만 보낸다.

        그래서 **upsert가 아니라 UPDATE다.** Postgres는 `ON CONFLICT DO UPDATE`에서도
        후보 행의 NOT NULL을 먼저 검사하므로, `company_name`을 빼고 upsert하면
        기존 행이 있어도 `23502`로 거절당한다 — 즉 관심 기업 추가가 한 번도 성공할
        수 없었다. 발행사 행은 `securities.cik` FK가 이미 보장하므로 UPDATE로 족하다.
        """
        self._db.table(SCHEMA, T_ENTITIES).update({
            "watchlist_sources": sorted(set(sources)),
            "watch_from": watch_from,
            "watchlist_removed_at": removed_at,
        }).eq("cik", cik).execute()

    def upsert_entities(self, entities: Iterable[Entity]) -> int:
        rows = [
            {
                "cik": entity.cik,
                "company_name": entity.company_name,
                "company_name_ko": entity.company_name_ko,
                "sic_code": entity.sic_code,
                "sic_industry_name": entity.sic_industry_name,
                "sic_division_name": entity.sic_division_name,
                "fiscal_year_end": entity.fiscal_year_end,
                "entity_type": entity.entity_type,
                "state_of_incorporation": entity.state_of_incorporation,
                "former_names": list(entity.former_names),
            }
            for entity in entities
        ]
        return self._db.upsert(schema=SCHEMA, table=T_ENTITIES, rows=rows, on_conflict="cik")

    def upsert_securities(self, securities: Iterable[Security]) -> int:
        """`security_id`는 저장소가 만든다. 여기서 보내면 identity를 코드가 정하게 된다."""
        rows = [
            {
                "ticker": security.ticker,
                "cik": security.cik,
                "exchange_code": security.exchange_code,
                "security_type": security.security_type,
                "security_title": security.security_title,
                "is_active_listing": security.is_active_listing,
                "is_tracked": security.is_tracked,
            }
            for security in securities
        ]
        return self._db.upsert(schema=SCHEMA, table=T_SECURITIES, rows=rows, on_conflict="ticker")

    def upsert_identifiers(self, rows: Iterable[dict[str, Any]]) -> int:
        """원천 식별자를 identity 브리지에 적는다.

        현재 ticker도 명시적으로 남겨야 과거 ticker/CUSIP writer가 같은 계약으로
        조회한다. ``valid_from``은 원천이 정확한 시작일을 주지 않을 때의 정직한
        `-infinity` 값이며, mapping 실패를 mapped로 꾸미지 않는다.
        """
        return self._db.upsert(
            schema=SCHEMA,
            table=T_IDENTIFIERS,
            rows=list(rows),
            on_conflict="identifier,identifier_type,valid_from",
        )

    def record_membership(self, snapshot: MembershipSnapshot, *, source_hash: str) -> int:
        """새 스냅샷을 security interval로 반영한다.

        이 경계에서는 ticker를 current security identity로만 변환한다. historical
        ticker 해석은 security_identifiers가 담당한다.
        """
        if snapshot.index_code == INDEX_SP500 and not 450 <= len(snapshot.tickers) <= 520:
            raise ValueError("S&P 500 membership must contain 450..520 unique securities")
        resolved = self.security_ids(snapshot.tickers)
        if len(resolved) != len(snapshot.tickers):
            missing = sorted(set(snapshot.tickers) - set(resolved))
            raise ValueError("membership has unknown securities: " + ",".join(missing))
        result = self._db.rpc(SCHEMA, RPC_REPLACE_MEMBERSHIP, {
            "p_index_code": snapshot.index_code, "p_effective_date": snapshot.effective_date.isoformat(),
            "p_security_ids": sorted(resolved.values()), "p_source": snapshot.source, "p_source_hash": source_hash,
        }).execute().data
        return int(result)


__all__ = [
    "INDEX_SP500",
    "SCHEMA",
    "T_ENTITIES",
    "T_IDENTIFIERS",
    "T_MEMBERSHIPS",
    "T_SECURITIES",
    "UniverseRepository",
]
