from __future__ import annotations

import unittest

from investment_agent.trading.contracts import EvidenceBundle, EvidenceItem
from investment_agent.research.features.layer import FeatureLayer


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


if __name__ == "__main__":
    unittest.main()
