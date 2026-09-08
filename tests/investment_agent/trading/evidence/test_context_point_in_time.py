"""historical replay에서 point-in-time 이력이 없는 데이터를 차단한다."""
from __future__ import annotations

import unittest
from unittest.mock import patch
from datetime import datetime, timezone

from investment_agent.trading.evidence.context import ContextBuilder


class _Repository:
    def __init__(self):
        self.macro_calls = 0

    def market_prices(self, ticker, as_of_at, limit=260):
        return [{
            "ticker": ticker,
            "trade_date": "2025-01-02",
            "close": 100,
            "ingested_at": "2025-01-02T23:00:00+00:00",
        }]

    def technical_snapshot(self, ticker, as_of_at):
        return []

    def fundamentals(self, ticker, as_of_at, limit=12):
        return []

    def fundamentals_pit(self, ticker, as_of_at, limit=12):
        return [{
            "ticker": ticker,
            "fiscal_year": 2025,
            "fiscal_period": "Q4",
            "filed_at": "2025-01-02",
            "period_end": "2024-12-31",
            "revenue": 100,
        }]

    def estimates(self, ticker, as_of_at, limit=12):
        return {"consensus": [], "analysts": []}

    def macro_snapshot(self, as_of_at):
        self.macro_calls += 1
        return {
            "run": {"finished_at": "2025-01-03T00:00:00+00:00"},
            "observations": [{"series_id": "CPI", "obs_date": "2024-12-01", "value": 1}],
        }

    def segment_snapshot(self, ticker, as_of_at):
        return {"filings": [], "metrics": []}

    def guru_snapshot(self, ticker, as_of_at):
        return {"filings": [], "positions": []}

    def econ_snapshot(self, as_of_at, lookback_days=14):
        return {"results": [], "forecasts": []}


class ContextPointInTimeTest(unittest.TestCase):
    def test_future_economic_event_is_evidence_without_a_forecast(self):
        repository = _Repository()
        event = {"event_key": "US_CPI:2024-12-01", "scheduled_at": "2025-01-10T13:30:00Z",
                 "collected_at": "2025-01-02T00:00:00Z"}
        with patch.object(repository, "econ_snapshot", return_value={"events": [event], "results": [], "forecasts": []}):
            bundle = ContextBuilder(repository).build("AAPL", datetime(2025, 1, 3, tzinfo=timezone.utc),
                                                       source_kind="historical_replay")
        evidence = next(item for item in bundle.evidence if item.domain == "economic_calendar")
        self.assertEqual(evidence.payload["events"], [event])
        self.assertFalse(any(item.startswith("economic_calendar:") for item in bundle.missing_data))

    def test_historical_replay_does_not_query_unversioned_macro(self):
        repository = _Repository()
        bundle = ContextBuilder(repository).build(
            "AAPL",
            datetime(2025, 1, 3, tzinfo=timezone.utc),
            source_kind="historical_replay",
        )
        self.assertEqual(repository.macro_calls, 0)
        self.assertNotIn("macro", bundle.domains)
        self.assertTrue(any("point-in-time" in item for item in bundle.missing_data))

    def test_live_shadow_can_use_latest_completed_macro_run(self):
        repository = _Repository()
        bundle = ContextBuilder(repository).build(
            "AAPL",
            datetime(2025, 1, 3, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(repository.macro_calls, 1)
        self.assertIn("macro", bundle.domains)

    def test_historical_replay_uses_financial_versions_cutoff_evidence(self):
        bundle = ContextBuilder(_Repository()).build(
            "AAPL",
            datetime(2025, 1, 3, tzinfo=timezone.utc),
            source_kind="historical_replay",
        )
        fundamentals = next(item for item in bundle.evidence if item.domain == "fundamentals")

        self.assertEqual(fundamentals.source, "SEC EDGAR/FSDS via fundamentals.financials")
        self.assertEqual(fundamentals.available_at, "2025-01-02T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
