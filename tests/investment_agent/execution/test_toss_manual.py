from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from investment_agent.execution.orders.intents import ExecutionIntent
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.orders.planning import ExecutionLimits, TargetWeightOrderPlanner
from investment_agent.execution.orders.toss_manual import export_handoff, prepare_handoff

_NOW = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)


def _intent() -> ExecutionIntent:
    return ExecutionIntent(
        intent_id="intent-toss-preview",
        risk_decision_id="risk-1",
        proposal_id="proposal-1",
        execution_mode="paper",
        target_weights={"AAPL": 0.1, "MSFT": 0.1, "CASH": 0.8},
        input_hash=hashlib.sha256(b"input").hexdigest(),
        not_before="2026-08-21T11:00:00+00:00",
        expires_at="2026-08-21T13:00:00+00:00",
    )


def _planner() -> TargetWeightOrderPlanner:
    return TargetWeightOrderPlanner(ExecutionLimits(
        min_order_notional=1,
        max_order_notional=10_000,
        max_total_notional=20_000,
    ))


class TossManualHandoffTest(unittest.TestCase):
    @patch("investment_agent.execution.orders.toss_manual.toss.fetch_buying_power", return_value=8_000)
    @patch(
        "investment_agent.execution.orders.toss_manual.toss.fetch_prices",
        return_value=(
            {"AAPL": 100.0, "MSFT": 100.0},
            {"AAPL": "2026-08-21T12:00:00+00:00", "MSFT": "2026-08-21T12:00:00+00:00"},
        ),
    )
    @patch(
        "investment_agent.execution.orders.toss_manual.toss.fetch_holdings",
        return_value={
            "items": [{"marketCountry": "US", "symbol": "AAPL", "quantity": "20"}],
            "dailyProfitLoss": {"amount": {"usd": "25"}},
        },
    )
    @patch("investment_agent.execution.orders.toss_manual.toss.fetch_open_orders", return_value=[])
    def test_preview_is_deterministic_and_sells_before_buys(
        self, _orders, _holdings, _prices, _cash,
    ):
        first = prepare_handoff(
            _intent(), account_seq=7, eligible_buy_symbols={"AAPL", "MSFT"},
            planner=_planner(), now=_NOW,
        )
        second = prepare_handoff(
            _intent(), account_seq=7, eligible_buy_symbols={"AAPL", "MSFT"},
            planner=_planner(), now=_NOW,
        )
        self.assertEqual(first.manifest_hash, second.manifest_hash)
        self.assertEqual(first.snapshot.daily_profit_loss_usd, 25.0)
        self.assertEqual(
            [(ticket.side, ticket.symbol, ticket.order_quantity) for ticket in first.tickets],
            [("sell", "AAPL", 10.0), ("buy", "MSFT", 10.0)],
        )

    @patch(
        "investment_agent.execution.orders.toss_manual.toss.fetch_open_orders",
        return_value=[{"symbol": "AAPL"}],
    )
    def test_open_orders_fail_closed(self, _orders):
        with self.assertRaisesRegex(ExecutionSafetyError, "open orders"):
            prepare_handoff(
                _intent(), account_seq=7, eligible_buy_symbols={"AAPL", "MSFT"},
                planner=_planner(), now=_NOW,
            )

    @patch("investment_agent.execution.orders.toss_manual.toss.fetch_buying_power", return_value=8_000)
    @patch(
        "investment_agent.execution.orders.toss_manual.toss.fetch_prices",
        return_value=(
            {"AAPL": 100.0, "MSFT": 100.0},
            {"AAPL": None, "MSFT": None},
        ),
    )
    @patch(
        "investment_agent.execution.orders.toss_manual.toss.fetch_holdings",
        return_value={
            "items": [{"marketCountry": "US", "symbol": "AAPL", "quantity": "20"}],
            "dailyProfitLoss": {"amount": {"usd": "25"}},
        },
    )
    @patch("investment_agent.execution.orders.toss_manual.toss.fetch_open_orders", return_value=[])
    def test_export_requires_exact_confirmation_and_contains_no_account_identifier(
        self, _orders, _holdings, _prices, _cash,
    ):
        handoff = prepare_handoff(
            _intent(), account_seq=987654, eligible_buy_symbols={"AAPL", "MSFT"},
            planner=_planner(), now=_NOW,
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ExecutionSafetyError, "exactly match"):
                export_handoff(handoff, output_dir=Path(directory), confirm="wrong")
            csv_path, manifest_path = export_handoff(
                handoff,
                output_dir=Path(directory),
                confirm=handoff.intent_id,
            )
            self.assertTrue(csv_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["disclaimer"], "NON_EXECUTABLE_TOSS_MANUAL_ORDER_SHEET")
            self.assertNotIn("account_seq", manifest_path.read_text(encoding="utf-8").lower())
            self.assertNotIn("987654", manifest_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
