"""역할 호출들이 같은 접두부로 시작하는가 — 아니면 provider의 prompt cache가 한 번도 걸리지 않는다.

cache는 요청의 첫 토큰부터 같은 접두부에만 걸린다. 판단 역할이 5개 리포트를 싣는데,
역할마다 다른 지시가 앞에 오면 리포트가 같아도 적중이 0이다.
"""
from __future__ import annotations

import unittest

from investment_agent.trading.decision.agents import orchestrator
from investment_agent.trading.decision.agents.graph_state import AnalystReports, shared_context
from investment_agent.trading.decision.llm.client import OpenAICompatibleClient

_ROLE_TASKS = {"tradingagents_investment_committee"}


class _RecordingClient:
    def __init__(self):
        self.calls: list[dict] = []

    def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        name = kwargs["task_name"]
        if name.endswith("_analyst"):
            return {"report": f"{name} 리포트 본문"}
        return {"bull_case": "b", "bear_case": "r", "stance": "neutral", "decision": "decision"}


class SharedPrefixTest(unittest.TestCase):
    def _graph_calls(self) -> list[dict]:
        client = _RecordingClient()
        orchestrator.run_compact_graph(
            client, ticker="AAPL", curr_date="2026-09-16",
            fetch_market_evidence=lambda: "m", fetch_fundamentals_evidence=lambda: "f",
            fetch_news_evidence=lambda: "n", fetch_sentiment_evidence=lambda: "s",
            fetch_macro_evidence=lambda: "mc",
        )
        return [call for call in client.calls if call["task_name"] in _ROLE_TASKS]

    def test_every_role_call_starts_with_the_same_context(self):
        calls = self._graph_calls()
        self.assertEqual(_ROLE_TASKS, {call["task_name"] for call in calls})
        contexts = {call.get("context") for call in calls}
        self.assertEqual(1, len(contexts))
        self.assertIn("tradingagents_market_analyst 리포트 본문", contexts.pop())

    def test_reports_are_not_sent_twice(self):
        """리포트는 접두부에 한 번. 역할 payload에 또 실으면 절감이 입력 증가로 바뀐다."""
        for call in self._graph_calls():
            self.assertNotIn("리포트 본문", call["user"], call["task_name"])

    def test_the_context_does_not_depend_on_the_role(self):
        reports = AnalystReports(market_report="m", news_report="n")
        self.assertEqual(shared_context(reports), shared_context(AnalystReports(market_report="m", news_report="n")))
        self.assertIn("20거래일", shared_context(reports))


class ClientLayoutTest(unittest.TestCase):
    def _client(self) -> OpenAICompatibleClient:
        return OpenAICompatibleClient(base_url="https://example.com/v1", model="gpt-5-mini")

    def test_context_is_the_first_message_and_the_role_instruction_follows(self):
        payload = self._client().build_payload(system="역할 지시", user='{"x":1}', schema_text="{}", context="공유 접두부")
        first, second = payload["messages"]
        self.assertEqual({"role": "system", "content": "공유 접두부"}, first)
        self.assertTrue(second["content"].startswith("역할 지시\n\n"))
        self.assertIn('{"x":1}', second["content"])

    def test_without_context_the_layout_is_unchanged(self):
        payload = self._client().build_payload(system="역할 지시", user="u", schema_text="{}")
        self.assertEqual({"role": "system", "content": "역할 지시"}, payload["messages"][0])


if __name__ == "__main__":
    unittest.main()
