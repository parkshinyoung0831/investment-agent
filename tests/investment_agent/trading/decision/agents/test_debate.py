"""Bull/Bear 토론과 Research Manager가 20거래일 계약대로 도는지 검증한다."""
from __future__ import annotations

import json
import unittest

from investment_agent.trading.decision.agents import debate
from investment_agent.trading.decision.agents.graph_state import AnalystReports, InvestDebateState


class _ScriptedClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies[len(self.calls) - 1]


class BullBearDebateTest(unittest.TestCase):
    def test_default_max_rounds_runs_exactly_two_turns_bull_then_bear(self):
        client = _ScriptedClient([{"argument": "bull turn"}, {"argument": "bear turn"}])
        state = debate.run_bull_bear_debate(client, reports=AnalystReports())
        self.assertEqual(
            [c["task_name"] for c in client.calls],
            ["tradingagents_bull_researcher", "tradingagents_bear_researcher"],
        )
        self.assertEqual(state.count, 2)
        self.assertIn("bull turn", state.bull_history)
        self.assertIn("bear turn", state.bear_history)
        self.assertIn("bull turn", state.history)
        self.assertIn("bear turn", state.history)

    def test_second_turn_sees_first_turn_as_opponent_argument(self):
        client = _ScriptedClient([{"argument": "bull turn"}, {"argument": "bear turn"}])
        debate.run_bull_bear_debate(client, reports=AnalystReports())
        second_call_user = json.loads(client.calls[1]["user"])
        self.assertIn("bull turn", second_call_user["opponent_last_argument"])

    def test_max_rounds_two_runs_four_turns(self):
        client = _ScriptedClient([{"argument": f"turn {i}"} for i in range(4)])
        state = debate.run_bull_bear_debate(client, reports=AnalystReports(), max_rounds=2)
        self.assertEqual(state.count, 4)
        self.assertEqual(len(client.calls), 4)

    def test_prompt_states_the_20_day_horizon_and_forbids_sizing_talk(self):
        client = _ScriptedClient([{"argument": "bull turn"}, {"argument": "bear turn"}])
        debate.run_bull_bear_debate(client, reports=AnalystReports())
        system = client.calls[0]["system"]
        self.assertIn("20거래일", system)
        self.assertIn("비중", system)


class ResearchManagerTest(unittest.TestCase):
    def test_stores_stance_and_plan_in_judge_decision(self):
        client = _ScriptedClient([{"stance": "bullish", "plan": "reasoning text"}])
        state = InvestDebateState(history="Bull: x\nBear: y", count=2)
        result = debate.run_research_manager(client, reports=AnalystReports(), state=state)
        self.assertEqual(client.calls[0]["task_name"], "tradingagents_research_manager")
        self.assertIn("bullish", result.judge_decision)
        self.assertIn("reasoning text", result.judge_decision)


if __name__ == "__main__":
    unittest.main()
