"""구조화 호출의 토론 상태 축소 — 사본만 빼고 정보는 하나도 빼지 않는다."""
from __future__ import annotations

import unittest

from investment_agent.platform.serialization import canonical_json
from investment_agent.trading.decision.agents.engine import structuring_state


def _state() -> dict:
    bull, bear = "Bull: 매출 가속", "Bear: 마진 압박"
    agg, con, neu = "Aggressive: 상방", "Conservative: 하방", "Neutral: 균형"
    return {
        "market_report": "시장 리포트",
        "investment_debate_state": {
            "bull_history": bull, "bear_history": bear, "history": f"{bull}\n{bear}",
            "current_response": "마진 압박", "last_speaker": "bear",
            "judge_decision": "bullish: 매출이 이긴다", "count": 2,
        },
        "investment_plan": "bullish: 매출이 이긴다",
        "trader_investment_plan": "트레이더 계획",
        "risk_debate_state": {
            "aggressive_history": agg, "conservative_history": con, "neutral_history": neu,
            "history": f"{agg}\n{con}\n{neu}",
            "current_aggressive_response": "상방", "current_conservative_response": "하방",
            "current_neutral_response": "균형", "latest_speaker": "Judge",
            "judge_decision": "neutral: 최종 판단", "count": 3,
        },
        "final_trade_decision": "최종 판단",
    }


class StructuringStateTest(unittest.TestCase):
    def test_copies_are_dropped(self):
        compact = structuring_state(_state())
        self.assertNotIn("investment_plan", compact)
        self.assertNotIn("final_trade_decision", compact)
        self.assertEqual({"history", "judge_decision", "last_speaker", "count"},
                         set(compact["investment_debate_state"]))
        self.assertEqual({"history", "judge_decision", "latest_speaker", "count"},
                         set(compact["risk_debate_state"]))
        self.assertLess(len(canonical_json(compact)), len(canonical_json(_state())))

    def test_every_dropped_text_survives_in_the_compact_state(self):
        """무손실의 정의: 원래 state의 모든 문자열이 축소본 어딘가에 그대로 있다."""
        original = _state()
        text = canonical_json(structuring_state(original))

        def strings(value):
            if isinstance(value, dict):
                for item in value.values():
                    yield from strings(item)
            elif isinstance(value, str):
                yield value

        for value in strings(original):
            self.assertIn(canonical_json(value)[1:-1], text)

    def test_a_field_that_is_not_a_copy_is_kept(self):
        """history가 발언을 빠뜨린 상태라면(형식이 바뀌면) 그 발언의 유일한 사본을 지우면 안 된다."""
        state = _state()
        state["investment_debate_state"]["bull_history"] = "Bull: history에 없는 발언"
        state["final_trade_decision"] = "judge_decision과 다른 결론"
        compact = structuring_state(state)
        self.assertEqual("Bull: history에 없는 발언", compact["investment_debate_state"]["bull_history"])
        self.assertEqual("judge_decision과 다른 결론", compact["final_trade_decision"])

    def test_the_input_state_is_not_mutated(self):
        """역할 출력(대시보드·artifact)은 전체 state를 그대로 가져야 한다."""
        state = _state()
        structuring_state(state)
        self.assertEqual(_state(), state)


class EngineSendsTheCompactStateTest(unittest.TestCase):
    def test_the_structuring_prompt_carries_no_copies_but_role_outputs_keep_everything(self):
        import json

        from investment_agent.research.evidence.contracts import EvidenceBundle, EvidenceItem
        from investment_agent.trading.decision.agents.engine import TradingAgentsDecisionEngine

        class _Runner:
            version = "test-v1"

            def run(self, bundle, *, memory_text):
                return _state()

        class _Client:
            users: list[str] = []

            def complete_json(self, **kwargs):
                self.users.append(kwargs["user"])
                payload = json.loads(kwargs["user"])
                return {
                    "ticker": payload["ticker"], "as_of_at": payload["as_of_at"], "thesis": "neutral",
                    "hard_constraint": "none", "key_risks": [], "probability_up": 0.5, "confidence": 0.5,
                    "expected_excess_return": 0.0, "reasoning": ["r"], "evidence_ids": ["EV-1"],
                    "missing_data": [],
                }

        bundle = EvidenceBundle(
            ticker="AAPL", as_of_at="2026-08-21T00:00:00+00:00", source_kind="live_shadow",
            evidence=(EvidenceItem(
                evidence_id="EV-1", domain="market", source="market.prices_daily", observed_at="2026-08-20",
                available_at="2026-08-20T23:00:00+00:00", timing_status="known", payload={"close": 1.0},
            ),),
        )
        client = _Client()
        result = TradingAgentsDecisionEngine(client, _Runner()).run(bundle, memory_text="")
        sent = json.loads(client.users[0])["tradingagents_state"]
        self.assertNotIn("bull_history", sent["investment_debate_state"])
        self.assertNotIn("final_trade_decision", sent)
        self.assertIn("bull_history", result.role_outputs["investment_debate_state"])


if __name__ == "__main__":
    unittest.main()
