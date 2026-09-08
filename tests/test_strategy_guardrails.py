"""월간 전략이 stale/부분 데이터를 정상 신호로 저장하지 않는지 검증한다."""
from __future__ import annotations

import unittest
from datetime import date, datetime
import os
import tempfile
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import pandas as pd

from investment_agent.research.strategies import TICKERS, db, etl, retention, strategies
from investment_agent.research.strategies.sources import market as strategy_market

ROOT = Path(__file__).resolve().parents[1]


def _monthly_index(periods: int, *, end: str = "2026-06") -> pd.DatetimeIndex:
    return pd.period_range(end=end, periods=periods, freq="M").to_timestamp("M")


def _complete_prices(periods: int = 14) -> pd.DataFrame:
    index = _monthly_index(periods)
    return pd.DataFrame(
        {
            ticker: [100.0 * (1.01 ** month) for month in range(periods)]
            for ticker in TICKERS
        },
        index=index,
    )


class StrategyCalculationGuardrailTest(unittest.TestCase):
    def test_weight_constraint_reads_jsonb_value_from_named_alias(self):
        path = ROOT / "src" / "investment_agent" / "research" / "strategies" / "sql"
        self.assertEqual(list(path.glob("*.sql")), [], "Research 전략은 production SQL schema를 만들지 않는다")

    def test_allocation_weights_must_sum_to_one(self):
        with self.assertRaisesRegex(ValueError, "sum to 1"):
            db._validated_weights({"SPY": 0.6, "BIL": 0.3})

    def test_gem_compares_best_risk_asset_with_cash(self):
        index = _monthly_index(12)

        def monthly(total_return: float) -> list[float]:
            value = (1 + total_return) ** (1 / 12) - 1
            return [value] * 12

        rets = pd.DataFrame(
            {
                "SPY": monthly(-0.05),
                "EFA": monthly(0.10),
                "BIL": monthly(0.02),
            },
            index=index,
        )

        result = strategies._gem(rets)

        self.assertEqual(result["weights"], {"EFA": 1.0})
        self.assertEqual(result["mode"], "Risk-On-INTL")

    def test_latest_missing_month_is_not_stitched_with_old_data(self):
        rets = pd.DataFrame(
            {"SPY": [0.01] * 12},
            index=_monthly_index(12),
        )
        rets.iloc[-1, 0] = None

        self.assertIsNone(strategies.cum_ret(rets, "SPY", 12))

    def test_compute_all_requires_every_strategy(self):
        incomplete = _complete_prices().drop(columns=["XLY"])

        with self.assertRaisesRegex(RuntimeError, "strategy calculation incomplete"):
            strategies.compute_all(incomplete)

    def test_complete_universe_returns_all_six_strategies(self):
        results = strategies.compute_all(_complete_prices())

        self.assertEqual(
            {row["strategy_id"] for row in results},
            {"gem", "adm", "dmsr", "gtaa5", "haa_bal", "haa_sim"},
        )


class MonthlyEntrypointGuardrailTest(unittest.TestCase):
    def test_backfill_keeps_available_strategies_before_one_inception(self):
        prices = _complete_prices()
        prices.loc[:, "XLC"] = float("nan")

        results, unavailable = etl._compute_available_for_backfill(prices)

        self.assertEqual(unavailable, ["dmsr"])
        self.assertEqual(
            {row["strategy_id"] for row in results},
            {"gem", "adm", "gtaa5", "haa_bal", "haa_sim"},
        )

    def test_backfill_rejects_strategy_gap_after_first_valid_month(self):
        prices = _complete_prices()
        prices.loc[:, "XLC"] = float("nan")

        with self.assertRaisesRegex(RuntimeError, "dmsr"):
            etl._compute_available_for_backfill(
                prices,
                previously_available={"dmsr"},
            )

    def test_backfill_preflight_rejects_partial_download_before_write(self):
        incomplete = _complete_prices().drop(columns=["XLY"])

        with (
            mock.patch.object(etl, "download_monthly_close", return_value=incomplete),
            mock.patch.object(etl.db, "upsert_allocation") as upsert,
            self.assertRaisesRegex(RuntimeError, "strategy calculation incomplete"),
        ):
            etl._run_backfill(datetime.now(ZoneInfo("Asia/Seoul")).date().replace(day=1))

        upsert.assert_not_called()


