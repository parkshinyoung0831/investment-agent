from __future__ import annotations

import unittest

from investment_agent.reporting.readers.dashboard import load_earnings_overview


class DashboardReaderTest(unittest.TestCase):
    def test_earnings_overview_rejects_invalid_ticker_before_connection(self):
        result = load_earnings_overview("not a ticker")
        self.assertEqual("blocked", result.status)


if __name__ == "__main__":
    unittest.main()
