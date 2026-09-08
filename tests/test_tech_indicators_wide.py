"""기술지표가 종목·날짜당 한 행으로 저장되는지 검증한다."""
from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

import pandas as pd

from investment_agent.research.features import db, etl
from investment_agent.research.features.compute import compute_all


class TechnicalIndicatorsWideTest(unittest.TestCase):
    def test_compute_returns_one_row_per_date_after_rsi_warmup(self):
        dates = pd.date_range("2026-01-01", periods=50, freq="D")
        prices = pd.DataFrame(
            {
                "ticker": ["AAPL"] * len(dates),
                "trade_date": dates.date,
                "close": [100.0 + i for i in range(len(dates))],
                "volume": [1000] * len(dates),
            }
        )

        result = compute_all(prices)

        self.assertEqual(
            list(result.columns),
            ["ticker", "trade_date", "rsi14", "macd", "macd_signal"],
        )
        self.assertFalse(result.duplicated(["ticker", "trade_date"]).any())
        self.assertTrue(result["rsi14"].notna().all())
        self.assertTrue(result[["rsi14", "macd", "macd_signal"]].notna().all().all())

    def test_long_warmup_makes_saved_tail_seed_independent(self):
        dates = pd.bdate_range("2020-01-01", periods=1_300)
        prices = pd.DataFrame(
            {
                "ticker": ["AAPL"] * len(dates),
                "trade_date": dates.date,
                "close": [100.0 + i * 0.03 + (i % 17) * 0.2 for i in range(len(dates))],
                "volume": [1000] * len(dates),
            }
        )
        full = compute_all(prices).tail(500).reset_index(drop=True)
        shifted = compute_all(prices.iloc[100:]).tail(500).reset_index(drop=True)

        pd.testing.assert_frame_equal(full, shifted, rtol=1e-12, atol=1e-12)

    def test_changed_rows_compare_all_three_columns_and_nulls(self):
        frame = pd.DataFrame(
            {
                "ticker": ["AAPL", "MSFT", "NVDA"],
                "trade_date": [date(2026, 8, 17)] * 3,
                "rsi14": [55.0, 60.0, 70.0],
                "macd": [1.0, 2.0, float("nan")],
                "macd_signal": [0.9, 1.9, float("nan")],
            }
        )
        existing = {
            ("AAPL", "2026-08-17"): {
                "rsi14": 55.0,
                "macd": 1.0,
                "macd_signal": 0.9,
            },
            ("MSFT", "2026-08-17"): {
                "rsi14": 60.0,
                "macd": 2.1,
                "macd_signal": 1.9,
            },
            ("NVDA", "2026-08-17"): {
                "rsi14": 70.0,
                "macd": None,
                "macd_signal": None,
            },
        }

        changed = db.changed_indicators(frame, existing)

        self.assertEqual(changed["ticker"].tolist(), ["MSFT"])


class TechnicalIndicatorRetryTest(unittest.TestCase):
    def test_old_market_correction_expands_comparison_window(self):
        prices = pd.DataFrame(
            {
                "ticker": ["AAPL", "AAPL"],
                "trade_date": [
                    pd.Timestamp("2026-06-01").date(),
                    pd.Timestamp("2026-07-31").date(),
                ],
                "close": [100.0, 110.0],
                "volume": [1000, 1100],
            }
        )
        indicators = pd.DataFrame(
            {
                "ticker": ["AAPL"],
                "trade_date": [pd.Timestamp("2026-06-15").date()],
                "rsi14": [55.0],
                "macd": [1.2],
                "macd_signal": [1.1],
            }
        )

        with (
            mock.patch.object(etl.db, "latest_market_date", return_value="2026-07-31"),
            mock.patch.object(etl.db, "latest_indicator_date", return_value="2026-07-31"),
            mock.patch.object(
                etl.db,
                "latest_indicator_write_at",
                return_value="2026-08-01T00:00:00+00:00",
            ),
            mock.patch.object(
                etl.db,
                "earliest_market_change_since",
                return_value="2026-06-15",
            ),
            mock.patch.object(etl, "load_prices", return_value=prices),
            mock.patch.object(etl, "compute_all", return_value=indicators),
            mock.patch.object(
                etl.db,
                "existing_indicators_since",
                return_value={},
            ) as existing,
            mock.patch.object(
                etl.db,
                "changed_indicators",
                side_effect=lambda frame, _: frame,
            ),
            mock.patch.object(
                etl.db,
                "upsert_indicators",
                side_effect=lambda frame: len(frame),
            ),
        ):
            written = etl.run()

        existing.assert_called_once_with("2026-06-15")
        self.assertEqual(written, 1)

    def test_empty_market_frame_is_a_failure(self):
        with (
            mock.patch.object(etl.db, "latest_market_date", return_value=None),
            mock.patch.object(etl.db, "latest_indicator_date", return_value=None),
            mock.patch.object(etl, "load_prices", return_value=pd.DataFrame()),
            self.assertRaisesRegex(RuntimeError, "no prices loaded"),
        ):
            etl.run()


if __name__ == "__main__":
    unittest.main()

