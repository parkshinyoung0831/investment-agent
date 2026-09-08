from __future__ import annotations

import unittest
from datetime import datetime, timezone

from investment_agent.trading.contracts import ContractError
from investment_agent.trading.portfolio.contracts import PortfolioProposal
from investment_agent.trading.risk.gate import (
    DeterministicRiskGate,
    PortfolioRiskPolicy,
    portfolio_turnover,
)


def proposal(weights: dict[str, float], as_of_at: str = "2026-08-21T11:00:00+00:00"):
    return PortfolioProposal.create(
        run_id="run-1", source_type="llm", source_version="ta-v1",
        stage="shadow", as_of_at=as_of_at, weights=weights,
        confidence=0.8, reasoning=("test",),
    )


class RiskGateTest(unittest.TestCase):
    def test_nonfinite_policy_cannot_disable_age_or_beta_limits(self):
        for field in ("max_proposal_age_hours", "max_abs_beta"):
            for value in (float("nan"), float("inf"), float("-inf")):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    PortfolioRiskPolicy(**{field: value})

    def test_caps_symbol_and_preserves_cash_and_total(self):
        gate = DeterministicRiskGate(PortfolioRiskPolicy(
            max_symbol_weight=0.10, max_turnover=1.0, min_cash_weight=0.05,
        ))
        result = gate.evaluate(
            proposal({"AAPL": 0.60, "CASH": 0.40}),
            current_weights={"CASH": 1.0},
            tradable_symbols={"AAPL"},
            decided_at=datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
        )
        self.assertTrue(result.is_approved)
        self.assertAlmostEqual(result.approved_weights["AAPL"], 0.10)
        self.assertAlmostEqual(result.approved_weights["CASH"], 0.90)
        self.assertTrue(result.adjustments)
        self.assertAlmostEqual(result.metrics["concentration_hhi"], 0.01)
        self.assertAlmostEqual(result.metrics["turnover"], 0.10)
        self.assertIn("portfolio_volatility", result.to_dict()["metrics"])

    def test_rejects_unknown_and_stale_proposal(self):
        gate = DeterministicRiskGate(PortfolioRiskPolicy(max_proposal_age_hours=1))
        result = gate.evaluate(
            proposal({"FAKE": 0.05, "CASH": 0.95}, "2026-08-20T00:00:00+00:00"),
            current_weights={"CASH": 1.0}, tradable_symbols={"AAPL"},
            decided_at=datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
        )
        self.assertFalse(result.is_approved)
        self.assertIsNone(result.approved_weights)
        self.assertEqual(len(result.violations), 2)

    def test_turnover_is_scaled_toward_current_portfolio(self):
        gate = DeterministicRiskGate(PortfolioRiskPolicy(
            max_symbol_weight=1.0, max_turnover=0.10, min_cash_weight=0.0,
        ))
        result = gate.evaluate(
            proposal({"AAPL": 1.0, "CASH": 0.0}),
            current_weights={"CASH": 1.0}, tradable_symbols={"AAPL"},
            decided_at=datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
        )
        self.assertTrue(result.is_approved)
        self.assertAlmostEqual(
            portfolio_turnover({"CASH": 1.0}, result.approved_weights), 0.10
        )

    def test_only_approved_decision_creates_intent(self):
        gate = DeterministicRiskGate(PortfolioRiskPolicy(max_turnover=1.0))
        rejected = gate.evaluate(
            proposal({"FAKE": 0.05, "CASH": 0.95}),
            current_weights={"CASH": 1.0}, tradable_symbols=set(),
            decided_at=datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
        )
        with self.assertRaises(ContractError):
            gate.create_execution_intent(
                rejected, execution_mode="paper",
                not_before=datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
