"""FactVerificationGate 단위 테스트."""
from __future__ import annotations

import unittest

from investment_agent.trading.decision.fact_checker import (
    FactClaim,
    FactVerificationGate,
    extract_claims,
)


class FactCheckerTests(unittest.TestCase):
    def test_extract_claims_finds_metrics(self) -> None:
        text = (
            "현재 AAPL의 주가는 180.5달러이며 RSI는 65.2입니다. "
            "P/E는 28.5배로 고평가이나 매출성장률은 12.5%에 달합니다."
        )
        claims = extract_claims(text)
        metrics = {c.metric: c.claimed_value for c in claims}
        self.assertAlmostEqual(metrics.get("price", 0), 180.5)
        self.assertAlmostEqual(metrics.get("rsi", 0), 65.2)
        self.assertAlmostEqual(metrics.get("pe_ratio", 0), 28.5)
        self.assertAlmostEqual(metrics.get("revenue_growth", 0), 12.5)

    def test_verify_passes_when_claims_match_evidence(self) -> None:
        gate = FactVerificationGate(tolerance=0.05)
        text = "RSI 65.0, P/E 30.0, 주가 150.0"
        evidence = {
            "rsi": 64.5,   # ~0.8% error <= 5%
            "pe_ratio": 29.8, # ~0.7% error <= 5%
            "price": 151.0,   # ~0.7% error <= 5%
        }
        res = gate.verify(text, evidence)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.hallucination_count, 0)
        self.assertEqual(res.verified_claims, 3)
        self.assertAlmostEqual(res.confidence_penalty, 0.0)

    def test_verify_penalizes_hallucinations(self) -> None:
        gate = FactVerificationGate(tolerance=0.05, max_hallucination_rate=0.3)
        # LLM이 PER을 15배라고 주장했으나 실제로는 45배(심각한 왜곡)
        text = "P/E 15.0로 저평가되어 있으며 주가 100.0"
        evidence = {
            "pe_ratio": 45.0,  # 200% error!
            "price": 100.0,    # match
        }
        res = gate.verify(text, evidence)
        self.assertFalse(res.is_valid)
        self.assertEqual(res.hallucination_count, 1)
        self.assertEqual(res.verified_claims, 1)
        self.assertGreaterEqual(res.confidence_penalty, 0.5)
        self.assertLess(res.adjusted_confidence(0.8), 0.4)

    def test_empty_reasoning_is_safe(self) -> None:
        gate = FactVerificationGate()
        res = gate.verify("", {})
        self.assertTrue(res.is_valid)
        self.assertEqual(res.total_claims, 0)


if __name__ == "__main__":
    unittest.main()
