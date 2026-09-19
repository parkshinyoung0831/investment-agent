"""Trader가 Research Manager 판단을 근거로 계획 텍스트 하나를 만드는지 검증한다."""
from __future__ import annotations

import json
import unittest

from investment_agent.trading.decision.agents import trader
from investment_agent.trading.decision.agents.graph_state import AnalystReports, InvestDebateState


class _RecordingClient:
    def __init__(self, plan: str = "trader plan"):
        self.plan = plan
        self.calls: list[dict] = []

    def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        return {"plan": self.plan}


class TraderTest(unittest.TestCase):
    def test_returns_plan_from_client_and_uses_dedicated_task_name(self):
        client = _RecordingClient("go with the debate")
        debate_state = InvestDebateState(judge_decision="bullish: strong margins")
        result = trader.run_trader(client, reports=AnalystReports(), debate_state=debate_state)
        self.assertEqual(result, "go with the debate")
        self.assertEqual(client.calls[0]["task_name"], "tradingagents_trader")

    def test_prompt_carries_research_manager_decision_and_20_day_horizon(self):
        client = _RecordingClient()
        debate_state = InvestDebateState(judge_decision="bullish: strong margins")
        trader.run_trader(client, reports=AnalystReports(), debate_state=debate_state)
        system = client.calls[0]["system"]
        self.assertIn("20거래일", system)
        payload = json.loads(client.calls[0]["user"])
        self.assertEqual(payload["research_manager_decision"], "bullish: strong margins")


if __name__ == "__main__":
    unittest.main()
