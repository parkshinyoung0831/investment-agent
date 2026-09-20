"""Research 사건 산출물의 식별자·시각·직렬화 계약."""
from __future__ import annotations

import unittest
from dataclasses import replace

from investment_agent.platform.serialization import ContractError
from investment_agent.research.features.event_contracts import Event, EventFeatureSnapshot


class EventContractTest(unittest.TestCase):
    def _event(self) -> Event:
        return Event(
            event_id="event-1", ticker="aapl", event_type="earnings",
            occurred_at="2026-08-20T20:00:00Z", available_at="2026-08-20T21:00:00Z",
            first_seen_at="2026-08-20T21:00:00Z", importance=0.8,
            direction=0.4, confidence=0.9, novelty=0.5, controversy=0.2,
            source_count=2, source_diversity=1.0, sentiment=0.4,
            evidence_ids=("source-a", "source-b"), metadata={"themes": ["energy_oil"]},
        )

    def test_event_owner_normalization_and_pit_rejection(self):
        event = self._event()
        self.assertEqual(Event.__module__, "investment_agent.research.features.event_contracts")
        self.assertEqual(event.to_dict()["ticker"], "AAPL")
        with self.assertRaisesRegex(ContractError, "available_at cannot precede"):
            replace(event, available_at="2026-08-20T19:00:00Z")
        with self.assertRaisesRegex(ContractError, "evidence_ids must be unique"):
            replace(event, evidence_ids=("source-a", "source-a"))

    def test_feature_hash_and_source_order_are_unchanged(self):
        feature = EventFeatureSnapshot(
            ticker="aapl", as_of_at="2026-08-20T22:00:00Z",
            available_at="2026-08-20T21:00:00Z", source_ids=("b", "a"),
            event_count=2, high_impact_event_count=1,
        )
        self.assertEqual(EventFeatureSnapshot.__module__, "investment_agent.research.features.event_contracts")
        self.assertEqual(feature.to_dict()["source_ids"], ["a", "b"])
        self.assertEqual(feature.input_hash, "e0c335180cc462375627c3db5e9d889c8c1ade2c64f37cb055cadff3c60588f7")
        with self.assertRaisesRegex(ContractError, "available_at cannot be after as_of_at"):
            replace(feature, available_at="2026-08-20T23:00:00Z")


if __name__ == "__main__":
    unittest.main()
