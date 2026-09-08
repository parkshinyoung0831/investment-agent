"""실적 consensus reader와 v1 필드 계약을 검증한다."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from investment_agent.reporting.notifications import earnings_report


class EarningsConsensusReaderTest(unittest.TestCase):
    def test_reader_returns_snapshot_kind_for_consensus_contract(self) -> None:
        database = Mock()
        database.select_in_chunks.return_value = [
            {
                "security_id": 7,
                "target_fiscal_year": 2026,
                "target_fiscal_period": "Q3",
                "snapshot_date": "2026-08-15",
                "snapshot_kind": "observed",
            }
        ]
        universe = Mock()
        universe.securities_by_ticker.return_value = {
            "NVDA": SimpleNamespace(security_id=7)
        }

        with (
            patch.object(earnings_report.Database, "from_config", return_value=database),
            patch.object(earnings_report, "UniverseRepository", return_value=universe),
        ):
            rows = earnings_report.load_earnings_estimates(["NVDA"])

        self.assertEqual(rows[0]["snapshot_kind"], "observed")
        columns = database.select_in_chunks.call_args.kwargs["columns"]
        self.assertIn("snapshot_kind", columns)

    def test_reader_maps_reporting_surprise_view_to_card_contract(self) -> None:
        database = Mock()
        database.select_in_chunks.return_value = [
            {
                "ticker": "NVDA",
                "period_end": "2026-07-26",
                "eps_actual": 2.25,
                "eps_estimate": 2.08,
                "eps_surprise_pct": 0.0817,
            }
        ]

        with patch.object(earnings_report.Database, "from_config", return_value=database):
            history = earnings_report.load_surprise_history(["NVDA"])

        self.assertEqual(history["NVDA"][0]["quarter_end"], "2026-07-26")
        self.assertEqual(history["NVDA"][0]["eps_estimate"], 2.08)
        query = database.select_in_chunks.call_args.kwargs
        self.assertEqual(query["schema"], "reporting")
        self.assertEqual(query["table"], "earnings_surprise")


if __name__ == "__main__":
    unittest.main()
