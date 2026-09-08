from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from investment_agent.research.backtest.cli import load_backtest_input, main


def payload() -> dict:
    return {
        "schema_version": "ai-backtest-v1",
        "transaction_costs": {"commission_rate": 0.0, "slippage_bps": 0.0},
        "request": {
            "sessions": ["2026-01-02", "2026-01-05"],
            "bars": [
                {"symbol": "AAPL", "session_date": day, "open": 100, "high": 101,
                 "low": 99, "close": 100, "volume": 1000}
                for day in ("2026-01-02", "2026-01-05")
            ],
            "weight_points": [{
                "point_id": "", "decided_at": "2026-01-02T20:00:00+00:00",
                "effective_date": "2026-01-05", "weights": {"AAPL": 0.5, "CASH": 0.5},
                "source_id": "test", "case_keys": [],
            }],
            "universe_snapshots": [{
                "effective_date": "2026-01-02", "symbols": ["AAPL"], "source_id": "pit-1",
            }],
            "corporate_actions": [],
            "config": {"initial_cash": 10000, "cohort_mode": "point_in_time"},
        },
    }


class BacktestJsonEntryTest(unittest.TestCase):
    def test_load_and_write_reproducible_artifact(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            input_path = root / "input.json"
            output_path = root / "output.json"
            input_path.write_text(json.dumps(payload()), encoding="utf-8")
            request, _costs = load_backtest_input(input_path)
            self.assertEqual(request.config.cohort_mode, "point_in_time")
            self.assertEqual(main(["--input", str(input_path), "--output", str(output_path)]), 0)
            artifact = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact["schema_version"], "ai-backtest-v1")
            self.assertFalse(artifact["result"]["research_only"])
            self.assertEqual(len(artifact["result"]["artifact_hash"]), 64)

    def test_unknown_schema_version_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.json"
            value = payload()
            value["schema_version"] = "future"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_backtest_input(path)


if __name__ == "__main__":
    unittest.main()

