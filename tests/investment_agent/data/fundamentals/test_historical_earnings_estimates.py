"""Yahoo 과거 EPS 예상치 재구성 규칙을 네트워크 없이 검증한다."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from investment_agent.data.fundamentals.application.historical_earnings_estimates import (
    HISTORICAL_EPS_SOURCE,
    build_historical_eps_estimates,
)
from investment_agent.data.fundamentals.application.backfill_earnings_estimates import (
    backfill_historical_eps_estimates,
)
from investment_agent.data.fundamentals.infrastructure.yahoo_finance import reported_earnings


def _flash(*, ticker: str = "ADI", filed_at: str = "2026-08-19") -> dict:
    return {
        "ticker": ticker,
        "fiscal_year": 2026,
        "fiscal_period": "Q3",
        "period_end": "2026-08-01",
        "filed_at": filed_at,
        "accession_no": "0000000000-26-000001",
    }


class HistoricalEpsEstimateBuilderTests(unittest.TestCase):
    def test_builds_reconstructed_eps_snapshot_with_exact_fiscal_key(self) -> None:
        batch = build_historical_eps_estimates(
            [_flash()],
            {"2026-08-19": {"eps_estimate": 3.34, "eps_actual": 3.45}},
        )

        self.assertEqual(batch.skipped, [])
        self.assertEqual(batch.snapshots, [{
            "ticker": "ADI",
            "target_fiscal_year": 2026,
            "target_fiscal_period": "Q3",
            "target_period_end": "2026-08-01",
            "snapshot_date": "2026-08-19",
            "snapshot_kind": "reconstructed",
            "source": HISTORICAL_EPS_SOURCE,
            "source_horizon": "q+0",
            "eps_avg": 3.34,
        }])

    def test_rejects_distant_or_missing_eps_estimates(self) -> None:
        batch = build_historical_eps_estimates(
            [_flash(), _flash(ticker="INTU", filed_at="2026-08-25")],
            {
                "2026-08-10": {"eps_estimate": 3.34},
                "2026-08-25": {"eps_estimate": None},
            },
        )

        self.assertEqual(batch.snapshots, [])
        self.assertEqual(
            sorted(item["reason"] for item in batch.skipped),
            ["eps_estimate_missing", "report_date_unmatched"],
        )


class _FlashRepository:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.loaded_tickers: list[str] | None = None

    def load_earnings_results(self, tickers: list[str] | None) -> list[dict]:
        self.loaded_tickers = tickers
        return self.rows


class _ExpectationsRepository:
    def __init__(self) -> None:
        self.written: list[dict] = []

    def upsert_consensus(self, rows: list[dict]) -> int:
        self.written.extend(rows)
        return len(rows)


class _ReportedSource:
    def __init__(self, data: dict[str, dict[str, dict[str, float]]]) -> None:
        self.data = data

    def fetch_reported_earnings(self, ticker: str) -> dict[str, dict[str, float]]:
        return self.data[ticker]


class HistoricalEpsEstimateUseCaseTests(unittest.TestCase):
    def test_persists_only_matched_reconstructed_rows(self) -> None:
        flash_repository = _FlashRepository([_flash(), _flash(ticker="INTU", filed_at="2026-08-25")])
        expectations_repository = _ExpectationsRepository()
        source = _ReportedSource({
            "ADI": {"2026-08-19": {"eps_estimate": 3.34}},
            "INTU": {"2026-08-25": {"eps_estimate": 3.59}},
        })

        metrics = backfill_historical_eps_estimates(
            tickers=["ADI", "INTU"],
            flash_repository=flash_repository,
            expectations_repository=expectations_repository,
            source=source,
            request_gap_sec=0,
        )

        self.assertEqual(metrics["flash_rows"], 2)
        self.assertEqual(metrics["reconstructed_rows"], 2)
        self.assertEqual(metrics["failures"], [])
        self.assertEqual(
            {(row["ticker"], row["eps_avg"]) for row in expectations_repository.written},
            {("ADI", 3.34), ("INTU", 3.59)},
        )

    def test_all_scope_reads_existing_flash_rows_without_a_ticker_filter(self) -> None:
        flash_repository = _FlashRepository([_flash()])
        expectations_repository = _ExpectationsRepository()
        source = _ReportedSource({"ADI": {"2026-08-19": {"eps_estimate": 3.34}}})

        metrics = backfill_historical_eps_estimates(
            tickers=None,
            flash_repository=flash_repository,
            expectations_repository=expectations_repository,
            source=source,
            request_gap_sec=0,
        )

        self.assertEqual(metrics["reconstructed_rows"], 1)
        self.assertIsNone(flash_repository.loaded_tickers)


class ReportedEarningsAdapterTests(unittest.TestCase):
    def test_reads_the_wider_historical_earnings_window(self) -> None:
        frame = pd.DataFrame(
            {
                "EPS Estimate": [3.34],
                "Reported EPS": [3.45],
                "Surprise(%)": [3.32],
            },
            index=pd.to_datetime(["2026-08-19"]),
        )

        class _Ticker:
            def get_earnings_dates(self, *, limit: int):
                self.limit = limit
                return frame

        ticker = _Ticker()
        with patch.object(reported_earnings.yf, "Ticker", return_value=ticker):
            rows = reported_earnings.fetch_reported_earnings("ADI")

        self.assertEqual(ticker.limit, 100)
        self.assertEqual(rows["2026-08-19"]["eps_estimate"], 3.34)

    def test_provider_failure_is_raised_for_pipeline_accounting(self) -> None:
        ticker = MagicMock()
        ticker.get_earnings_dates.side_effect = RuntimeError("Yahoo unavailable")
        with patch.object(reported_earnings.yf, "Ticker", return_value=ticker):
            with self.assertRaisesRegex(RuntimeError, "Yahoo unavailable"):
                reported_earnings.fetch_reported_earnings("ADI")


class EarningsFlashViewContractTests(unittest.TestCase):
    def test_view_declares_observed_estimate_contract(self) -> None:
        with open("db/postgres/v1/30_fundamentals.sql", encoding="utf-8") as handle:
            sql = handle.read()

        self.assertIn("snapshot_kind", sql)
        self.assertIn("source_horizon", sql)
        self.assertIn("estimates_not_from_the_future_check", sql)

        with open("db/postgres/v1/90_reporting.sql", encoding="utf-8") as handle:
            reporting_sql = handle.read()
        self.assertIn("est.snapshot_date < f.filing_date", reporting_sql)
        self.assertNotIn("est.snapshot_date <= f.filing_date", reporting_sql)

    def test_consumers_read_the_derived_flash_view(self) -> None:
        with open("src/investment_agent/reporting/notifications/earnings_flash.py", encoding="utf-8") as handle:
            notify_db = handle.read()
        with open("src/investment_agent/dashboard/db.py", encoding="utf-8") as handle:
            dashboard_db = handle.read()

        self.assertIn('V_EARNINGS_SURPRISE = "earnings_surprise"', notify_db)
        self.assertIn("table=V_EARNINGS_SURPRISE", notify_db)
        for column in ("eps_analysts", "eps_surprise_pct", "revenue_surprise_pct", "snapshot_date"):
            self.assertIn(column, dashboard_db)


if __name__ == "__main__":
    unittest.main()
