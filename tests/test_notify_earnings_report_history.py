from __future__ import annotations

import unittest
from datetime import date, timedelta

from investment_agent.notifications.earnings_report import charts


class HistoricalCardTest(unittest.TestCase):
    def test_health_gauges_exclude_current_ratio(self):
        result = charts.gauges({
            "net_debt_to_ebitda": 1.2,
            "current_ratio": 1.8,
            "altman_z": 3.4,
        })

        self.assertEqual(
            [item["name"] for item in result],
            ["순부채/EBITDA", "Altman Z''"],
        )

    def test_market_context_strictly_excludes_filing_day_and_future_prices(self):
        start = date(2026, 1, 1)
        prices = [
            {
                "trade_date": (start + timedelta(days=index)).isoformat(),
                "close": 100 + index,
                "volume": 1_000 + index,
            }
            for index in range(35)
        ]

        eligible = charts.prices_before_filing(prices, "2026-01-26")
        snapshot = charts.technical_snapshot(eligible)

        self.assertEqual(eligible[-1]["trade_date"], "2026-01-25")
        self.assertEqual(snapshot["close"], 124)
        self.assertEqual(snapshot["high_52w"], 124)

    def test_shareholder_return_is_hidden_without_dividend(self):
        prices = [{"trade_date": "2026-01-02", "close": 100, "div_amount": 0}]

        self.assertIsNone(
            charts.shareholder_return(
                prices,
                [("2025-01-02", 110), ("2026-01-02", 100)],
            )
        )

    def test_dividend_graph_is_available_with_recent_dividends(self):
        prices = [
            {"trade_date": "2025-03-15", "close": 100, "div_amount": .5},
            {"trade_date": "2025-06-15", "close": 100, "div_amount": .5},
            {"trade_date": "2026-01-02", "close": 100, "div_amount": 0},
        ]

        trend = charts.dividend_trend(prices)

        self.assertIsNotNone(trend)
        self.assertEqual(len(trend["svg"]["bars"]), 2)
        self.assertEqual(trend["svg"]["bars"][0]["label"], "'25.03")
        self.assertEqual(trend["svg"]["bars"][1]["label"], "'25.06")
        self.assertEqual(trend["latest_dps"], "$0.50")
        self.assertTrue(trend["svg"]["line_points"])

    def test_dividend_trend_cagr_multi_year(self):
        prices = [
            {"trade_date": "2023-08-10", "close": 100, "div_amount": .25},
            {"trade_date": "2023-11-10", "close": 100, "div_amount": .25},
            {"trade_date": "2024-02-10", "close": 100, "div_amount": .26},
            {"trade_date": "2024-05-10", "close": 100, "div_amount": .26},
            {"trade_date": "2024-08-10", "close": 100, "div_amount": .26},
            {"trade_date": "2024-11-10", "close": 100, "div_amount": .26},
            {"trade_date": "2025-02-10", "close": 100, "div_amount": .27},
        ]

        trend = charts.dividend_trend(prices)

        self.assertIsNotNone(trend)
        self.assertEqual(len(trend["svg"]["bars"]), 7)
        self.assertEqual(trend["svg"]["bars"][0]["label"], "'23.08")
        self.assertEqual(trend["svg"]["bars"][-1]["label"], "'25.02")
        self.assertIsNotNone(trend["cagr"])

    def test_quarter_labels_are_thinned_so_they_do_not_touch(self):
        rows = [
            {
                "ticker": "T", "period_end": f"202{3 + index // 4}-0{index % 4 + 1}-28",
                "fiscal_year": 2023 + index // 4, "fiscal_period": f"Q{index % 4 + 1}",
                "revenue": 100 + index, "operating_income_loss": 30, "net_income": 20,
            }
            for index in range(13)
        ]

        bars = charts.combo(rows, [])["financials"]["bars"]

        self.assertEqual(sum(bar["show"] for bar in bars), 5)
        self.assertTrue(bars[-1]["show"])   # 이번 분기는 언제나 찍는다

    def test_cashflow_is_drawn_by_quarter_not_by_year(self):
        """연 단위는 점이 다섯 개뿐이라 계절성도 이번 분기 위치도 안 보인다."""
        rows = [
            {
                "fiscal_year": 2023 + index // 4,
                "fiscal_period": f"Q{index % 4 + 1}",
                "net_cash_from_operating_activities": 100 + index,
                "net_cash_from_investing_activities": -40,
                "net_cash_from_financing_activities": -20,
            }
            for index in range(13)
        ]
        result = charts.cashflow_quarters(rows)

        self.assertIsNotNone(result)
        self.assertEqual(len(result["operating"]["dots"]), 13)
        self.assertTrue(result["investing"]["points"])
        self.assertTrue(result["financing"]["points"])
        # 13개를 다 찍으면 x라벨이 겹친다 — 양끝과 3분기마다만.
        self.assertEqual([label["label"] for label in result["labels"]],
                         ["Q1·23", "Q4·23", "Q3·24", "Q2·25", "Q1·26"])


if __name__ == "__main__":
    unittest.main()
