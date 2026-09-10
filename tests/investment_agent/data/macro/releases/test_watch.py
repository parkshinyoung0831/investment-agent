"""ECON release-time watcher의 due/filter/pending/idempotency 계약."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from investment_agent.data.macro.application import release_calendar as etl
from investment_agent.data.macro.releases import db
from investment_agent.data.macro.commands import econ_calendar_daily as daily
from investment_agent.operations.commands import econ_calendar_watch_releases as watch_releases


_NOW = datetime(2026, 8, 28, 1, 0, tzinfo=timezone.utc)


def _release(series_id: str = "US_CPI") -> dict:
    return {
        "event_key": f"{series_id}:2026-07-01",
        "series_id": series_id,
        "ref_period": "2026-07-01",
        "scheduled_at": "2026-08-28T00:50:00+00:00",
        "schedule_confidence": "exact",
        "status": "scheduled",
    }


class ReleaseWatchTest(unittest.TestCase):
    def test_no_due_release_exits_before_provider_poll(self) -> None:
        with (
            patch.object(etl.db, "due_releases", return_value=[]) as due,
            patch.object(etl.actuals, "fetch_batch") as fetch,
        ):
            result = etl.watch_once(now=_NOW, limit=50)
        due.assert_called_once_with(now=_NOW, limit=50)
        fetch.assert_not_called()
        self.assertEqual(result, {
            "due": 0, "not_available": 0, "observations_inserted": 0,
            "first_actuals": 0, "first_actual_event_keys": [], "failures": [],
        })

    def test_due_events_are_selected_but_comparison_observations_are_kept(self) -> None:
        cpi = _release()
        ism = _release("US_ISM_MANUFACTURING")
        raw = {
            "US_CPI": [{"ref_period": "2026-07-01"}, {"ref_period": "2026-06-01"}],
        }
        with (
            patch.object(etl.db, "due_releases", return_value=[cpi, ism]),
            patch.object(etl.db, "collectible_series", return_value=[{"series_id": "US_CPI", "frequency": "monthly"}]),
            patch.object(etl.db, "measures_by_series", return_value={"US_CPI": [{"transform": "pct_change_12"}]}),
            patch.object(etl.actuals, "fetch_batch", return_value=(raw, [])) as fetch,
            patch.object(etl, "ingest_raw", return_value={
                "observations_inserted": 2, "first_actuals": 1,
                "first_actual_event_keys": [cpi["event_key"]], "actualized_event_keys": [cpi["event_key"]],
            }) as ingest,
        ):
            result = etl.watch_once(now=_NOW, limit=50)
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.kwargs["end"], _NOW.date())
        self.assertEqual(fetch.call_args.kwargs["starts_by_series"]["US_CPI"].isoformat(), "2025-07-01")
        ingest.assert_called_once_with(raw, eligible_event_keys={cpi["event_key"]})
        self.assertEqual(result["due"], 2)
        self.assertEqual(result["first_actuals"], 1)
        self.assertEqual(result["not_available"], 1)
        self.assertEqual(result["failures"], [])

    def test_not_available_yet_does_not_close_release_as_actual(self) -> None:
        release = _release()
        pending = [{"series_id": "US_CPI", "status": "not_available_yet"}]
        with (
            patch.object(etl.db, "due_releases", return_value=[release]),
            patch.object(etl.db, "collectible_series", return_value=[{"series_id": "US_CPI", "frequency": "monthly"}]),
            patch.object(etl.db, "measures_by_series", return_value={"US_CPI": [{"transform": "pct_change_1"}]}),
            patch.object(etl.actuals, "fetch_batch", return_value=({}, pending)),
            patch.object(etl, "ingest_raw", return_value={
                "observations_inserted": 0, "first_actuals": 0,
                "first_actual_event_keys": [], "actualized_event_keys": [],
            }),
        ):
            result = etl.watch_once(now=_NOW, limit=50)
        self.assertEqual(result["not_available"], 1)
        self.assertEqual(result["observations_inserted"], 0)
        self.assertEqual(result["failures"], [])

    def test_entrypoint_retry_is_bounded_and_stops_after_first_actual(self) -> None:
        responses = [
            {"due": 1, "first_actuals": 0, "not_available": 1, "failures": []},
            {"due": 1, "first_actuals": 1, "not_available": 0,
             "first_actual_event_keys": ["US_CPI:2026-07-01"], "failures": []},
        ]
        with (
            patch("investment_agent.platform.db.postgres.Database.from_config"),
            patch.object(db, "configure"),
            patch.object(db, "seed_catalog"),
            patch.object(watch_releases.etl, "watch_once", side_effect=responses) as watch,
            patch.object(watch_releases.time, "sleep") as sleep,
        ):
            exit_code = watch_releases.main([
                "--poll-attempts", "2", "--poll-interval-seconds", "1",
            ])
        self.assertEqual(exit_code, 0)
        self.assertEqual(watch.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_notification_failure_can_be_retried_when_no_release_is_due(self) -> None:
        with (
            patch("investment_agent.platform.db.postgres.Database.from_config"),
            patch.object(db, "configure"),
            patch.object(db, "seed_catalog"),
            patch.object(watch_releases.etl, "watch_once", return_value={"due": 0, "failures": []}),
            patch("investment_agent.notifications.econ_calendar.run.run", return_value=1) as notify,
        ):
            exit_code = watch_releases.main(["--notify"])
        self.assertEqual(exit_code, 0)
        notify.assert_called_once_with()

    def test_entrypoint_fails_when_final_provider_attempt_still_fails(self) -> None:
        failure = {
            "due": 1,
            "first_actuals": 0,
            "not_available": 1,
            "failures": [{"series_id": "US_CPI", "type": "ActualProviderError"}],
        }
        with (
            patch("investment_agent.platform.db.postgres.Database.from_config"),
            patch.object(db, "configure"),
            patch.object(db, "seed_catalog"),
            patch.object(watch_releases.etl, "watch_once", return_value=failure),
            patch.object(watch_releases.time, "sleep"),
        ):
            exit_code = watch_releases.main([
                "--poll-attempts", "2", "--poll-interval-seconds", "1",
            ])

        self.assertEqual(exit_code, 1)

    def test_daily_entrypoint_fails_on_one_source_failure(self) -> None:
        summary = {
            "series_tracked": 30,
            "candidate_releases": 1,
            "failure_count": 1,
            "failures": [{"series_id": "KR_CPI", "type": "ActualProviderError"}],
        }
        with (
            patch("investment_agent.platform.db.postgres.Database.from_config"),
            patch.object(db, "configure"),
            patch.object(db, "seed_catalog"),
            patch.object(etl, "run_daily", return_value=summary),
            patch.object(daily, "notify_ops"),
        ):
            exit_code = daily.main([])

        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
