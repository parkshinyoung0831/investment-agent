"""System·My Portfolio 비교 read model: 따라간 정도와 같은 기간의 성과 차이만 원장 값으로 만든다."""
from __future__ import annotations

import unittest

from investment_agent.reporting.services.investment import build_system_portfolio_read_model

NAV = [
    {"trade_date": "2026-09-09", "nav": 100.0, "benchmark_nav": 100.0, "daily_return": 0.0, "turnover": 0.5,
     "cost": 0.0, "weights": {"AAA": 0.5, "CASH": 0.5}},
    {"trade_date": "2026-09-10", "nav": 110.0, "benchmark_nav": 101.0, "daily_return": 0.1, "turnover": 0.0,
     "cost": 0.0, "weights": {"AAA": 0.6, "CASH": 0.4}},
]


class SystemPortfolioReadModelTest(unittest.TestCase):
    def test_follow_ratio_and_differences_come_from_the_latest_snapshot(self):
        model = build_system_portfolio_read_model(
            nav_rows=NAV, target_rows=[],
            account={"captured_at": "2026-09-10T20:00:00+00:00", "cash": 100.0,
                     "holdings": [{"ticker": "BBB", "quantity": 1, "market_price": 100.0}]},
        )
        mine = model["my"]
        self.assertAlmostEqual(mine["follow_ratio"], 1 - 0.5 * (0.6 + 0.5 + 0.1))
        self.assertEqual({row["ticker"] for row in mine["differences"]}, {"AAA", "BBB", "CASH"})
        self.assertAlmostEqual(model["system"]["summary"]["total_return"], 0.10)

    def test_return_gap_needs_a_time_weighted_account_return(self):
        no_twr = build_system_portfolio_read_model(nav_rows=NAV, target_rows=[], account={"cash": 1.0})
        self.assertNotIn("return_gap", no_twr["my"])
        report = {"report_kind": "daily", "as_of_at": "2026-09-10T21:00:00+00:00",
                  "nav": {"cumulative_return": 0.04, "periods": [{"start_at": "2026-09-09T21:00:00+00:00"}]}}
        model = build_system_portfolio_read_model(nav_rows=NAV, target_rows=[], account={"cash": 1.0},
                                                  performance_reports=[report])
        self.assertAlmostEqual(model["my"]["system_return"], 0.10)
        self.assertAlmostEqual(model["my"]["return_gap"], -0.06)


if __name__ == "__main__":
    unittest.main()
