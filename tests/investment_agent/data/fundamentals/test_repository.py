"""정정이 원본을 덮지 않고, as-of 조회가 그때의 값을 준다."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from investment_agent.data.fundamentals.domain.filings import Filing
from investment_agent.data.fundamentals.repository import (
    SCHEMA,
    T_ESTIMATES,
    T_FILINGS,
    T_FINANCIALS,
    T_PROCESSING,
    T_SCHEDULE,
    FundamentalsRepository,
)
from tests.investment_agent.fakes import FakeDatabase

CIK = "0000320193"
ORIGINAL = "0000320193-25-000001"
RESTATED = "0000320193-25-000009"


def _financial_row(
    *, accession: str = RESTATED, filing_date: str = "2026-06-01", revenue: float = 95.0,
    period_end: str = "2025-12-31", fiscal_period: str = "Q4",
) -> dict:
    return {
        "cik": CIK, "period_end": period_end, "fiscal_period": fiscal_period,
        "revenue": revenue, "source_accession_no": accession, "source_filing_date": filing_date,
    }


class VersionSelectionTest(unittest.TestCase):
    """canonical 정책: 기간별 한 행만 있고, 정정 전 숫자는 복원하지 않는다 —
    의도적 한계다(repository.py의 ``financials``/``restated_periods`` 문서 참고)."""

    def setUp(self) -> None:
        self.db = FakeDatabase()
        self.db.put(SCHEMA, T_FINANCIALS, [_financial_row()])
        self.repo = FundamentalsRepository(self.db)

    def test_both_versions_are_kept(self) -> None:
        """PK에 accession_no가 없어도 기간별 최대 한 행이라는 계약은 지켜야 한다."""
        versions = self.repo.financial_versions(CIK)
        self.assertEqual([date(2025, 12, 31)], list(versions))
        self.assertEqual(1, len(versions[date(2025, 12, 31)]))
        self.assertEqual(RESTATED, versions[date(2025, 12, 31)][0].accession_no)

    def test_without_as_of_the_restated_value_is_returned(self) -> None:
        rows = self.repo.financials(CIK, "cik, period_end, source_accession_no, revenue")
        self.assertEqual([RESTATED], [row["source_accession_no"] for row in rows])
        self.assertEqual(95.0, rows[0]["revenue"])

    def test_as_of_before_the_restatement_returns_the_original(self) -> None:
        """canonical 정책에서는 '그때 우리가 알던 값'을 복원하지 않는다 — 그 시점에
        아직 공시가 없었다는 사실만 반영해 행을 통째로 제외한다."""
        rows = self.repo.financials(
            CIK, "cik, period_end, source_accession_no, revenue",
            as_of=datetime(2026, 3, 1, tzinfo=timezone.utc),
        )
        self.assertEqual([], rows)

    def test_as_of_before_anything_arrived_is_empty(self) -> None:
        rows = self.repo.financials(
            CIK, "cik, period_end, source_accession_no, revenue",
            as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.assertEqual([], rows)

    def test_as_of_after_the_filing_shows_the_current_canonical_value(self) -> None:
        rows = self.repo.financials(
            CIK, "cik, period_end, source_accession_no, revenue",
            as_of=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(95.0, rows[0]["revenue"])

    def test_restated_periods_lists_only_what_changed(self) -> None:
        """canonical 정책은 정정 횟수를 재현하지 않는다 — 항상 빈 목록이다."""
        self.assertEqual([], self.repo.restated_periods(CIK))


class ProcessingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = FakeDatabase()
        self.db.put(SCHEMA, T_FILINGS, [
            {"accession_no": ORIGINAL, "cik": CIK, "form_type": "10-K",
             "filing_date": "2026-02-01", "report_date": None,
             "available_at": None, "source": "sec_edgar"},
            {"accession_no": RESTATED, "cik": CIK, "form_type": "10-K/A",
             "filing_date": "2026-06-01", "report_date": None,
             "available_at": None, "source": "sec_edgar"},
        ])
        self.db.put(SCHEMA, T_PROCESSING, [
            {"accession_no": ORIGINAL, "content_type": "company", "mapping_version": "v3"},
        ])
        self.repo = FundamentalsRepository(self.db)

    def test_already_processed_filings_are_skipped(self) -> None:
        pending = self.repo.unprocessed_accessions(
            content_type="company", mapping_version="v3", ciks=[CIK]
        )
        self.assertEqual([RESTATED], pending)

    def test_a_new_mapping_version_reprocesses_everything(self) -> None:
        """매핑 세대가 바뀌면 같은 공시를 다시 읽어야 한다."""
        pending = self.repo.unprocessed_accessions(
            content_type="company", mapping_version="v4", ciks=[CIK]
        )
        self.assertEqual([ORIGINAL, RESTATED], sorted(pending))

    def test_an_unknown_content_type_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.repo.unprocessed_accessions(
                content_type="prices", mapping_version="v3", ciks=[CIK]
            )


class ConsensusTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = FakeDatabase()
        self.db.put(SCHEMA, T_ESTIMATES, [
            {"security_id": 1, "target_fiscal_year": 2026, "target_fiscal_period": "Q1",
             "snapshot_date": "2026-04-20", "eps_avg": 1.50, "revenue_avg": 90.0,
             "eps_analysts": 30, "snapshot_kind": "observed"},
            # 발표 뒤에 갱신된 값. 서프라이즈 계산에 쓰이면 안 된다.
            {"security_id": 1, "target_fiscal_year": 2026, "target_fiscal_period": "Q1",
             "snapshot_date": "2026-05-10", "eps_avg": 1.62, "revenue_avg": 95.0,
             "eps_analysts": 31, "snapshot_kind": "observed"},
        ])
        self.repo = FundamentalsRepository(self.db)

    def test_the_snapshot_before_the_announcement_is_used(self) -> None:
        """최신 컨센서스를 쓰면 과거 서프라이즈가 매일 조금씩 달라진다."""
        row = self.repo.consensus_before(
            1, fiscal_year=2026, fiscal_period="Q1", on_or_before=date(2026, 5, 1)
        )
        self.assertEqual(1.50, row["eps_avg"])

    def test_no_snapshot_before_the_date_is_none(self) -> None:
        row = self.repo.consensus_before(
            1, fiscal_year=2026, fiscal_period="Q1", on_or_before=date(2026, 1, 1)
        )
        self.assertIsNone(row)


class ScheduleTest(unittest.TestCase):
    def test_only_the_last_observation_per_period_survives(self) -> None:
        """예정일은 자주 바뀐다. 관측이 쌓인 채로 세면 같은 발표가 여러 번 잡힌다."""
        db = FakeDatabase()
        db.put(SCHEMA, T_SCHEDULE, [
            {"security_id": 1, "target_fiscal_year": 2026, "target_fiscal_period": "Q1",
             "expected_report_at": "2026-05-01T20:00:00+00:00", "expected_report_date": "2026-05-01",
             "expected_session": "amc", "is_estimated": True, "snapshot_date": "2026-04-01"},
            {"security_id": 1, "target_fiscal_year": 2026, "target_fiscal_period": "Q1",
             "expected_report_at": "2026-05-01T20:00:00+00:00", "expected_report_date": "2026-05-01",
             "expected_session": "amc", "is_estimated": False, "snapshot_date": "2026-04-20"},
        ])
        rows = FundamentalsRepository(db).scheduled_reports(on_date=date(2026, 5, 1))
        self.assertEqual(1, len(rows))
        self.assertEqual("2026-04-20", rows[0]["snapshot_date"])
        self.assertFalse(rows[0]["is_estimated"])

    def test_session_filter_narrows_the_watch_window(self) -> None:
        db = FakeDatabase()
        db.put(SCHEMA, T_SCHEDULE, [
            {"security_id": 1, "target_fiscal_year": 2026, "target_fiscal_period": "Q1",
             "expected_report_at": "2026-05-01T11:00:00+00:00", "expected_report_date": "2026-05-01",
             "expected_session": "bmo", "is_estimated": False, "snapshot_date": "2026-04-20"},
            {"security_id": 2, "target_fiscal_year": 2026, "target_fiscal_period": "Q1",
             "expected_report_at": "2026-05-01T20:00:00+00:00", "expected_report_date": "2026-05-01",
             "expected_session": "amc", "is_estimated": False, "snapshot_date": "2026-04-20"},
        ])
        rows = FundamentalsRepository(db).scheduled_reports(on_date=date(2026, 5, 1), session="amc")
        self.assertEqual([2], [row["security_id"] for row in rows])


class WriteTest(unittest.TestCase):
    def test_financial_upsert_conflicts_on_the_fiscal_period_not_the_accession(self) -> None:
        """accession_no가 충돌 키에 있으면 정정마다 새 행이 쌓여 canonical 정책이
        깨진다 — 기간 키만으로 충돌해야 정정이 같은 행을 덮어쓴다."""
        db = FakeDatabase()
        FundamentalsRepository(db).upsert_financials([
            {"cik": CIK, "period_end": "2025-12-31", "fiscal_period": "Q4",
             "source_accession_no": RESTATED, "revenue": 95.0},
        ])
        (_key, _rows, conflict) = db.upserts[0]
        self.assertEqual("cik,period_end,fiscal_period", conflict)

    def test_filings_upsert_does_not_send_available_at(self) -> None:
        db = FakeDatabase()
        FundamentalsRepository(db).upsert_filings([
            Filing(ORIGINAL, CIK, "10-K", date(2026, 2, 1)),
        ])
        (_key, rows, conflict) = db.upserts[0]
        self.assertNotIn("available_at", rows[0])
        self.assertEqual("accession_no", conflict)


if __name__ == "__main__":
    unittest.main()
