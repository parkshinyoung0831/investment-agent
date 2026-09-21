"""과거 재현 backfill: 평일 판단 시각, 이미 있는 시점 건너뛰기, 밸류에이션 → feature 순서."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from investment_agent.research.commands.backfill_research_history import (
    BackfillDateState,
    audit_backfill,
    backfill,
    replay_dates,
)


class ReplayDatesTest(unittest.TestCase):
    def test_dates_are_weekdays_after_the_daily_bar_is_final(self):
        dates = replay_dates(start=date(2025, 6, 7), end=date(2025, 6, 30), every_days=7)  # 6/7 토요일
        self.assertEqual([moment.date().isoformat() for moment in dates],
                         ["2025-06-06", "2025-06-13", "2025-06-20", "2025-06-27"])
        self.assertTrue(all(moment.weekday() < 5 and moment.hour == 23 for moment in dates))

    def test_invalid_ranges_are_rejected(self):
        with self.assertRaises(ValueError):
            replay_dates(start=date(2025, 6, 1), end=date(2025, 5, 1), every_days=7)
        with self.assertRaises(ValueError):
            replay_dates(start=date(2025, 6, 1), end=date(2025, 7, 1), every_days=0)


class BackfillTest(unittest.TestCase):
    def setUp(self):
        self.calls: list[tuple[str, str]] = []
        self.dates = [datetime(2025, 6, day, 23, 30, tzinfo=timezone.utc) for day in (6, 13, 20)]

    def _build(self, name):
        def run(**kwargs):
            self.calls.append((name, kwargs["as_of_at"].date().isoformat()))
            assert kwargs["source_kind"] == "historical_replay"
            return {"rows_upserted": len(kwargs["tickers"]), "status": "success"}
        return run

    def test_existing_dates_are_skipped_and_valuations_come_before_features(self):
        results = backfill(
            dates=self.dates, universe=lambda as_of: ["AAA", "BBB"],
            date_state=lambda as_of, tickers: BackfillDateState(completed=as_of.day == 13),
            build_valuations=self._build("valuations"), build_features=self._build("features"),
        )
        self.assertEqual([row["status"] for row in results], ["built", "skipped_existing", "built"])
        self.assertEqual(self.calls, [("valuations", "2025-06-06"), ("features", "2025-06-06"),
                                      ("valuations", "2025-06-20"), ("features", "2025-06-20")])

    def test_max_dates_limits_only_new_work(self):
        results = backfill(
            dates=self.dates, universe=lambda as_of: ["AAA"],
            date_state=lambda as_of, tickers: BackfillDateState(completed=as_of.day == 6),
            build_valuations=self._build("valuations"), build_features=self._build("features"), max_dates=1,
        )
        self.assertEqual([row["status"] for row in results], ["skipped_existing", "built"])

    def test_a_date_without_membership_builds_nothing(self):
        results = backfill(
            dates=self.dates[:1], universe=lambda as_of: [],
            date_state=lambda as_of, tickers: BackfillDateState(),
            build_valuations=self._build("valuations"), build_features=self._build("features"),
        )
        self.assertEqual(results[0]["status"], "no_membership")
        self.assertEqual(self.calls, [])

    def test_partial_date_rebuilds_only_missing_tickers_and_records_the_result(self):
        recorded = []
        results = backfill(
            dates=self.dates[:1], universe=lambda as_of: ["AAA", "BBB", "CCC"],
            date_state=lambda as_of, tickers: BackfillDateState(terminal_tickers=frozenset({"AAA"})),
            build_valuations=self._build("valuations"), build_features=self._build("features"),
            record_result=lambda as_of, tickers, result: recorded.append((as_of, tickers, result)),
        )
        self.assertEqual(results[0]["resumed_tickers"], 2)
        self.assertEqual(recorded[0][1], ["AAA", "BBB", "CCC"])
        self.assertEqual(recorded[0][2]["status"], "built")

    def test_membership_is_resolved_before_date_state(self):
        order = []

        def universe(as_of):
            order.append("universe")
            return ["AAA"]

        def date_state(as_of, tickers):
            order.append(("state", tuple(tickers)))
            return BackfillDateState(completed=True)

        backfill(
            dates=self.dates[:1], universe=universe, date_state=date_state,
            build_valuations=self._build("valuations"), build_features=self._build("features"),
        )
        self.assertEqual(order, ["universe", ("state", ("AAA",))])


class BackfillAuditTest(unittest.TestCase):
    def test_audit_reports_snapshot_terminal_and_missing_coverage_without_building(self):
        moment = datetime(2025, 6, 6, 23, 30, tzinfo=timezone.utc)
        rows = audit_backfill(
            dates=[moment],
            universe=lambda as_of: ["AAA", "BBB", "CCC", "DDD"],
            date_state=lambda as_of, tickers: BackfillDateState(
                stored_tickers=frozenset({"AAA", "BBB"}),
                terminal_tickers=frozenset({"AAA", "BBB", "CCC"}),
                unavailable_tickers=frozenset({"CCC"}),
            ),
        )
        self.assertEqual(rows, [{
            "as_of_at": moment.isoformat(),
            "status": "incomplete",
            "expected_count": 4,
            "snapshot_count": 2,
            "unavailable_count": 1,
            "terminal_count": 3,
            "coverage": 0.75,
            # 종목 하나는 봉이 없어 표본에서 빠졌다 — coverage(끝난 비율)가 가리는 사실이다.
            "snapshot_coverage": 0.5,
            "missing_tickers": ["DDD"],
        }])

    def test_audit_does_not_trust_a_completed_flag_when_members_are_missing(self):
        moment = datetime(2025, 6, 6, 23, 30, tzinfo=timezone.utc)
        rows = audit_backfill(
            dates=[moment], universe=lambda as_of: ["AAA", "BBB"],
            date_state=lambda as_of, tickers: BackfillDateState(
                completed=True, stored_tickers=frozenset({"AAA"}), terminal_tickers=frozenset({"AAA"}),
            ),
        )
        self.assertEqual(rows[0]["status"], "inconsistent_completed")
        self.assertEqual(rows[0]["missing_tickers"], ["BBB"])


if __name__ == "__main__":
    unittest.main()
