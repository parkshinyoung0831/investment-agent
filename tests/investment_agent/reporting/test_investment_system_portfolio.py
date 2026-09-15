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

    def test_real_is_compared_with_the_approved_target_and_shows_execution_state(self):
        targets = [
            {"target_id": "t2", "decided_at": "2026-09-10T22:00:00+00:00", "is_approved": False, "weights": {"CCC": 0.5, "CASH": 0.5},
             "detail": {"rebalance_trigger": "scheduled"}},
            {"target_id": "t1", "decided_at": "2026-09-08T22:00:00+00:00", "is_approved": True, "weights": {"AAA": 0.5, "CASH": 0.5},
             "detail": {"rebalance_trigger": "initial"}},
        ]
        model = build_system_portfolio_read_model(
            nav_rows=NAV, target_rows=targets,
            account={"cash": 50.0, "holdings": [{"ticker": "AAA", "market_value": 50.0}]},
            approvals=[{"status": "pending"}, {"status": "rejected"}],
            orders=[{"status": "submitted"}, {"status": "filled"}],
        )
        system = model["system"]
        # 목표는 최신 **승인** 목표, 현재비중은 가격으로 drift된 비중이다.
        self.assertEqual(system["target_weights"], {"AAA": 0.5, "CASH": 0.5})
        table = {row["ticker"]: row for row in system["weights_table"]}
        self.assertEqual((table["AAA"]["target_weight"], table["AAA"]["current_weight"]), (0.5, 0.6))
        self.assertEqual(table["CASH"]["current_weight"], 0.4)
        self.assertEqual(system["rebalance_trigger"], "scheduled")
        mine = model["my"]
        self.assertAlmostEqual(mine["follow_ratio"], 1.0)  # 실계좌는 drift가 아니라 목표를 따른다
        self.assertEqual((mine["pending_approval_count"], mine["open_order_count"]), (1, 1))

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
