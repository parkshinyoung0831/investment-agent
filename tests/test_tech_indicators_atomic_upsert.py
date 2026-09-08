from __future__ import annotations

import inspect
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import pandas as pd

from investment_agent.research.features import db


def _frame() -> pd.DataFrame:
    return pd.DataFrame({
        "ticker": ["AAPL"],
        "trade_date": [date(2026, 8, 27)],
        "rsi14": [55.0],
        "macd": [1.25],
        "macd_signal": [1.1],
    })


class TechIndicatorAtomicUpsertTests(unittest.TestCase):
    def test_existing_indicator_rows_are_read_from_local_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ, {"INVESTMENT_AGENT_RESEARCH_ROOT": directory}
        ):
            self.assertEqual(db.upsert_indicators(_frame()), 1)
            rows = db.existing_indicators_since("2026-08-01")
        self.assertEqual(rows[("AAPL", "2026-08-27")]["rsi14"], 55.0)

    def test_price_history_projects_security_identity_to_current_ticker(self) -> None:
        with mock.patch.object(
            db,
            "select_all_paged",
            side_effect=[
                [{"security_id": 7, "ticker": "AAPL"}],
                [{"security_id": 7, "trade_date": "2026-08-27", "close": 100}],
            ],
        ) as paged:
            rows = db.load_market_prices_since("2026-08-01")

        self.assertEqual(rows, [{"ticker": "AAPL", "trade_date": "2026-08-27", "close": 100}])
        self.assertEqual(paged.call_args_list[0].kwargs["order_by"], "security_id")
        self.assertEqual(paged.call_args_list[1].kwargs["order_by"], "security_id,trade_date")

    def test_price_history_rejects_unmapped_security(self) -> None:
        with (
            mock.patch.object(db, "select_all_paged", side_effect=[
                [], [{"security_id": 99, "trade_date": "2026-08-27", "close": 100}],
            ]),
            self.assertRaisesRegex(RuntimeError, "without a universe ticker"),
        ):
            db.load_market_prices_since("2026-08-01")

    def test_upsert_is_idempotent_and_local(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ, {"INVESTMENT_AGENT_RESEARCH_ROOT": directory}
        ):
            self.assertEqual(db.upsert_indicators(_frame()), 1)
            self.assertEqual(db.upsert_indicators(_frame()), 0)
        self.assertNotIn("tech_indicators", inspect.getsource(db))

    def test_invalid_frame_fails_before_local_write(self) -> None:
        frame = _frame()
        frame.loc[0, "rsi14"] = float("nan")
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ, {"INVESTMENT_AGENT_RESEARCH_ROOT": directory}
        ), self.assertRaisesRegex(ValueError, "non-finite"):
            db.upsert_indicators(frame)
        self.assertEqual(list(Path(directory).glob("**/*")), [])

    def test_research_has_no_production_schema_declaration(self) -> None:
        sql_root = Path("src/investment_agent/research/features/sql")
        self.assertEqual(list(sql_root.glob("*.sql")), [])


if __name__ == "__main__":
    unittest.main()
