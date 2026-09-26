"""재무는 기간마다 한 행이고, 과거 시점 조회는 그 기간을 처음 공개한 공시일로 자른다."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from investment_agent.data.fundamentals.infrastructure.supabase.expectations import (
    _project_fundamental_rows,
    disclosures_by_period,
)
from investment_agent.data.fundamentals.repository import (
    SCHEMA,
    T_ESTIMATES,
    T_SCHEDULE,
    FundamentalsRepository,
)
from tests.investment_agent.fakes import FakeDatabase

CIK = "0000320193"
ORIGINAL = "0000320193-25-000001"
RESTATED = "0000320193-25-000009"

FILINGS = [
    {"accession_no": ORIGINAL, "cik": CIK, "filing_date": "2026-02-01", "form_type": "10-K",
     "report_date": "2025-12-31", "available_at": "2026-02-02T00:00:00+00:00"},
    {"accession_no": RESTATED, "cik": CIK, "filing_date": "2026-06-01", "form_type": "10-K/A",
     "report_date": "2025-12-31", "available_at": "2026-06-03T00:00:00+00:00"},
]
# 정정 공시가 값을 덮어쓴 뒤의 한 행.
ROW = {"cik": CIK, "period_end": "2025-12-31", "fiscal_period": "Q4", "fiscal_year": 2025,
       "accession_no": RESTATED, "revenue": 95.0, "ingested_at": "2026-06-03T00:00:00+00:00"}


def _as_of(when: datetime, *, include_available_at: bool = True, filings=FILINGS) -> list[dict]:
    return _project_fundamental_rows(
        "AAPL", [ROW], disclosures_by_period([ROW], filings), when,
        include_available_at=include_available_at, limit=12,
    )


class PeriodDisclosureTest(unittest.TestCase):
    """정정 전후 어느 시점이든 기간은 사라지지 않고, 처음 공개된 날부터 보인다."""

    def test_between_the_original_and_the_restatement_the_period_is_visible(self) -> None:
        rows = _as_of(datetime(2026, 3, 1, tzinfo=timezone.utc))
        self.assertEqual([(RESTATED, 95.0, "2026-02-01")],
                         [(row["accession_no"], row["revenue"], row["filed_at"]) for row in rows])

    def test_the_latest_filing_names_the_form_type(self) -> None:
        self.assertEqual("10-K/A", _as_of(datetime(2026, 7, 1, tzinfo=timezone.utc))[0]["form_type"])

    def test_before_the_first_disclosure_is_empty(self) -> None:
        self.assertEqual([], _as_of(datetime(2026, 1, 1, tzinfo=timezone.utc)))

    def test_operational_replay_waits_until_we_actually_had_the_first_filing(self) -> None:
        """SEC 제출일(2/1)이 지났어도 우리가 받은 것은 2/2다."""
        when = datetime(2026, 2, 1, 12, tzinfo=timezone.utc)
        self.assertEqual([], _as_of(when, include_available_at=True))

    def test_source_replay_waits_for_the_end_of_the_filing_day_in_new_york(self) -> None:
        """2/1 제출 공시는 2/2 05:00 UTC(뉴욕 2/2 0시) 전에는 쓰지 않는다 — 장 마감 뒤 공시일 수 있다."""
        self.assertEqual([], _as_of(datetime(2026, 2, 2, 4, 59, tzinfo=timezone.utc),
                                    include_available_at=False))
        self.assertEqual(1, len(_as_of(datetime(2026, 2, 2, 5, 0, tzinfo=timezone.utc),
                                       include_available_at=False)))

    def test_without_the_original_filing_the_restatement_date_bounds_the_period(self) -> None:
        rows = _as_of(datetime(2026, 3, 1, tzinfo=timezone.utc), filings=[FILINGS[1]])
        self.assertEqual([], rows)

    def test_a_row_without_its_filing_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            disclosures_by_period([ROW], [FILINGS[0]])


class ScheduleSnapshotsTest(unittest.TestCase):
    def test_last_seen_at_is_read_so_freshness_can_follow_reconfirmation(self) -> None:
        """snapshot_date는 처음 본 날이다. 마지막 재확인은 last_seen_at에만 있다."""
        db = FakeDatabase()
        db.put(SCHEMA, T_SCHEDULE, [
            {"security_id": 1, "target_fiscal_year": 2026, "target_fiscal_period": "Q4",
             "target_period_end": "2026-08-30", "snapshot_date": "2026-09-13",
             "expected_report_at": "2026-09-24T20:00:00+00:00", "expected_report_date": "2026-09-24",
             "expected_session": "amc", "is_estimated": False,
             "last_seen_at": "2026-09-19T01:31:09+00:00", "collected_at": "2026-09-13T01:00:00+00:00"},
        ])

        (row,) = FundamentalsRepository(db).schedule_snapshots([1])

        self.assertEqual("2026-09-19T01:31:09+00:00", row["last_seen_at"])


class LatestConsensusTest(unittest.TestCase):
    def _repo(self, rows: list[dict]) -> FundamentalsRepository:
        db = FakeDatabase()
        db.put(SCHEMA, T_ESTIMATES, rows)
        return FundamentalsRepository(db)

    @staticmethod
    def _estimate(security_id: int, period: str, snapshot: str, eps: float, *,
                  kind: str = "captured_live", last_seen: str = "2026-09-19T01:00:00+00:00",
                  year: int = 2026) -> dict:
        return {"security_id": security_id, "target_fiscal_year": year,
                "target_fiscal_period": period, "snapshot_kind": kind, "snapshot_date": snapshot,
                "eps_avg": eps, "eps_analysts": 20, "revenue_avg": 100.0, "revenue_analysts": 18,
                "last_seen_at": last_seen}

    def test_the_newest_observation_per_target_period_wins(self) -> None:
        repo = self._repo([
            self._estimate(1, "Q4", "2026-09-13", 6.50),
            self._estimate(1, "Q4", "2026-09-17", 6.53),
            self._estimate(1, "Q1", "2026-09-13", 4.85, year=2027),
        ])

        latest = repo.latest_consensus([1], seen_since=date(2026, 9, 1))

        self.assertEqual(6.53, latest[(1, 2026, "Q4")]["eps_avg"])
        self.assertEqual(4.85, latest[(1, 2027, "Q1")]["eps_avg"])

    def test_reconstructed_history_is_not_a_live_consensus(self) -> None:
        """재구성값은 애널리스트 수·매출이 비어 있다. 예정 카드에 실으면 반쪽 숫자가 된다."""
        repo = self._repo([
            self._estimate(1, "Q4", "2026-09-06", 6.56, kind="reconstructed"),
        ])

        self.assertEqual({}, repo.latest_consensus([1], seen_since=date(2026, 9, 1)))

    def test_observations_no_longer_seen_are_left_out(self) -> None:
        """수집이 끊긴 지 오래된 값은 지금의 컨센서스가 아니다. 조회 범위도 이것으로 묶는다."""
        repo = self._repo([
            self._estimate(1, "Q4", "2026-06-01", 6.00, last_seen="2026-06-02T00:00:00+00:00"),
        ])

        self.assertEqual({}, repo.latest_consensus([1], seen_since=date(2026, 9, 1)))

    def test_only_requested_securities_are_read(self) -> None:
        repo = self._repo([
            self._estimate(1, "Q4", "2026-09-13", 6.50),
            self._estimate(2, "Q4", "2026-09-13", 9.99),
        ])

        latest = repo.latest_consensus([1], seen_since=date(2026, 9, 1))

        self.assertEqual({(1, 2026, "Q4")}, set(latest))

    def test_no_securities_reads_nothing(self) -> None:
        self.assertEqual({}, self._repo([]).latest_consensus([], seen_since=date(2026, 9, 1)))


if __name__ == "__main__":
    unittest.main()
