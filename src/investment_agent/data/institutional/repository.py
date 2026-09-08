"""institutional 스키마를 읽고 쓰는 유일한 자리.

## CUSIP은 여기서 종목으로 바꾸지 않는다

13F는 CUSIP으로만 온다. 그것을 `security_id`로 옮기는 것은 `universe`의 일이고,
이 저장소는 신고 원문에 있는 그대로를 돌려준다. 여기서 매핑까지 하면 매핑 규칙이
두 곳에 생기고, 못 붙은 CUSIP을 어떻게 다뤘는지 추적할 수 없게 된다.

## 45일 지연이 PIT 경계다

13F는 분기말 상태를 **최대 45일 뒤에** 낸다. `period_end` 시점에 그 내용을 알았다고
가정하면 backtest가 한 분기를 통째로 미리 본다. 시점 조회는 `filing_date`로 자른다.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

from investment_agent.data.institutional.domain.holdings import (
    Filing13F,
    Position,
    effective_filings,
    portfolio_weights,
)
from investment_agent.data.institutional.domain import managers as manager_config
from investment_agent.platform.db.postgres import Database
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

SCHEMA = "institutional"

T_MANAGERS = "managers"
T_FILINGS = "filings"
T_POSITIONS = "positions"

_FILING_COLUMNS = (
    "accession_no, manager_cik, period_end, form_type, filing_date, "
    "amendment_type, amendment_no, reported_value_usd"
)
_POSITION_COLUMNS = (
    "accession_no, source_row_no, issuer_name, identifier, identifier_type, "
    "value_usd, quantity, quantity_type, position_kind"
)


class InstitutionalRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ── 매니저 ────────────────────────────────────────────────────────────
    def active_managers(self) -> list[dict[str, Any]]:
        """추적 대상 manager 목록. manager_cik/name/fund_name/is_active의 SSOT는
        코드 설정(`investment_agent.data.institutional.managers`)이다 —
        Supabase에는 이 사실을 담는 테이블이 없다."""
        return manager_config.active_managers()

    def known_accessions(self) -> set[str]:
        """이미 원장에 있는 SEC accession. 신규 수집만 원천에 요청할 때 쓴다."""
        return {
            str(row["accession_no"])
            for row in self._db.select_paged(
                lambda: self._db.table(SCHEMA, T_FILINGS).select("accession_no"),
                order_by="accession_no",
            )
        }

    # ── 신고 ──────────────────────────────────────────────────────────────
    def filings(
        self,
        manager_ciks: Sequence[str],
        *,
        period_end: date | None = None,
        known_at: date | None = None,
    ) -> list[Filing13F]:
        """신고 목록. `known_at`을 주면 그날까지 **제출된** 것만 준다.

        분기말이 아니라 제출일로 자르는 것이 핵심이다 — 13F는 45일 늦게 나온다.
        """
        def configure(query: Any) -> Any:
            if period_end is not None:
                query = query.eq("period_end", period_end.isoformat())
            if known_at is not None:
                query = query.lte("filing_date", known_at.isoformat())
            return query

        rows = self._db.select_in_chunks(
            schema=SCHEMA,
            table=T_FILINGS,
            columns=_FILING_COLUMNS,
            filter_column="manager_cik",
            values=list(manager_ciks),
            configure=configure,
            order_by="manager_cik, period_end, filing_date",
        )
        return [Filing13F.from_row(row) for row in rows]

    def effective_filings(
        self,
        manager_ciks: Sequence[str],
        *,
        period_end: date | None = None,
        known_at: date | None = None,
    ) -> list[Filing13F]:
        """정정 규칙을 적용한 뒤 남는 신고들. 보유를 셀 때는 반드시 이것을 쓴다."""
        return effective_filings(
            self.filings(manager_ciks, period_end=period_end, known_at=known_at)
        )

    # ── 보유 ──────────────────────────────────────────────────────────────
    def positions(self, accession_nos: Sequence[str]) -> list[Position]:
        rows = self._db.select_in_chunks(
            schema=SCHEMA,
            table=T_POSITIONS,
            columns=_POSITION_COLUMNS,
            filter_column="accession_no",
            values=list(accession_nos),
            order_by="accession_no, source_row_no",
        )
        return [Position.from_row(row) for row in rows]

    def weights_for(
        self, manager_cik: str, *, period_end: date, known_at: date | None = None
    ) -> dict[str, float]:
        """그 분기 포트폴리오 비중(CUSIP 기준).

        `effective_filings`를 거치므로 정정이 이중 계산되지 않는다.
        """
        filings = self.effective_filings(
            [manager_cik], period_end=period_end, known_at=known_at
        )
        if not filings:
            return {}
        return portfolio_weights(self.positions([item.accession_no for item in filings]))

    # ── 쓰기 ──────────────────────────────────────────────────────────────
    def upsert_filings(self, rows: Iterable[dict[str, Any]]) -> int:
        return self._db.upsert(
            schema=SCHEMA,
            table=T_FILINGS,
            rows=list(rows),
            on_conflict="accession_no",
        )

    def upsert_positions(self, rows: Iterable[dict[str, Any]]) -> int:
        columns = {
            "accession_no", "source_row_no", "issuer_name", "identifier", "identifier_type",
            "value_usd", "quantity", "quantity_type", "position_kind",
        }
        return self._db.upsert(
            schema=SCHEMA,
            table=T_POSITIONS,
            rows=[{key: value for key, value in row.items() if key in columns} for row in rows],
            on_conflict="accession_no,source_row_no",
        )

    def delete_filings_before(self, cutoff: date) -> int:
        """보존 기간 밖 신고를 지우고 FK cascade로 원천 행도 함께 정리한다."""
        response = (
            self._db.table(SCHEMA, T_FILINGS)
            .delete()
            .lt("period_end", cutoff.isoformat())
            .execute()
        )
        return len(response.data or [])


__all__ = [
    "InstitutionalRepository",
    "SCHEMA",
    "T_FILINGS",
    "T_MANAGERS",
    "T_POSITIONS",
]
