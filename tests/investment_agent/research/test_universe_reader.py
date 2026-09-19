"""Research universe 입력이 canonical Data owner에서 오는지 검증한다."""
from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from investment_agent.research.datasets.universe import DataUniverseReader


class DataUniverseReaderTest(unittest.TestCase):
    @patch("investment_agent.research.datasets.universe.universe_data.select_tracked_tickers")
    def test_current_tickers_are_normalized_without_changing_data_ownership(self, select):
        select.return_value = ["msft", "AAPL", "aapl"]

        self.assertEqual(["AAPL", "MSFT"], DataUniverseReader().current_tracked_tickers())
        select.assert_called_once_with()

    @patch("investment_agent.research.datasets.universe.universe_data.select_sp500_membership_snapshots")
    def test_historical_membership_delegates_to_data_owner(self, select):
        select.return_value = [{"effective_date": "2026-01-02", "symbols": ["AAPL"]}]

        rows = DataUniverseReader().historical_sp500_membership(
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
        )

        self.assertEqual(select.return_value, rows)
        select.assert_called_once_with(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))

    @patch("investment_agent.research.datasets.universe.universe_data.select_sp500_membership_snapshots")
    def test_rl_membership_rows_preserve_the_existing_research_contract(self, select):
        select.return_value = [
            {
                "effective_date": "2026-01-02",
                "symbols": ["AAPL", "MSFT"],
                "source_hash": "a" * 64,
                "source": "ignored-when-hash-exists",
            },
            {
                "effective_date": "2026-02-03",
                "symbols": ["NVDA"],
                "source": "official-source",
            },
        ]

        rows = DataUniverseReader().rl_historical_membership_rows(
            start_as_of="2026-01-01T12:00:00+00:00",
            end_as_of="2026-02-28T23:00:00+00:00",
        )

        self.assertEqual(
            [
                {
                    "effective_at": "2026-01-02T00:00:00+00:00",
                    "symbols": ["AAPL", "MSFT"],
                    "source_id": "a" * 64,
                    "source_kind": "historical_point_in_time",
                },
                {
                    "effective_at": "2026-02-03T00:00:00+00:00",
                    "symbols": ["NVDA"],
                    "source_id": "official-source",
                    "source_kind": "historical_point_in_time",
                },
            ],
            rows,
        )
        select.assert_called_once()
        kwargs = select.call_args.kwargs
        self.assertEqual("2026-01-01", kwargs["start_date"].isoformat())
        self.assertEqual("2026-02-28", kwargs["end_date"].isoformat())

    @patch("investment_agent.research.datasets.universe.universe_data.select_sp500_membership_snapshots")
    def test_rl_membership_rejects_an_inverted_window_before_reading(self, select):
        with self.assertRaisesRegex(ValueError, "must not precede"):
            DataUniverseReader().rl_historical_membership_rows(
                start_as_of="2026-02-01T00:00:00+00:00",
                end_as_of="2026-01-01T00:00:00+00:00",
            )

        select.assert_not_called()


if __name__ == "__main__":
    unittest.main()
