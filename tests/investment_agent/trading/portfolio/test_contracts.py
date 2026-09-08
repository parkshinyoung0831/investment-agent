from __future__ import annotations

import unittest

from investment_agent.trading.contracts import ContractError
from investment_agent.trading.portfolio.contracts import PortfolioProposal, SecurityProposal
from investment_agent.trading.portfolio.proposals import (
    from_security_proposals,
    from_strategy_allocation,
)


class PortfolioContractTest(unittest.TestCase):
    def test_weights_must_include_a_complete_cash_aware_simplex(self):
        with self.assertRaises(ContractError):
            PortfolioProposal.create(
                run_id="run-1", source_type="rl", source_version="ppo-v1",
                stage="shadow", as_of_at="2026-08-21T12:00:00+00:00",
                weights={"AAPL": 0.4, "CASH": 0.4}, confidence=0.7,
                reasoning=("test",),
            )

    def test_security_proposals_become_one_normalized_portfolio(self):
        proposals = [
            SecurityProposal(
                ticker="AAPL", as_of_at="2026-08-21T12:00:00+00:00",
                signal="open", probability_up=0.7, confidence=0.8,
                expected_excess_return=0.03, target_weight=0.8,
                reasoning=("EV evidence",), evidence_ids=("EV-1",),
            ),
            SecurityProposal(
                ticker="MSFT", as_of_at="2026-08-21T12:00:00+00:00",
                signal="open", probability_up=0.6, confidence=0.7,
                expected_excess_return=0.02, target_weight=0.4,
                reasoning=("EV evidence",), evidence_ids=("EV-2",),
            ),
        ]
        portfolio = from_security_proposals(
            proposals, run_id="run-1", source_version="ta-v1", min_cash_weight=0.1
        )
        self.assertAlmostEqual(sum(portfolio.weights.values()), 1.0)
        self.assertAlmostEqual(portfolio.weights["CASH"], 0.1)
        self.assertAlmostEqual(portfolio.weights["AAPL"], 0.6)
        self.assertAlmostEqual(portfolio.weights["MSFT"], 0.3)
        self.assertEqual(portfolio.metadata["coverage"], "partial_universe")
        self.assertEqual(portfolio.metadata["analyzed_symbols"], ["AAPL", "MSFT"])

    def test_security_portfolio_coverage_must_be_explicit_and_valid(self):
        proposal = SecurityProposal(
            ticker="AAPL", as_of_at="2026-08-21T12:00:00+00:00",
            signal="open", probability_up=0.7, confidence=0.8,
            expected_excess_return=0.03, target_weight=0.1,
            reasoning=("EV evidence",), evidence_ids=("EV-1",),
        )
        portfolio = from_security_proposals(
            [proposal], run_id="run-1", source_version="ta-v1",
            coverage="full_portfolio",
        )
        self.assertEqual(portfolio.metadata["coverage"], "full_portfolio")
        with self.assertRaises(ContractError):
            from_security_proposals(
                [proposal], run_id="run-1", source_version="ta-v1",
                coverage="unknown",
            )

    def test_execution_critical_scope_changes_proposal_identity(self):
        common = dict(
            run_id="run-1", source_type="llm", source_version="ta-v1",
            stage="shadow", as_of_at="2026-08-21T12:00:00+00:00",
            weights={"AAPL": 0.1, "CASH": 0.9}, confidence=0.8,
            reasoning=("test",),
        )
        partial = PortfolioProposal.create(
            **common, metadata={"coverage": "partial_universe"}
        )
        full = PortfolioProposal.create(
            **common, metadata={"coverage": "full_portfolio"},
        )
        self.assertNotEqual(partial.proposal_id, full.proposal_id)

    def test_security_parser_rejects_unknown_evidence(self):
        with self.assertRaises(ContractError):
            SecurityProposal.from_dict(
                {
                    "ticker": "AAPL",
                    "as_of_at": "2026-08-21T12:00:00+00:00",
                    "signal": "watch",
                    "probability_up": 0.5,
                    "confidence": 0.5,
                    "expected_excess_return": 0.0,
                    "target_weight": 0.0,
                    "reasoning": ["근거 부족"],
                    "evidence_ids": ["EV-FAKE"],
                    "missing_data": [],
                },
                ticker="AAPL",
                as_of_at="2026-08-21T12:00:00+00:00",
                allowed_evidence_ids={"EV-REAL"},
            )

    def test_etf_strategy_is_reference_only_not_an_executable_full_portfolio(self):
        proposal = from_strategy_allocation(
            {
                "strategy_id": "dual-momentum",
                "weights": {"SPY": 0.6, "BIL": 0.4},
                "decision_date": "2026-08-21",
                "apply_date": "2026-09-01",
            },
            run_id="run-etf-reference",
            as_of_at="2026-08-21T12:00:00+00:00",
        )
        self.assertEqual(proposal.metadata["coverage"], "partial_universe")
        self.assertFalse(proposal.metadata["execution_eligible"])
        self.assertEqual(proposal.metadata["purpose"], "benchmark_reference_only")
        self.assertEqual(proposal.reasoning, ("research.strategy_allocations:dual-momentum",))


if __name__ == "__main__":
    unittest.main()
