"""정정이 원본을 덮지 않고, as-of 조회가 그때의 값을 준다."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from investment_agent.data.fundamentals.domain.filings import Filing
from investment_agent.data.fundamentals.infrastructure.supabase.expectations import (
    _project_fundamental_rows,
)
from investment_agent.data.fundamentals.repository import (
    SCHEMA,
    T_ESTIMATES,
    T_FILINGS,
    T_PROCESSING,
    T_SCHEDULE,
    FundamentalsRepository,
)
from tests.investment_agent.fakes import FakeDatabase

CIK = "0000320193"
ORIGINAL = "0000320193-25-000001"
RESTATED = "0000320193-25-000009"


def _version(accession: str, revenue: float, *, ingested_at: str) -> dict:
    return {"cik": CIK, "period_end": "2025-12-31", "fiscal_period": "Q4", "fiscal_year": 2025,
            "accession_no": accession, "mapping_version": "v1", "revenue": revenue,
            "ingested_at": ingested_at}


PROVENANCE = {
    ORIGINAL: {"accession_no": ORIGINAL, "filing_date": "2026-02-01", "form_type": "10-K",
               "available_at": "2026-02-02T00:00:00+00:00"},
    RESTATED: {"accession_no": RESTATED, "filing_date": "2026-06-01", "form_type": "10-K/A",
               "available_at": "2026-06-03T00:00:00+00:00"},
}
VERSIONS = [
    _version(ORIGINAL, 100.0, ingested_at="2026-02-02T00:00:00+00:00"),
    _version(RESTATED, 95.0, ingested_at="2026-06-03T00:00:00+00:00"),
]


def _as_of(when: datetime, *, include_available_at: bool = True) -> list[dict]:
    return _project_fundamental_rows("AAPL", VERSIONS, PROVENANCE, when,
                                     include_available_at=include_available_at, limit=12)


class VersionSelectionTest(unittest.TestCase):
    """정정 공시가 원본을 지우지 않고, cutoff마다 그때 알 수 있던 버전 하나를 고른다."""

    def test_before_the_restatement_the_original_value_is_returned(self) -> None:
        rows = _as_of(datetime(2026, 3, 1, tzinfo=timezone.utc))
        self.assertEqual([(ORIGINAL, 100.0)], [(row["accession_no"], row["revenue"]) for row in rows])

    def test_after_the_restatement_only_the_restated_value_is_returned(self) -> None:
        rows = _as_of(datetime(2026, 7, 1, tzinfo=timezone.utc))
        self.assertEqual([(RESTATED, 95.0)], [(row["accession_no"], row["revenue"]) for row in rows])

    def test_before_anything_arrived_is_empty(self) -> None:
        self.assertEqual([], _as_of(datetime(2026, 1, 1, tzinfo=timezone.utc)))

    def test_operational_replay_waits_until_we_actually_had_the_filing(self) -> None:
        """SEC 제출일(6/1)이 지났어도 우리가 받은 것은 6/3이다 — 운영 재현은 원본을 쓴다."""
        versions = [VERSIONS[0], {**VERSIONS[1], "ingested_at": None}]
        when = datetime(2026, 6, 2, 12, tzinfo=timezone.utc)

        def pick(include: bool) -> list[str]:
            return [row["accession_no"] for row in _project_fundamental_rows(
                "AAPL", versions, PROVENANCE, when, include_available_at=include, limit=12)]

        self.assertEqual([ORIGINAL], pick(True))
        self.assertEqual([RESTATED], pick(False))

    def test_source_replay_waits_for_the_end_of_the_filing_day_in_new_york(self) -> None:
        """6/1 제출 공시는 6/2 00:00 UTC(뉴욕 6/1 저녁)에는 아직 쓰지 않는다 — 장 마감 뒤 공시일 수 있다."""
        versions = [VERSIONS[0], {**VERSIONS[1], "ingested_at": None}]

        def pick(when: datetime) -> list[str]:
            return [row["accession_no"] for row in _project_fundamental_rows(
                "AAPL", versions, PROVENANCE, when, include_available_at=False, limit=12)]

        self.assertEqual([ORIGINAL], pick(datetime(2026, 6, 2, 3, 59, tzinfo=timezone.utc)))
        self.assertEqual([RESTATED], pick(datetime(2026, 6, 2, 4, 0, tzinfo=timezone.utc)))

    def test_operational_replay_also_waits_until_the_version_was_stored(self) -> None:
        """공시는 받았어도 재처리한 버전 행이 cutoff 뒤에 생겼으면 그때는 몰랐던 값이다."""
        provenance = {**PROVENANCE, RESTATED: {**PROVENANCE[RESTATED], "available_at": "2026-06-01T12:00:00+00:00"}}
        when = datetime(2026, 6, 2, tzinfo=timezone.utc)
        rows = _project_fundamental_rows("AAPL", VERSIONS, provenance, when, include_available_at=True, limit=12)
        self.assertEqual([ORIGINAL], [row["accession_no"] for row in rows])

    def test_a_version_without_its_filing_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            _project_fundamental_rows("AAPL", VERSIONS, {ORIGINAL: PROVENANCE[ORIGINAL]},
                                      datetime(2026, 7, 1, tzinfo=timezone.utc),
                                      include_available_at=True, limit=12)


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
             "eps_analysts": 30, "snapshot_kind": "captured_live"},
            # 발표 뒤에 갱신된 값. 서프라이즈 계산에 쓰이면 안 된다.
            {"security_id": 1, "target_fiscal_year": 2026, "target_fiscal_period": "Q1",
             "snapshot_date": "2026-05-10", "eps_avg": 1.62, "revenue_avg": 95.0,
             "eps_analysts": 31, "snapshot_kind": "captured_live"},
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
