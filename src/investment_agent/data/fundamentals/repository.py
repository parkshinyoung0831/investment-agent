"""fundamentals 스키마를 읽고 쓰는 유일한 자리.

## 재무는 CIK 사실이다

SEC CompanyFacts는 등록인(CIK) 단위로 온다. 한 CIK에 상장 종목이 여럿일 수 있으므로
(듀얼클래스), 종목별로 펼치는 것은 **읽는 쪽**이 한다. 저장은 CIK로 한 번만 한다 —
펼쳐 저장하면 같은 숫자가 여러 행에 복사되고, 정정이 들어올 때 일부만 갱신되는 길이
열린다.

## 재무는 공시 버전으로 쌓는다

정정 공시는 `financial_versions`에 새 행으로 들어가고, 기간별 최신 값은
`fundamentals.financials` 뷰가 고른다. 쓰기는 `infrastructure/supabase/company_financials.py`,
과거 시점 조회는 `infrastructure/supabase/expectations.py`가 맡는다.

## 처리 상태와 공시 사실을 나눠 읽는다

"어떤 공시가 있는가"는 `filings`, "우리가 그것을 어떻게 처리했는가"는
`filing_processing`이다. 재처리 대상을 고를 때 후자만 보므로, 재처리 정책을 바꿔도
공시 사실은 그대로 남는다.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Any

from investment_agent.data.fundamentals.domain.filings import Filing, filing_row
from investment_agent.platform.clock import as_date
from investment_agent.platform.db.postgres import Database
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

SCHEMA = "fundamentals"

T_FILINGS = "filings"
T_PROCESSING = "filing_processing"
T_FINANCIALS = "financials"  # 뷰: 기간별 최신 공시 버전
T_FINANCIAL_VERSIONS = "financial_versions"
T_SHARE_CLASSES = "share_class_snapshots"
T_SEGMENTS = "segment_metrics"
T_EARNINGS = "earnings_results"
T_ESTIMATES = "earnings_estimates"
T_SCHEDULE = "earnings_schedule_versions"
T_ANALYST_SNAPSHOTS = "analyst_consensus_snapshots"

CONTENT_TYPES = ("company", "segments")

_FILING_COLUMNS = "accession_no, cik, form_type, filing_date, report_date, available_at, source"


class FundamentalsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ── 공시 ──────────────────────────────────────────────────────────────
    def filings_for(
        self, ciks: Sequence[str], *, since: date | None = None
    ) -> list[Filing]:
        rows = self._db.select_in_chunks(
            schema=SCHEMA,
            table=T_FILINGS,
            columns=_FILING_COLUMNS,
            filter_column="cik",
            values=list(ciks),
            configure=(lambda query: query.gte("filing_date", since.isoformat()))
            if since is not None else None,
            order_by="cik, filing_date",
        )
        return [Filing.from_row(row) for row in rows]

    def unprocessed_accessions(
        self, *, content_type: str, mapping_version: str, ciks: Sequence[str]
    ) -> list[str]:
        """아직 이 매핑 세대로 처리하지 않은 공시.

        처리 표에서 **이미 한 것**을 빼는 방식이다. 반대로 "처리할 것"을 표에 미리
        넣어 두면, 그 표가 비는 순간 재처리가 조용히 아무것도 안 한다.
        """
        if content_type not in CONTENT_TYPES:
            raise ValueError(f"unknown content_type: {content_type!r}")
        known = {
            row["accession_no"]
            for row in self._db.select_paged(
                lambda: self._db.table(SCHEMA, T_PROCESSING)
                .select("accession_no")
                .eq("content_type", content_type)
                .eq("mapping_version", mapping_version),
                order_by="accession_no",
            )
        }
        return [
            filing.accession_no
            for filing in self.filings_for(ciks)
            if filing.accession_no not in known
        ]

    # ── 실적 ──────────────────────────────────────────────────────────────
    def earnings_results(self, ciks: Sequence[str], *, since: date | None = None) -> list[dict[str, Any]]:
        return self._db.select_in_chunks(
            schema=SCHEMA,
            table=T_EARNINGS,
            columns=("cik, accession_no, fiscal_year, fiscal_period, period_end, "
                     "revenue_actual, eps_actual, guidance_summary, press_release_url"),
            filter_column="cik",
            values=list(ciks),
            configure=(lambda query: query.gte("period_end", since.isoformat()))
            if since is not None else None,
            order_by="cik, period_end",
        )

    def consensus_before(
        self, security_id: int, *, fiscal_year: int, fiscal_period: str, on_or_before: date
    ) -> dict[str, Any] | None:
        """발표 시점 이전 **마지막** 컨센서스.

        최신 컨센서스를 쓰면 과거 서프라이즈가 매일 조금씩 달라진다. 그러면 "그때
        놀라운 실적이었나"에 답할 수 없고, 학습 label로도 쓸 수 없다.
        """
        rows = (
            self._db.table(SCHEMA, T_ESTIMATES)
            .select("eps_avg, revenue_avg, snapshot_date, eps_analysts, snapshot_kind")
            .eq("security_id", security_id)
            .eq("target_fiscal_year", fiscal_year)
            .eq("target_fiscal_period", fiscal_period)
            .lte("snapshot_date", on_or_before.isoformat())
            .order("snapshot_date", desc=True)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def scheduled_reports(
        self, *, on_date: date, session: str | None = None
    ) -> list[dict[str, Any]]:
        """그날 발표 예정. 관측일마다 행이 쌓이므로 종목·기간별 **마지막 관측**만 남긴다."""
        def factory() -> Any:
            query = (
                self._db.table(SCHEMA, T_SCHEDULE)
                .select("security_id, target_fiscal_year, target_fiscal_period, "
                        "expected_report_at, expected_report_date, expected_session, "
                        "is_estimated, snapshot_date")
                .eq("expected_report_date", on_date.isoformat())
            )
            if session is not None:
                query = query.eq("expected_session", session)
            return query

        newest: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
        for row in self._db.select_paged(factory, order_by="security_id, snapshot_date"):
            key = (row["security_id"], row["target_fiscal_year"], row["target_fiscal_period"])
            current = newest.get(key)
            if current is None or str(row["snapshot_date"]) >= str(current["snapshot_date"]):
                newest[key] = row
        return list(newest.values())

    def schedule_snapshots(self, security_ids: Sequence[int]) -> list[dict[str, Any]]:
        """관심종목의 발표 예정 스냅샷을 전부 읽는다(마지막 관측 선택은 reader가 한다)."""
        if not security_ids:
            return []
        return self._db.select_in_chunks(
            schema=SCHEMA,
            table=T_SCHEDULE,
            columns=("security_id,target_fiscal_year,target_fiscal_period,target_period_end,"
                     "snapshot_date,expected_report_at,expected_report_date,expected_session,is_estimated"),
            filter_column="security_id",
            values=list(security_ids),
            order_by="security_id,snapshot_date",
        )

    def filing_periods(self, ciks: Sequence[str]) -> list[dict[str, Any]]:
        """재무 기간과 제출일을 ticker reader가 작년 비교에 사용할 모양으로 돌려준다."""
        if not ciks:
            return []
        versions = self._db.select_in_chunks(
            schema=SCHEMA,
            table=T_FINANCIALS,
            columns="cik,fiscal_year,fiscal_period,period_end,accession_no,filing_date",
            filter_column="cik",
            values=list(ciks),
            order_by="cik,period_end",
        )
        return [
            {**row, "filed_at": row.get("filing_date")}
            for row in versions
            if row.get("filing_date")
        ]

    # ── 쓰기 ──────────────────────────────────────────────────────────────
    def upsert_filings(self, filings: Iterable[object]) -> int:
        """`available_at`은 보내지 않는다 — 저장소가 찍는 PIT 경계다."""
        return self._db.upsert(
            schema=SCHEMA,
            table=T_FILINGS,
            rows=[filing_row(filing) for filing in filings],
            on_conflict="accession_no",
        )

    def record_processing(
        self,
        *,
        accession_no: str,
        content_type: str,
        mapping_version: str,
        status: str,
        facts_count: int,
        rows_count: int,
    ) -> int:
        return self._db.upsert(
            schema=SCHEMA,
            table=T_PROCESSING,
            rows=[{
                "accession_no": accession_no,
                "content_type": content_type,
                "mapping_version": mapping_version,
                "status": status,
                "facts_count": facts_count,
                "rows_count": rows_count,
            }],
            on_conflict="accession_no,content_type,mapping_version",
        )


__all__ = [
    "CONTENT_TYPES",
    "FundamentalsRepository",
    "SCHEMA",
    "T_ANALYST_SNAPSHOTS",
    "T_EARNINGS",
    "T_ESTIMATES",
    "T_FILINGS",
    "T_FINANCIALS",
    "T_FINANCIAL_VERSIONS",
    "T_PROCESSING",
    "T_SCHEDULE",
    "T_SEGMENTS",
    "T_SHARE_CLASSES",
]