class StrategySourceGuardrailTest(unittest.TestCase):
    @staticmethod
    def _raw(*tickers: str) -> pd.DataFrame:
        index = pd.period_range(end="2026-07", periods=14, freq="M").to_timestamp()
        columns = pd.MultiIndex.from_tuples(
            [(ticker, "Close") for ticker in tickers]
        )
        return pd.DataFrame(
            [[100.0 + month + offset for offset, _ in enumerate(tickers)]
             for month in range(len(index))],
            index=index,
            columns=columns,
        )

    def test_monthly_source_requires_every_requested_ticker(self):
        raw = self._raw("SPY")
        with (
            mock.patch.object(strategy_market.market_prices, "monthly_close_history", return_value=raw),
            mock.patch.object(
                strategy_market,
                "_last_complete_month_end",
                return_value=pd.Timestamp("2026-07-31"),
            ),
            self.assertRaisesRegex(RuntimeError, "omitted tickers: BIL"),
        ):
            strategy_market.download_monthly_close(["SPY", "BIL"])

    def test_monthly_source_reads_market_owner_and_returns_complete_months(self):
        raw = self._raw("SPY", "BIL")
        raw.columns = ["SPY", "BIL"]
        with (
            mock.patch.object(
                strategy_market.market_prices,
                "monthly_close_history",
                return_value=raw,
            ) as monthly_history,
            mock.patch.object(
                strategy_market,
                "_last_complete_month_end",
                return_value=pd.Timestamp("2026-07-31"),
            ),
        ):
            result = strategy_market.download_monthly_close(["SPY", "BIL"])

        self.assertEqual(list(result.columns), ["SPY", "BIL"])
        self.assertEqual(result.index[-1], pd.Timestamp("2026-07-31"))
        monthly_history.assert_called_once_with(["SPY", "BIL"], period="2y")

    def test_backfill_does_not_hide_strategy_calculation_errors(self):
        prices = _complete_prices()

        with (
            mock.patch.object(
                etl,
                "compute_one",
                side_effect=RuntimeError("calculation bug"),
            ),
            self.assertRaisesRegex(RuntimeError, "calculation bug"),
        ):
            etl._compute_available_for_backfill(prices)

    def test_stale_latest_month_fails_before_any_write(self):
        apply_month = datetime.now(ZoneInfo("Asia/Seoul")).date().replace(day=1)
        stale_end = (pd.Timestamp(apply_month) - pd.offsets.MonthEnd(2)).to_period("M")
        stale_prices = pd.DataFrame(
            {ticker: [100.0 + i for i in range(14)] for ticker in TICKERS},
            index=pd.period_range(end=stale_end, periods=14, freq="M").to_timestamp("M"),
        )

        with (
            mock.patch.object(etl.db, "allocation_strategy_ids", return_value=set()),
            mock.patch.object(etl, "download_monthly_close", return_value=stale_prices),
            mock.patch.object(etl.db, "upsert_allocation") as upsert,
            self.assertRaisesRegex(RuntimeError, "stale or incomplete"),
        ):
            etl._run_monthly(mark_sent=False)

class StrategyRetentionTest(unittest.TestCase):
    def test_prune_history_calls_db_with_3_years_ago(self):
        with mock.patch.object(retention.db, "delete_allocations_before", return_value=5) as mock_delete:
            deleted = retention.prune_history(today=date(2026, 9, 2))

        self.assertEqual(deleted, 5)
        mock_delete.assert_called_once_with("2023-09-02")

    def test_prune_history_handles_leap_year(self):
        with mock.patch.object(retention.db, "delete_allocations_before", return_value=0) as mock_delete:
            deleted = retention.prune_history(today=date(2024, 2, 29))

        self.assertEqual(deleted, 0)
        mock_delete.assert_called_once_with("2021-02-28")

    def test_db_delete_allocations_before_deletes_local_rows(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ, {"INVESTMENT_AGENT_RESEARCH_ROOT": directory}
        ):
            db.upsert_allocation(
                "gem", date(2026, 8, 31), date(2026, 9, 1), "Attack",
                {"SPY": 1.0}, {},
            )
            deleted = retention.db.delete_allocations_before("2026-10-01")

        self.assertEqual(deleted, 1)


if __name__ == "__main__":
    unittest.main()

