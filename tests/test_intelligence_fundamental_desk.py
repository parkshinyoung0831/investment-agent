"""Unit tests for Intelligence Fundamental Desk with institutional metrics."""
from __future__ import annotations

import unittest
from investment_agent.trading.contracts import EvidenceBundle, EvidenceItem
from investment_agent.trading.decision.desks.fundamental import analyze_fundamental


class FundamentalDeskTest(unittest.TestCase):
    def test_analyze_fundamental_with_revision_breadth_and_true_fcf(self):
        bundle = EvidenceBundle(
            ticker="NVDA",
            as_of_at="2026-08-31T00:00:00+00:00",
            source_kind="live_shadow",
            evidence=(
                EvidenceItem(
                    evidence_id="ev-1",
                    domain="estimates",
                    source="fundamentals.v_security_estimates_momentum",
                    observed_at="2026-08-30T00:00:00+00:00",
                    available_at="2026-08-30T00:00:00+00:00",
                    timing_status="known",
                    payload={"revision_breadth_30d": 0.75},
                ),
                EvidenceItem(
                    evidence_id="ev-2",
                    domain="fundamentals",
                    source="fundamentals.v_security_metrics",
                    observed_at="2026-08-30T00:00:00+00:00",
                    available_at="2026-08-30T00:00:00+00:00",
                    timing_status="known",
                    payload={
                        "true_fcf_margin_ttm": 0.45,
                        "revenue_growth_yoy": 0.50,
                    },
                ),
            ),
        )

        signal = analyze_fundamental(bundle)
        self.assertEqual(signal.domain, "fundamental")
        self.assertGreater(signal.direction, 0.5)
        self.assertIn("30일 컨센서스 리비전 +0.75", signal.reasoning)
        self.assertIn("SBC차감 FCF수익/마진 45.00%", signal.reasoning)
        self.assertIn("매출 성장 50.00%", signal.reasoning)

    def test_analyze_fundamental_fallback_metrics(self):
        bundle = EvidenceBundle(
            ticker="AAPL",
            as_of_at="2026-08-31T00:00:00+00:00",
            source_kind="live_shadow",
            evidence=(
                EvidenceItem(
                    evidence_id="ev-1",
                    domain="fundamentals",
                    source="fundamentals.v_security_metrics",
                    observed_at="2026-08-30T00:00:00+00:00",
                    available_at="2026-08-30T00:00:00+00:00",
                    timing_status="known",
                    payload={"fcf_growth": 0.10},
                ),
            ),
        )
        signal = analyze_fundamental(bundle)
        self.assertIn("FCF 변화 10.00%", signal.reasoning)


if __name__ == "__main__":
    unittest.main()
