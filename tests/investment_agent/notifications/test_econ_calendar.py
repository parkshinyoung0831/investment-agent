"""경제 발표 알림 — 발표 하나가 묶음 전송과 반복 실행을 거쳐도 사람에게 한 번 닿는다."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from investment_agent.notifications.econ_calendar import db as store
from investment_agent.notifications.econ_calendar import run as release_run
from tests.investment_agent.notifications.fakes import memory_context

NOW = datetime(2026, 9, 13, 13, 0, tzinfo=timezone.utc)
SERIES = ("US_CPI", "US_CORE_CPI", "US_INITIAL_CLAIMS", "US_CONTINUING_CLAIMS", "US_RETAIL_SALES", "US_PPI")


def _row(series_id: str, *, first_actual_at: datetime | None = None, **extra) -> dict:
    return {
        "event_key": f"{series_id}:2026-08-01", "series_id": series_id, "series_name_ko": series_id,
        "category": "inflation", "status": "released", "unit": "%", "ref_period": "2026-08-01",
        "first_actual_value": 1.5, "first_actual_at": (first_actual_at or NOW - timedelta(hours=1)).isoformat(),
        **extra,
    }


class LoadReleasedTest(unittest.TestCase):
    def _load(self, rows, event_keys=None):
        reader = SimpleNamespace(read=lambda *_a, **_k: SimpleNamespace(status="ok", rows=rows))
        with patch.object(store, "ReportingQueries", return_value=reader):
            return store.load_released(object(), event_keys, now=NOW)

    def test_only_recent_confirmed_first_actuals_are_candidates(self) -> None:
        rows = [
            _row("US_CPI"),
            _row("US_PPI", status="scheduled"),
            _row("US_GDP", first_actual_value=None),
            _row("US_NFP", first_actual_at=NOW - timedelta(days=30)),
        ]

        self.assertEqual([row["series_id"] for row in self._load(rows)], ["US_CPI"])
        self.assertEqual(self._load(rows, ["US_PPI:2026-08-01"]), [])
        self.assertEqual(self._load(rows, []), [])

    def test_an_unavailable_reader_fails_instead_of_looking_empty(self) -> None:
        reader = SimpleNamespace(read=lambda *_a, **_k: SimpleNamespace(status="error", rows=[]))
        with patch.object(store, "ReportingQueries", return_value=reader), self.assertRaises(RuntimeError):
            store.load_released(object(), now=NOW)


class ReleaseNoticeTest(unittest.TestCase):
    def test_identity_is_the_series_and_its_reference_period(self) -> None:
        notice, = release_run.notices([_row("US_CPI")])

        self.assertEqual(notice.key, ("US_CPI", "2026-08-01"))
        self.assertEqual(notice.fact_at, NOW - timedelta(hours=1))

    def test_a_malformed_event_key_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            release_run.notices([{**_row("US_CPI"), "event_key": "not-a-key"}])


class ReleasePublishTest(unittest.TestCase):
    def _run(self, rows, context) -> int:
        with (
            patch.object(release_run, "load_config", return_value=None),
            patch.object(release_run, "configured_database", return_value=None),
            patch.object(release_run.store, "load_released", return_value=rows),
            patch.object(release_run, "discord_target", return_value="123"),
            patch("investment_agent.notifications.econ_calendar.embeds.build",
                  side_effect=lambda batch: {"description": ",".join(r["series_id"] for r in batch)}),
        ):
            return release_run.run(context=context)

    def test_each_release_reaches_people_once_across_batches_and_repeated_runs(self) -> None:
        context, _ledger, channel = memory_context()
        rows = [_row(series) for series in SERIES]

        first = self._run(rows, context)
        repeated = [self._run(list(reversed(rows)), context) for _ in range(4)]

        self.assertEqual(first, 2)
        delivered = [s for m in channel.created for s in m["message"]["embeds"][0]["description"].split(",")]
        self.assertCountEqual(delivered, SERIES)
        self.assertEqual([len(m["message"]["embeds"][0]["description"].split(",")) for m in channel.created], [5, 1])
        self.assertEqual(repeated, [0, 0, 0, 0])

    def test_nothing_released_sends_nothing(self) -> None:
        context, _ledger, channel = memory_context()

        self.assertEqual(self._run([], context), 0)
        self.assertEqual(channel.created, [])


if __name__ == "__main__":
    unittest.main()
