"""MARKET 주식분할 보정과 corporate actions 병합 회귀 테스트."""
from __future__ import annotations

import unittest
from pathlib import Path

from investment_agent.data.market.domain.actions import merge_corporate_actions
from investment_agent.data.market.domain.price_repair import (
    is_split_ratio,
    normalize_split_adjusted_prices,
    validate_repaired_prices,
)


class SplitRatioTest(unittest.TestCase):
    def test_forward_and_reverse_are_actions(self):
        self.assertTrue(is_split_ratio(10))
        self.assertTrue(is_split_ratio(1 / 3))
        self.assertFalse(is_split_ratio(1))
        self.assertFalse(is_split_ratio(0))
        self.assertFalse(is_split_ratio(None))


class PriceRepairValidationTest(unittest.TestCase):
    def test_normalizes_mixed_basis_before_forward_split(self):
        rows = [
            {"ticker": "MNST", "trade_date": "2026-08-05", "open": 94.0, "high": 95.0, "low": 93.0, "close": 94.46, "adj_close": 90.0, "volume": 1_000, "source": "yfinance"},
            {"ticker": "MNST", "trade_date": "2026-08-06", "open": 47.0, "high": 48.0, "low": 46.0, "close": 47.08, "adj_close": 44.9, "volume": 2_000, "source": "yfinance"},
            {"ticker": "MNST", "trade_date": "2026-08-07", "open": 90.0, "high": 91.0, "low": 89.0, "close": 90.36, "adj_close": 86.0, "volume": 1_100, "source": "yfinance"},
            {"ticker": "MNST", "trade_date": "2026-08-11", "open": 45.0, "high": 46.0, "low": 44.0, "close": 45.53, "adj_close": 43.4, "volume": 2_200, "split_ratio": 2.0, "source": "yfinance"},
        ]

        repaired = normalize_split_adjusted_prices(rows)

        self.assertAlmostEqual(repaired[0]["close"], 47.23)
        self.assertAlmostEqual(repaired[0]["adj_close"], 45.0)
        self.assertAlmostEqual(repaired[1]["close"], 47.08)
        self.assertAlmostEqual(repaired[2]["close"], 45.18)
        self.assertEqual(repaired[0]["volume"], 2_000)
        self.assertEqual(repaired[1]["volume"], 2_000)
        self.assertEqual(repaired[2]["source"], "yfinance_repaired")
        validate_repaired_prices(
            repaired,
            [{"action_date": "2026-08-11", "split_ratio": 2.0}],
        )

    def test_preserves_adj_close_when_it_is_already_on_adjusted_basis(self):
        rows = [
            {
                "ticker": "TEST", "trade_date": "2026-08-07",
                "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
                "adj_close": 49.0, "volume": 1_000, "source": "yfinance",
            },
            {
                "ticker": "TEST", "trade_date": "2026-08-11",
                "open": 50.0, "high": 51.0, "low": 49.0, "close": 50.0,
                "adj_close": 49.1, "volume": 2_000, "split_ratio": 2.0,
                "source": "yfinance",
            },
        ]

        repaired = normalize_split_adjusted_prices(rows)

        self.assertEqual(repaired[0]["close"], 50.0)
        self.assertEqual(repaired[0]["adj_close"], 49.0)

    def test_leaves_already_adjusted_history_unchanged(self):
        rows = [
            {"ticker": "NVDA", "trade_date": "2024-06-07", "open": 120.0, "high": 122.0, "low": 119.0, "close": 121.0, "volume": 100, "source": "yfinance"},
            {"ticker": "NVDA", "trade_date": "2024-06-10", "open": 121.0, "high": 123.0, "low": 120.0, "close": 122.0, "volume": 110, "split_ratio": 10.0, "source": "yfinance"},
        ]

        self.assertEqual(normalize_split_adjusted_prices(rows), rows)

    def test_accepts_continuous_adjusted_prices(self):
        validate_repaired_prices(
            [
                {"trade_date": "2026-06-23", "close": 140},
                {"trade_date": "2026-06-24", "close": 138, "split_ratio": 1 / 3},
            ],
            [{"action_date": "2026-06-24", "split_ratio": 1 / 3}],
        )

    def test_accepts_continuous_price_for_small_distribution_ratio(self):
        validate_repaired_prices(
            [
                {"trade_date": "2019-02-07", "close": 60.58},
                {"trade_date": "2019-02-08", "close": 59.15, "split_ratio": 1.275},
            ],
            [{"action_date": "2019-02-08", "split_ratio": 1.275}],
        )

    def test_rejects_unadjusted_reverse_split_jump(self):
        with self.assertRaisesRegex(ValueError, "split discontinuity"):
            validate_repaired_prices(
                [
                    {"trade_date": "2026-06-23", "close": 46},
                    {"trade_date": "2026-06-24", "close": 138, "split_ratio": 1 / 3},
                ],
                [{"action_date": "2026-06-24", "split_ratio": 1 / 3}],
            )


class SplitSqlContractTest(unittest.TestCase):
    def test_schema_has_split_events_table(self):
        sql = Path("db/postgres/v1/20_market.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS market.split_events", sql)
        self.assertIn("CHECK (split_ratio > 0 AND split_ratio <> 1)", sql)
        self.assertNotIn("split_from", sql)
        self.assertNotIn("split_to", sql)
        self.assertNotIn("market.split_backfill_queue", sql)


class MarketActionMergeTest(unittest.TestCase):
    def test_merges_without_creating_action_only_price_rows(self) -> None:
        rows = merge_corporate_actions(
            [{"ticker": "TEST", "trade_date": "2026-08-01", "close": 10}],
            [
                {"ticker": "TEST", "ex_date": "2026-08-01", "div_amount": 0.2},
                {"ticker": "TEST", "ex_date": "2026-08-02", "div_amount": 0.3},
            ],
            [{"ticker": "TEST", "action_date": "2026-08-01", "split_ratio": 2}],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["div_amount"], 0.2)
        self.assertEqual(rows[0]["split_ratio"], 2)


if __name__ == "__main__":
    unittest.main()


