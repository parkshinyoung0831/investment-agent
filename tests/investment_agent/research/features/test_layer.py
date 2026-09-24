from __future__ import annotations

import unittest
from types import SimpleNamespace

from investment_agent.research.features.layer import FeatureLayer
from investment_agent.research.evidence.contracts import EvidenceBundle, EvidenceItem


class FeatureLayerTest(unittest.TestCase):
    def _bundle(self) -> EvidenceBundle:
        return EvidenceBundle(
            ticker="AAPL", as_of_at="2026-08-20T22:00:00+00:00",
            source_kind="historical_replay",
            evidence=(EvidenceItem(
                evidence_id="EV-MARKET-1", domain="market", source="market.prices_daily",
                observed_at="2026-08-20", available_at="2026-08-20T21:30:00+00:00",
                timing_status="known", payload={"latest_bars": [
                    {"trade_date": "2026-08-20", "close": 110.0},
                    {"trade_date": "2026-08-19", "close": 100.0},
                    {"trade_date": "2026-08-18", "close": 90.0},
                ]},
            ),),
        )

    def test_snapshot_is_reproducible_and_has_no_future_label(self):
        first = FeatureLayer().build(self._bundle())
        second = FeatureLayer().build(self._bundle())
        self.assertEqual(first.snapshot.snapshot_id, second.snapshot.snapshot_id)
        self.assertEqual(first.definition_hash, second.definition_hash)
        self.assertAlmostEqual(first.snapshot.features["price_return_1d"], 0.1)
        self.assertNotIn("forward_return", first.snapshot.features)
        self.assertFalse(first.snapshot.provenance["news_social_enabled"])

    def test_debt_to_assets_sums_debt_components_when_no_total_tag_is_filed(self):
        """대부분의 회사는 총차입 총계 태그 없이 구성요소만 낸다. 총계만 읽으면 열이 거의 빈다."""
        original = self._bundle()
        fundamentals = EvidenceItem(
            evidence_id="EV-FUND-1", domain="fundamentals", source="fundamentals.financials",
            observed_at="2026-06-30", available_at="2026-08-01T04:00:00+00:00", timing_status="known",
            payload={"filings": [{"assets": 1000.0, "short_term_debt": 50.0, "long_term_debt": 250.0,
                                  "revenue": 400.0, "operating_income_loss": 80.0}]},
        )
        bundle = EvidenceBundle(ticker=original.ticker, as_of_at=original.as_of_at,
                                source_kind=original.source_kind, evidence=(*original.evidence, fundamentals))
        features = FeatureLayer().build(bundle).snapshot.features
        self.assertAlmostEqual(0.3, features["fundamental_debt_to_assets"])

    def test_feature_input_is_structural_not_a_trading_class(self):
        original = self._bundle()
        item = original.evidence[0]
        incoming = SimpleNamespace(
            ticker=original.ticker, as_of_at=original.as_of_at,
            source_kind=original.source_kind, missing_data=original.missing_data,
            evidence=(SimpleNamespace(
                evidence_id=item.evidence_id, domain=item.domain,
                available_at=item.available_at, payload=item.payload,
            ),),
        )
        self.assertEqual(
            FeatureLayer().build(original).snapshot.snapshot_id,
            FeatureLayer().build(incoming).snapshot.snapshot_id,
        )


if __name__ == "__main__":
    unittest.main()
