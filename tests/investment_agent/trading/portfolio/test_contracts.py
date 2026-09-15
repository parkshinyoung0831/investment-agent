from __future__ import annotations

import unittest

from investment_agent.trading.contracts import ContractError
from investment_agent.trading.portfolio.contracts import PortfolioProposal, SecurityProposal


class PortfolioContractTest(unittest.TestCase):
    def test_weights_must_include_a_complete_cash_aware_simplex(self):
        with self.assertRaises(ContractError):
            PortfolioProposal.create(
                run_id="run-1", source_type="rl", source_version="ppo-v1",
                stage="shadow", as_of_at="2026-08-21T12:00:00+00:00",
                weights={"AAPL": 0.4, "CASH": 0.4}, confidence=0.7,
                reasoning=("test",),
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



if __name__ == "__main__":
    unittest.main()
