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


class RunLocalGraphTest(unittest.TestCase):
    def test_returns_the_same_dict_shape_the_runner_used_to_produce(self):
        client = _FakeClient()
        counts: dict[str, int] = {}
        result = orchestrator.run_local_graph(
            client,
            ticker="AAPL",
            curr_date="2026-09-16",
            fetch_market_evidence=_counting_fetcher("market evidence", counts, "market"),
            fetch_fundamentals_evidence=_counting_fetcher("fundamentals evidence", counts, "fundamentals"),
            fetch_news_evidence=_counting_fetcher("news evidence", counts, "news"),
            fetch_sentiment_evidence=_counting_fetcher("sentiment evidence", counts, "sentiment"),
            fetch_macro_evidence=_counting_fetcher("macro evidence", counts, "macro"),
        )

        expected_keys = {
            "market_report", "sentiment_report", "news_report", "fundamentals_report", "macro_report",
            "investment_debate_state", "investment_plan", "trader_investment_plan",
            "risk_debate_state", "final_trade_decision",
        }
        self.assertEqual(set(result), expected_keys)
        self.assertEqual(len(client.calls), 13)
        self.assertEqual(result["final_trade_decision"], "final decision text")
        self.assertIsInstance(result["investment_debate_state"], dict)
        self.assertIsInstance(result["risk_debate_state"], dict)
        self.assertIn("bullish", result["investment_plan"])
        self.assertEqual(
            result["risk_debate_state"]["aggressive_history"],
            "Aggressive: tradingagents_aggressive_debator argument",
        )
        self.assertEqual(counts, {"market": 1, "fundamentals": 1, "news": 1, "sentiment": 1, "macro": 1})

    def test_max_rounds_are_forwarded_to_the_debate_stages(self):
        client = _FakeClient()
        orchestrator.run_local_graph(
            client,
            ticker="AAPL",
            curr_date="2026-09-16",
            fetch_market_evidence=lambda: "m",
            fetch_fundamentals_evidence=lambda: "f",
            fetch_news_evidence=lambda: "n",
            fetch_sentiment_evidence=lambda: "s",
            fetch_macro_evidence=lambda: "mc",
            max_debate_rounds=2,
            max_risk_discuss_rounds=2,
        )
        bull_bear_calls = [c for c in client.calls if c["task_name"] in (
            "tradingagents_bull_researcher", "tradingagents_bear_researcher",
        )]
        risk_calls = [c for c in client.calls if c["task_name"] in (
            "tradingagents_aggressive_debator",
            "tradingagents_conservative_debator",
            "tradingagents_neutral_debator",
        )]
        self.assertEqual(len(bull_bear_calls), 4)
        self.assertEqual(len(risk_calls), 6)


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

    def test_the_result_keeps_the_full_graph_shape_for_structuring(self):
        result = self._run(_FakeClient())
        full = orchestrator.run_local_graph(
            _FakeClient(), ticker="AAPL", curr_date="2026-09-16",
            fetch_market_evidence=lambda: "m", fetch_fundamentals_evidence=lambda: "f",
            fetch_news_evidence=lambda: "n", fetch_sentiment_evidence=lambda: "s", fetch_macro_evidence=lambda: "x",
        )
        self.assertEqual(set(full), set(result))
        self.assertEqual("bear wins", result["final_trade_decision"])
        self.assertEqual("bearish: bear wins", result["risk_debate_state"]["judge_decision"])
        self.assertIn("Bull: bull text", result["investment_debate_state"]["history"])
        self.assertIn("Bear: bear text", result["investment_debate_state"]["history"])


if __name__ == "__main__":
    unittest.main()
