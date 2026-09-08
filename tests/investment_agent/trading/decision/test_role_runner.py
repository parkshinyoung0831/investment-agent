"""6단계 하네스와 코드 위험 게이트를 검증한다."""
from __future__ import annotations

import unittest

from investment_agent.trading.contracts import EvidenceBundle, EvidenceItem
from investment_agent.trading.decision.role_runner import InvestmentHarness


class FakeClient:
    provider = "fake"
    model = "fake-model"

    def __init__(self):
        self.calls: list[str] = []

    def complete_json(self, *, system, user, output_schema, task_name):
        self.calls.append(task_name)
        if task_name != "portfolio_manager":
            return {
                "summary": task_name,
                "stance": "neutral",
                "confidence": 0.5,
                "claims": [],
                "risks": [],
                "missing_data": [],
            }
        return {
            "ticker": "AAPL",
            "as_of_at": "2026-08-21T00:00:00+00:00",
            "horizon_days": 20,
            "action": "open",
            "probability_up": 0.7,
            "expected_excess_return": 0.05,
            "confidence": 0.8,
            "target_risk_unit": 0.2,
            "thesis": ["test"],
            "bear_case": [],
            "catalysts": [],
            "invalidation": [],
            "evidence_ids": ["EV-MARKET-1"],
            "missing_data": [],
        }


class HarnessTest(unittest.TestCase):
    def test_runs_six_roles_and_downgrades_missing_domain_risk(self):
        evidence = EvidenceItem(
            evidence_id="EV-MARKET-1",
            domain="market",
            source="test",
            observed_at="2026-08-20",
            available_at="2026-08-20T22:00:00+00:00",
            timing_status="known",
            payload={"close": 100},
        )
        bundle = EvidenceBundle(
            ticker="AAPL",
            as_of_at="2026-08-21T00:00:00+00:00",
            source_kind="live_shadow",
            evidence=(evidence,),
        )
        client = FakeClient()

        result = InvestmentHarness(client).run(bundle)

        self.assertEqual(len(client.calls), 6)
        self.assertEqual(client.calls[-1], "portfolio_manager")
        self.assertEqual(result.decision.action, "watch")
        self.assertEqual(result.decision.target_risk_unit, 0.0)
        self.assertTrue(any("필수 근거" in item for item in result.decision.missing_data))


if __name__ == "__main__":
    unittest.main()

