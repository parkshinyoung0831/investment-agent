"""개명된 과거 멤버가 재현 유니버스에서 현재 표기로 풀리는가 — 옛 표기는 가격과 이어지지 않는다."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from investment_agent.data.universe.domain.ticker_renames import current_symbols
from investment_agent.research.datasets.universe import members_over_window, research_universe


class _Repository:
    def current_tracked_tickers(self):
        return ["AAPL"]

    def historical_sp500_membership(self, *, start_date, end_date):
        return [{"effective_date": "2022-01-03", "symbols": ["AAPL", "FLT", "DISCA", "DISCK", "GPS"]}]


class TickerRenameTest(unittest.TestCase):
    def test_old_symbols_become_current_and_two_share_classes_of_one_company_collapse(self):
        self.assertEqual(["AAPL", "CPAY", "GAP", "WBD"], current_symbols(["AAPL", "flt", "DISCA", "DISCK", "GPS"]))

    def test_replay_universe_uses_current_symbols(self):
        members = research_universe(_Repository(), as_of_at=datetime(2022, 1, 5, 21, tzinfo=timezone.utc),
                                    source_kind="historical_replay")
        self.assertEqual(["AAPL", "CPAY", "GAP", "WBD"], members)
        self.assertNotIn("FLT", members_over_window(_Repository(), start=datetime(2022, 1, 1).date(),
                                                    end=datetime(2022, 2, 1).date()))


if __name__ == "__main__":
    unittest.main()
