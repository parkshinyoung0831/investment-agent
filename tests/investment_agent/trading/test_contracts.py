"""LLM 계약이 미래 근거와 가짜 인용을 차단하는지 검증한다."""
from __future__ import annotations

import unittest

from investment_agent.trading.contracts import (
    ContractError,
    EvidenceBundle,
    EvidenceItem,
    InvestmentDecision,
)


def _evidence(available_at: str = "2026-08-20T22:00:00+00:00") -> EvidenceItem:
    return EvidenceItem(
        evidence_id="EV-MARKET-abc",
        domain="market",
        source="test",
        observed_at="2026-08-20",
        available_at=available_at,
        timing_status="known",
        payload={"close": 100},
    )


class EvidenceContractTest(unittest.TestCase):
    def test_future_evidence_is_rejected(self):
        with self.assertRaisesRegex(ContractError, "future evidence"):
            EvidenceBundle(
                ticker="AAPL",
                as_of_at="2026-08-20T21:00:00+00:00",
                source_kind="live_shadow",
                evidence=(_evidence(),),
            )

    def test_decision_cannot_cite_unknown_evidence(self):
        data = {
            "ticker": "AAPL",
            "as_of_at": "2026-08-21T00:00:00+00:00",
            "horizon_days": 20,
            "action": "watch",
            "probability_up": 0.5,
            "expected_excess_return": 0.0,
            "confidence": 0.4,
            "target_risk_unit": 0.0,
            "thesis": [],
            "bear_case": [],
            "catalysts": [],
            "invalidation": [],
            "evidence_ids": ["EV-FAKE-999"],
            "missing_data": [],
        }
        with self.assertRaisesRegex(ContractError, "unknown evidence"):
            InvestmentDecision.from_dict(
                data,
                ticker="AAPL",
                as_of_at=data["as_of_at"],
                allowed_ids={"EV-MARKET-abc"},
            )


if __name__ == "__main__":
    unittest.main()

