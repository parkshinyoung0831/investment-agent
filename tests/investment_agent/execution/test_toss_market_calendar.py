from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from investment_agent.execution.brokers.toss.client import (
    TossExecutionError,
    fetch_us_regular_session,
)


class TossMarketCalendarTest(unittest.TestCase):

    @patch("investment_agent.execution.brokers.toss.client._get")
    def test_parses_official_early_close_session(self, get):
        get.return_value = {"result": {"today": {
            "date": "2026-11-27",
            "dayMarket": None,
            "preMarket": {},
            "regularMarket": {
                "startTime": "2026-11-27T23:30:00+09:00",
                "endTime": "2026-11-28T03:00:00+09:00",
            },
            "afterMarket": {},
        }}}
        value = fetch_us_regular_session(date(2026, 11, 27))
        self.assertEqual(value.market_date, date(2026, 11, 27))
        self.assertLess(value.start_at, value.end_at)
        self.assertEqual(get.call_args.kwargs["params"]["date"], "2026-11-27")

    @patch("investment_agent.execution.brokers.toss.client._get")
    def test_holiday_returns_none(self, get):
        get.return_value = {"result": {"today": {
            "date": "2026-07-03",
            "dayMarket": None,
            "preMarket": None,
            "regularMarket": None,
            "afterMarket": None,
        }}}
        self.assertIsNone(fetch_us_regular_session(date(2026, 7, 3)))

    @patch("investment_agent.execution.brokers.toss.client._get")
    def test_mismatched_date_fails_closed(self, get):
        get.return_value = {"result": {"today": {
            "date": "2026-07-04", "regularMarket": None,
        }}}
        with self.assertRaisesRegex(TossExecutionError, "요청일과 다릅니다"):
            fetch_us_regular_session(date(2026, 7, 3))


if __name__ == "__main__":
    unittest.main()
