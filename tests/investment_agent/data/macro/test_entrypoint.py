"""macro v1 진입점의 범위·모드·종료코드 계약을 검증한다."""
from __future__ import annotations

from datetime import date, timedelta
import unittest
from unittest import mock

import pandas as pd

from investment_agent.data.macro.application.refresh_market_state import MacroRefreshResult
from investment_agent.data.macro.commands import macro_refresh as run
from investment_agent.operations.runtime import EXIT_FAILED, EXIT_OK, EXIT_PARTIAL

_TODAY = date(2026, 8, 27)


def _indicator(series_id: str = "SPY") -> dict:
    return {
        "series_id": series_id,
        "name_ko": series_id,
        "source": "yfinance",
        "source_params": {"ticker": "^GSPC"},
        "series_kind": "price",
        "frequency": "daily",
    }


def _series(*days: int) -> pd.Series:
    index = pd.to_datetime([_TODAY - timedelta(days=day) for day in days])
    return pd.Series([100.0 + day for day in days], index=index)


class MacroTransformTest(unittest.TestCase):
    def test_daily_overlap_cutoff(self):
        self.assertEqual(
            run._incremental_cutoff("daily", _TODAY, daily_lookback_days=14),
            date(2026, 8, 13),
        )

    def test_rows_are_limited_to_inclusive_overlap(self):
        rows = run._rows_for_series(
            "SPY", _series(20, 14, 13, 0, -1), cutoff=date(2026, 8, 13), end=_TODAY
        )
        self.assertEqual(
            [(row["series_id"], row["obs_date"]) for row in rows],
            [("SPY", "2026-08-13"), ("SPY", "2026-08-14"), ("SPY", "2026-08-27")],
        )


class MacroRunTest(unittest.TestCase):
    def _run(self, result: MacroRefreshResult, argv: list[str], catalog=None):
        db = mock.Mock()
        with (
            mock.patch.object(run, "_kst_today", return_value=_TODAY),
            mock.patch.object(run.Database, "from_config", return_value=db),
            mock.patch.object(run.MacroRepository, "market_catalog", return_value=catalog or [_indicator()]),
            mock.patch.object(run, "refresh_macro", return_value=result) as refresh,
            mock.patch.object(run, "notify_ops") as notify,
        ):
            code = run.main(argv)
        return code, refresh, notify

    def test_dry_run_uses_v1_writer_without_persisting(self):
        code, refresh, notify = self._run(
            MacroRefreshResult(1, 2, ()), ["--dry-run", "--series", "SPY"]
        )
        self.assertEqual(EXIT_OK, code)
        self.assertFalse(notify.called)
        self.assertFalse(refresh.call_args.kwargs["persist"])
        self.assertEqual(["SPY"], [row["series_id"] for row in refresh.call_args.kwargs["catalog"]])

    def test_backfill_starts_before_the_requested_save_date(self):
        code, refresh, _ = self._run(
            MacroRefreshResult(1, 1, ()),
            ["--backfill-from", "2026-08-20", "--lookback-days", "5", "--series", "SPY"],
        )
        self.assertEqual(EXIT_OK, code)
        self.assertEqual(date(2026, 8, 15), refresh.call_args.kwargs["start"])
        self.assertEqual(_TODAY, refresh.call_args.kwargs["end"])

    def test_partial_result_is_reported_without_becoming_success(self):
        code, _, notify = self._run(
            MacroRefreshResult(2, 1, ({"series_id": "QQQ", "error": "timeout"},)),
            ["--series", "SPY"],
            catalog=[_indicator("SPY"), _indicator("QQQ")],
        )
        self.assertEqual(EXIT_PARTIAL, code)
        self.assertNotEqual(EXIT_OK, code)
        notify.assert_called_once()

    def test_catalog_failure_is_failed(self):
        db = mock.Mock()
        with (
            mock.patch.object(run, "_kst_today", return_value=_TODAY),
            mock.patch.object(run.Database, "from_config", return_value=db),
            mock.patch.object(run.MacroRepository, "market_catalog", side_effect=RuntimeError("offline")),
            mock.patch.object(run, "notify_ops") as notify,
        ):
            code = run.main([])
        self.assertEqual(EXIT_FAILED, code)
        notify.assert_called_once()


if __name__ == "__main__":
    unittest.main()
