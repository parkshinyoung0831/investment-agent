"""알림 read model이 쓰는 fundamentals 읽기 세 가지(발표 예정·실시간 컨센서스·재무 기간).

쓰기와 PIT 조회는 `infrastructure/supabase/`가 소유한다. 재무는 CIK 사실이라 종목으로
펼치는 것은 읽는 쪽이 한다.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from investment_agent.platform.db.postgres import Database

SCHEMA = "fundamentals"

T_FILINGS = "filings"
T_FINANCIALS = "financials"
T_ESTIMATES = "earnings_estimates"
T_SCHEDULE = "earnings_schedule_versions"


class FundamentalsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def schedule_snapshots(self, security_ids: Sequence[int]) -> list[dict[str, Any]]:
        """관심종목의 발표 예정 스냅샷을 전부 읽는다(마지막 관측 선택은 reader가 한다).

        `snapshot_date`는 이 상태를 **처음** 본 날이고, 마지막으로 다시 확인한 시각은
        `last_seen_at`이다. 신선도는 뒤의 것으로 재야 한다.
        """
        if not security_ids:
            return []
        return self._db.select_in_chunks(
            schema=SCHEMA,
            table=T_SCHEDULE,
            columns=("security_id,target_fiscal_year,target_fiscal_period,target_period_end,"
                     "snapshot_date,expected_report_at,expected_report_date,expected_session,"
                     "is_estimated,last_seen_at"),
            filter_column="security_id",
            values=list(security_ids),
            order_by="security_id,snapshot_date",
        )

    def latest_consensus(
        self, security_ids: Sequence[int], *, seen_since: date
    ) -> dict[tuple[int, int, str], dict[str, Any]]:
        """(종목, 대상 회계연도, 대상 분기)별 가장 최근에 관측한 실시간 컨센서스.

        예정 카드는 "다음 발표에 시장이 무엇을 기대하는가"를 싣는다. 과거 서프라이즈처럼
        발표 시점의 값이 필요한 것(`consensus_before`)과 달리 **지금의 값**이 맞다.

        `captured_live`만 쓴다 — 재구성값은 애널리스트 수·매출이 비어 반쪽 숫자가 된다.
        상태가 바뀔 때만 새 행이 쌓이므로, 지금도 유효한 값은 `last_seen_at`이 최근이다.
        `seen_since`보다 오래 안 보인 행은 수집이 끊긴 것이라 싣지 않고, 이 조건이 조회
        범위(누적 관측 전체)도 묶는다.
        """
        if not security_ids:
            return {}
        rows = self._db.select_in_chunks(
            schema=SCHEMA,
            table=T_ESTIMATES,
            columns=("security_id,target_fiscal_year,target_fiscal_period,snapshot_date,"
                     "eps_avg,eps_analysts,revenue_avg,revenue_analysts"),
            filter_column="security_id",
            values=list(security_ids),
            configure=lambda query: query.eq("snapshot_kind", "captured_live")
            .gte("last_seen_at", seen_since.isoformat()),
            order_by="security_id,target_fiscal_year,target_fiscal_period,snapshot_date",
        )
        latest: dict[tuple[int, int, str], dict[str, Any]] = {}
        for row in rows:  # snapshot_date 오름차순이라 같은 키에서는 뒤의 행이 최신이다.
            key = (int(row["security_id"]), int(row["target_fiscal_year"]),
                   str(row["target_fiscal_period"]))
            latest[key] = row
        return latest

    def filing_periods(self, ciks: Sequence[str]) -> list[dict[str, Any]]:
        """재무 기간과 제출일을 ticker reader가 작년 비교에 사용할 모양으로 돌려준다."""
        if not ciks:
            return []
        periods = self._db.select_in_chunks(
            schema=SCHEMA,
            table=T_FINANCIALS,
            columns="cik,fiscal_year,fiscal_period,period_end,accession_no",
            filter_column="cik",
            values=list(ciks),
            order_by="cik,period_end",
        )
        accessions = sorted({str(row["accession_no"]) for row in periods})
        filed = {
            str(row["accession_no"]): row.get("filing_date")
            for row in self._db.select_in_chunks(
                schema=SCHEMA,
                table=T_FILINGS,
                columns="accession_no,filing_date",
                filter_column="accession_no",
                values=accessions,
                order_by="accession_no",
            )
        } if accessions else {}
        return [
            {**row, "filing_date": filed[key], "filed_at": filed[key]}
            for row in periods
            if filed.get(key := str(row["accession_no"]))
        ]


__all__ = [
    "FundamentalsRepository",
    "SCHEMA",
    "T_ESTIMATES",
    "T_FILINGS",
    "T_FINANCIALS",
    "T_SCHEDULE",
]
