"""Risk 3자 토론(aggressive/conservative/neutral)과 Portfolio Manager(Risk Judge)를 검증한다."""
from __future__ import annotations

import json
import unittest

from investment_agent.trading.decision.llm.agents import risk_debate
from investment_agent.trading.decision.llm.agents.graph_state import AnalystReports, RiskDebateState


class _ScriptedClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies[len(self.calls) - 1]


class RiskDebateTest(unittest.TestCase):
    def test_default_max_rounds_runs_three_turns_in_order(self):
        client = _ScriptedClient([
            {"argument": "aggressive turn"},
            {"argument": "conservative turn"},
            {"argument": "neutral turn"},
        ])
        state = risk_debate.run_risk_debate(client, reports=AnalystReports(), trader_plan="plan text")
        self.assertEqual(
            [c["task_name"] for c in client.calls],
            [
                "tradingagents_aggressive_debator",
                "tradingagents_conservative_debator",
                "tradingagents_neutral_debator",
            ],
        )
        self.assertEqual(state.count, 3)
        self.assertIn("aggressive turn", state.aggressive_history)
        self.assertIn("conservative turn", state.conservative_history)
        self.assertIn("neutral turn", state.neutral_history)
        self.assertEqual(state.latest_speaker, "neutral")

    def test_prompt_carries_trader_plan_and_20_day_horizon(self):
        client = _ScriptedClient([
            {"argument": "aggressive turn"},
            {"argument": "conservative turn"},
            {"argument": "neutral turn"},
        ])
        risk_debate.run_risk_debate(client, reports=AnalystReports(), trader_plan="plan text")
        system = client.calls[0]["system"]
        self.assertIn("20거래일", system)
        payload = json.loads(client.calls[0]["user"])
        self.assertEqual(payload["trader_plan"], "plan text")

    def test_max_rounds_two_runs_six_turns(self):
        client = _ScriptedClient([{"argument": f"turn {i}"} for i in range(6)])
        state = risk_debate.run_risk_debate(
            client, reports=AnalystReports(), trader_plan="plan text", max_rounds=2
        )
        self.assertEqual(state.count, 6)
        self.assertEqual(len(client.calls), 6)


class PortfolioManagerTest(unittest.TestCase):
    def test_final_trade_decision_carries_stance_and_decision_text(self):
        client = _ScriptedClient([{"stance": "bullish", "decision": "final call"}])
        state = RiskDebateState(history="Aggressive: x\nConservative: y\nNeutral: z", count=3)
        result_state, final_trade_decision = risk_debate.run_portfolio_manager(
            client, reports=AnalystReports(), trader_plan="plan text", state=state,
        )
        self.assertEqual(client.calls[0]["task_name"], "tradingagents_portfolio_manager")
        self.assertIn("bullish", result_state.judge_decision)
        self.assertEqual(result_state.latest_speaker, "Judge")
        self.assertIn("final call", final_trade_decision)


if __name__ == "__main__":
    unittest.main()
