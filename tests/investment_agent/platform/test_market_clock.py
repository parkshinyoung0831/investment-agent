from __future__ import annotations

import unittest
from datetime import datetime, timezone

from investment_agent.platform.clock import completed_us_daily_bar_cutoff, us_market_today


class UsMarketClockTests(unittest.TestCase):
    def test_uses_new_york_date_at_utc_boundary(self) -> None:
        now = datetime(2026, 8, 28, 0, 30, tzinfo=timezone.utc)

        self.assertEqual(us_market_today(now).isoformat(), "2026-08-27")

    def test_rejects_naive_datetime(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            us_market_today(datetime(2026, 8, 28, 0, 30))  # noqa: DTZ001

    def test_daily_bar_cutoff_excludes_open_session(self) -> None:
        during_regular_session = datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc)

        self.assertEqual(
            completed_us_daily_bar_cutoff(during_regular_session).isoformat(),
            "2026-08-27",
        )

    def test_daily_bar_cutoff_allows_post_close_revision_window(self) -> None:
        after_finalization = datetime(2026, 8, 28, 22, 30, tzinfo=timezone.utc)

        self.assertEqual(
            completed_us_daily_bar_cutoff(after_finalization).isoformat(),
            "2026-08-28",
        )


if __name__ == "__main__":
    unittest.main()
