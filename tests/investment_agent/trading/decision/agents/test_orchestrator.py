"""로컬 그래프 오케스트레이터가 옛 TradingAgentsRunner.run()과 같은 dict 모양을 만드는지 검증한다."""
from __future__ import annotations

import unittest

from investment_agent.trading.decision.agents import orchestrator


class _FakeClient:
    def __init__(self):
        self.calls: list[dict] = []

    def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        name = kwargs["task_name"]
        if name.endswith("_analyst"):
            return {"report": f"{name} report"}
        if name in (
            "tradingagents_bull_researcher",
            "tradingagents_bear_researcher",
            "tradingagents_aggressive_debator",
            "tradingagents_conservative_debator",
            "tradingagents_neutral_debator",
        ):
            return {"argument": f"{name} argument"}
        if name == "tradingagents_research_manager":
            return {"stance": "bullish", "plan": "plan text"}
        if name == "tradingagents_trader":
            return {"plan": "trader plan text"}
        if name == "tradingagents_portfolio_manager":
            return {"stance": "bullish", "decision": "final decision text"}
        if name == "tradingagents_investment_committee":
            return {"bull_case": "bull text", "bear_case": "bear text", "stance": "bearish", "decision": "bear wins"}
        raise AssertionError(f"unexpected task_name {name}")


def _counting_fetcher(value: str, counts: dict, key: str):
    def fetch() -> str:
        counts[key] = counts.get(key, 0) + 1
        return value

    return fetch


class RunCompactGraphTest(unittest.TestCase):
    def _run(self, client):
        counts: dict[str, int] = {}
        return orchestrator.run_compact_graph(
            client, ticker="AAPL", curr_date="2026-09-16",
            fetch_market_evidence=_counting_fetcher("market evidence", counts, "market"),
            fetch_fundamentals_evidence=_counting_fetcher("fundamentals evidence", counts, "fundamentals"),
            fetch_news_evidence=_counting_fetcher("news evidence", counts, "news"),
            fetch_sentiment_evidence=_counting_fetcher("sentiment evidence", counts, "sentiment"),
            fetch_macro_evidence=_counting_fetcher("macro evidence", counts, "macro"),
        )

    def test_one_committee_call_follows_the_analysts(self):
        """분석가 5명 뒤 판단은 호출 1번이다(전체 그래프는 8번)."""
        client = _FakeClient()
        self._run(client)
        names = [call["task_name"] for call in client.calls]
        self.assertEqual(5, sum(name.endswith("_analyst") for name in names))
        self.assertEqual(["tradingagents_investment_committee"], [n for n in names if not n.endswith("_analyst")])

    def test_the_result_keeps_the_shape_the_structuring_call_reads(self):
        result = self._run(_FakeClient())
        self.assertEqual({
            "market_report", "sentiment_report", "news_report", "fundamentals_report", "macro_report",
            "investment_debate_state", "investment_plan", "trader_investment_plan",
            "risk_debate_state", "final_trade_decision",
        }, set(result))
        self.assertEqual("bear wins", result["final_trade_decision"])
        self.assertEqual("bearish: bear wins", result["risk_debate_state"]["judge_decision"])
        self.assertIn("Bull: bull text", result["investment_debate_state"]["history"])
        self.assertIn("Bear: bear text", result["investment_debate_state"]["history"])

if __name__ == "__main__":
    unittest.main()
