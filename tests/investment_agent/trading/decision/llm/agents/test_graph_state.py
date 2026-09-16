"""로컬 그래프 상태(토론 라운드 진행 규칙)가 계약대로 도는지 검증한다."""
from __future__ import annotations

import unittest

from investment_agent.trading.decision.llm.agents.graph_state import (
    InvestDebateState,
    RiskDebateState,
    debate_next_speaker,
    risk_next_speaker,
)


class DebateNextSpeakerTest(unittest.TestCase):
    def test_bull_speaks_first(self):
        self.assertEqual(debate_next_speaker(InvestDebateState()), "bull")

    def test_bear_follows_bull(self):
        state = InvestDebateState(last_speaker="bull", count=1)
        self.assertEqual(debate_next_speaker(state), "bear")

    def test_bull_follows_bear(self):
        state = InvestDebateState(last_speaker="bear", count=1)
        self.assertEqual(debate_next_speaker(state), "bull")

    def test_stops_after_two_exchanges_by_default(self):
        state = InvestDebateState(last_speaker="bear", count=2)
        self.assertIsNone(debate_next_speaker(state))

    def test_max_rounds_scales_total_exchanges(self):
        state = InvestDebateState(last_speaker="bear", count=2)
        self.assertEqual(debate_next_speaker(state, max_rounds=2), "bull")
        state = InvestDebateState(last_speaker="bull", count=4)
        self.assertIsNone(debate_next_speaker(state, max_rounds=2))


class RiskNextSpeakerTest(unittest.TestCase):
    def test_aggressive_speaks_first(self):
        self.assertEqual(risk_next_speaker(RiskDebateState()), "aggressive")

    def test_rotation_is_aggressive_conservative_neutral(self):
        state = RiskDebateState(latest_speaker="aggressive", count=1)
        self.assertEqual(risk_next_speaker(state), "conservative")
        state = RiskDebateState(latest_speaker="conservative", count=2)
        self.assertEqual(risk_next_speaker(state), "neutral")

    def test_stops_after_three_exchanges_by_default(self):
        state = RiskDebateState(latest_speaker="neutral", count=3)
        self.assertIsNone(risk_next_speaker(state))

    def test_max_rounds_scales_total_exchanges(self):
        state = RiskDebateState(latest_speaker="neutral", count=3)
        self.assertEqual(risk_next_speaker(state, max_rounds=2), "aggressive")


if __name__ == "__main__":
    unittest.main()
