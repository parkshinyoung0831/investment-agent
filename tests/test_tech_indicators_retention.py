"""기술지표 730일 보존 정책 계약."""
from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd

from investment_agent.operations.backfill import BackfillWindow
from investment_agent.research.features import (
    BACKFILL_WARMUP_TRADING_DAYS,
    BACKFILL_YEARS,
    etl,
    retention,
)
from investment_agent.research.features import prices as price_loader
from investment_agent.research.features import backfill


class TechIndicatorsRetentionTest(unittest.TestCase):
    def test_backfill_prunes_after_indicator_write(self):
        window = BackfillWindow(start=date(2024, 8, 18), end=date(2026, 8, 18))
        order: list[str] = []
        with (
            patch.object(backfill, "resolve_backfill_window", return_value=window),
            patch("investment_agent.research.features.etl.run") as run,
            patch(
                "investment_agent.research.features.retention.prune_history",
                side_effect=lambda **_kwargs: order.append("prune"),
            ) as prune,
        ):
            run.side_effect = lambda **_kwargs: order.append("run")
            result = backfill.main([])

        self.assertEqual(result, 0)
        self.assertEqual(order, ["run", "prune"])
        expected_rolling_days = window.trading_days + BACKFILL_WARMUP_TRADING_DAYS
        run.assert_called_once_with(
            rolling_days=expected_rolling_days,
            workflow="backfill",
            save_from=window.start,
        )
        prune.assert_called_once_with(today=window.end)

    def test_backfill_write_failure_does_not_run_retention(self):
        window = BackfillWindow(start=date(2024, 8, 18), end=date(2026, 8, 18))
        with (
            patch.object(backfill, "resolve_backfill_window", return_value=window),
            patch(
                "investment_agent.research.features.etl.run",
                side_effect=RuntimeError("run failed"),
            ),
            patch("investment_agent.research.features.retention.prune_history") as prune,
            self.assertRaisesRegex(RuntimeError, "run failed"),
        ):
            backfill.main([])

        prune.assert_not_called()

    def test_history_horizons_are_aligned(self):
        self.assertEqual(BACKFILL_YEARS, 2)
        self.assertGreaterEqual(BACKFILL_WARMUP_TRADING_DAYS, 750)
        self.assertEqual(retention.RETENTION_DAYS, 730)

    def test_backfill_warmup_fills_entire_retention_window_before_write(self):
        end = date(2026, 8, 18)
        cutoff = end - timedelta(days=retention.RETENTION_DAYS)
        warmup_calendar_days = BACKFILL_WARMUP_TRADING_DAYS * 7 // 5 + 30
        dates = pd.bdate_range(cutoff - timedelta(days=warmup_calendar_days), end)
        prices = pd.DataFrame(
            {
                "ticker": ["AAPL"] * len(dates),
                "trade_date": dates.date,
                "close": [100.0 + i for i in range(len(dates))],
                "volume": [1_000] * len(dates),
            }
        )

        with (
            patch.object(etl.db, "latest_market_date", return_value=end.isoformat()),
            patch.object(etl.db, "latest_indicator_date", return_value=None),
            patch.object(etl.db, "latest_indicator_write_at", return_value=None),
            patch.object(etl.db, "earliest_market_change_since", return_value=None),
            patch.object(etl, "load_prices", return_value=prices) as load_prices,
            patch.object(
                etl.db,
                "upsert_indicators",
                side_effect=lambda frame: len(frame),
            ) as upsert,
        ):
            rolling_days = len(pd.bdate_range(cutoff, end)) + BACKFILL_WARMUP_TRADING_DAYS
            written = etl.run(
                rolling_days=rolling_days,
                workflow="backfill",
                save_from=cutoff,
            )

        stored = upsert.call_args.args[0]
        first_available = min(day for day in dates.date if day >= cutoff)
        self.assertEqual(written, len(stored))
        self.assertGreater(len(stored), 0)
        self.assertEqual(stored["trade_date"].min(), first_available)
        self.assertTrue(
            stored[["rsi14", "macd", "macd_signal"]].notna().all().all()
        )
        load_prices.assert_called_once_with(rolling_days=rolling_days, end_date=end)

    def test_backfill_source_window_includes_calendar_warmup(self):
        end = date(2026, 8, 18)
        cutoff = end - timedelta(days=retention.RETENTION_DAYS)
        with patch.object(
            price_loader.db,
            "load_market_prices_since",
            return_value=[],
        ) as load:
            rolling_days = len(pd.bdate_range(cutoff, end)) + BACKFILL_WARMUP_TRADING_DAYS
            price_loader.load_prices(rolling_days=rolling_days, end_date=end)

        source_start = date.fromisoformat(load.call_args.args[0])
        required_calendar_days = BACKFILL_WARMUP_TRADING_DAYS * 7 // 5 + 15
        self.assertGreaterEqual(
            (cutoff - source_start).days,
            required_calendar_days,
        )

    def test_deletes_rows_older_than_730_days(self):
        with patch.object(retention.db, "delete_before", return_value=2) as delete:
            deleted = retention.prune_history(today=date(2026, 8, 18))

        self.assertEqual(deleted, 2)
        delete.assert_called_once_with("2024-08-18")


if __name__ == "__main__":
    unittest.main()
