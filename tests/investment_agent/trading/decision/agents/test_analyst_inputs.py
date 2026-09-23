"""분석가 입력 기록 — 분석가 단계를 같은 입력으로 다시 돌리려면 무엇을 받았는지 남아야 한다.

외부(뉴스·소셜) 원문은 보존 설정이 꺼져 있으면 저장하지 않는다(`runtime._persist_external_raw`와 같은 규칙).
"""
from __future__ import annotations

import hashlib
import json
import os
import unittest
from unittest import mock

from investment_agent.research.evidence.contracts import EvidenceBundle, EvidenceItem
from investment_agent.trading.decision.agents.engine import TradingAgentsDecisionEngine
from investment_agent.trading.decision.agents.runner import _recorded


class RecordedFetchTest(unittest.TestCase):
    def test_internal_evidence_keeps_the_text(self):
        sink: dict = {}
        self.assertEqual("market text", _recorded(sink, "market", lambda: "market text")())
        self.assertEqual("market text", sink["market"]["text"])
        self.assertEqual(hashlib.sha256(b"market text").hexdigest(), sink["market"]["sha256"])
        self.assertEqual(11, sink["market"]["chars"])

    def test_external_text_is_not_kept_unless_raw_persistence_is_on(self):
        for domain in ("news", "sentiment"):
            with self.subTest(domain=domain):
                sink: dict = {}
                with mock.patch.dict(os.environ, {"AI_INVESTOR_SAVE_EXTERNAL_RAW": "false"}):
                    _recorded(sink, domain, lambda: "headline")()
                self.assertNotIn("text", sink[domain])
                self.assertEqual(8, sink[domain]["chars"])
                with mock.patch.dict(os.environ, {"AI_INVESTOR_SAVE_EXTERNAL_RAW": "true"}):
                    _recorded(sink, domain, lambda: "headline")()
                self.assertEqual("headline", sink[domain]["text"])


def _bundle() -> EvidenceBundle:
    return EvidenceBundle(
        ticker="AAPL",
        as_of_at="2026-08-21T00:00:00+00:00",
        source_kind="live_shadow",
        evidence=(EvidenceItem(
            evidence_id="EV-MARKET-123", domain="market", source="market.prices_daily",
            observed_at="2026-08-20", available_at="2026-08-20T23:00:00+00:00",
            timing_status="known", payload={"close": 100.0},
        ),),
    )


class _Runner:
    version = "test-v1"

    def run(self, bundle, *, memory_text):
        return {"final_trade_decision": "hold", "_analyst_inputs": {"market": {"text": "SECRET-INPUT"}}}


class _Client:
    def __init__(self):
        self.users: list[str] = []

    def complete_json(self, **kwargs):
        self.users.append(kwargs["user"])
        payload = json.loads(kwargs["user"])
        return {
            "ticker": payload["ticker"], "as_of_at": payload["as_of_at"], "thesis": "neutral",
            "hard_constraint": "none", "key_risks": [], "probability_up": 0.5, "confidence": 0.5,
            "expected_excess_return": 0.0, "reasoning": ["r"], "evidence_ids": ["EV-MARKET-123"],
            "missing_data": [],
        }


class EngineCarriesAnalystInputsTest(unittest.TestCase):
    def test_inputs_reach_the_result_but_not_the_structuring_prompt(self):
        client = _Client()
        result = TradingAgentsDecisionEngine(client, _Runner()).run(_bundle(), memory_text="")
        self.assertEqual({"market": {"text": "SECRET-INPUT"}}, result.analyst_inputs)
        self.assertNotIn("SECRET-INPUT", client.users[0])
        self.assertNotIn("_analyst_inputs", result.role_outputs)


if __name__ == "__main__":
    unittest.main()
