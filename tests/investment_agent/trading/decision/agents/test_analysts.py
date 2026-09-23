"""각 분석가 노드가 EvidenceBundle 텍스트 하나를 근거로 리포트 하나를 만드는지 검증한다."""
from __future__ import annotations

import json
import unittest

from investment_agent.trading.decision.agents import analysts


class _RecordingClient:
    def __init__(self, report: str = "report text"):
        self.report = report
        self.calls: list[dict] = []

    def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        return {"report": self.report}


class AnalystNodeTest(unittest.TestCase):
    def test_market_analyst_calls_llm_with_evidence_and_returns_report(self):
        client = _RecordingClient("market is up")
        result = analysts.run_market_analyst(
            client, ticker="AAPL", curr_date="2026-09-16", evidence_text='{"close": 100}'
        )
        self.assertEqual(result, "market is up")
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertEqual(call["task_name"], "tradingagents_market_analyst")
        payload = json.loads(call["user"])
        self.assertEqual(payload["ticker"], "AAPL")
        self.assertEqual(payload["evidence"], '{"close": 100}')

    def test_market_analyst_skips_llm_call_when_data_unavailable(self):
        client = _RecordingClient()
        sentinel = "NO_DATA_AVAILABLE: ticker/date is outside the active point-in-time bundle."
        result = analysts.run_market_analyst(
            client, ticker="AAPL", curr_date="2026-09-16", evidence_text=sentinel,
        )
        self.assertEqual(result, sentinel)
        self.assertEqual(client.calls, [])

    def test_fundamentals_analyst_task_name(self):
        client = _RecordingClient("fundamentals ok")
        analysts.run_fundamentals_analyst(client, ticker="AAPL", curr_date="2026-09-16", evidence_text="{}")
        self.assertEqual(client.calls[0]["task_name"], "tradingagents_fundamentals_analyst")

    def test_news_analyst_task_name(self):
        client = _RecordingClient("news ok")
        analysts.run_news_analyst(client, ticker="AAPL", curr_date="2026-09-16", evidence_text="{}")
        self.assertEqual(client.calls[0]["task_name"], "tradingagents_news_analyst")

    def test_sentiment_analyst_task_name(self):
        client = _RecordingClient("sentiment ok")
        analysts.run_sentiment_analyst(client, ticker="AAPL", curr_date="2026-09-16", evidence_text="{}")
        self.assertEqual(client.calls[0]["task_name"], "tradingagents_sentiment_analyst")

    def test_macro_analyst_task_name_and_skip_on_unavailable(self):
        client = _RecordingClient("macro ok")
        result = analysts.run_macro_analyst(client, ticker="AAPL", curr_date="2026-09-16", evidence_text="{}")
        self.assertEqual(result, "macro ok")
        self.assertEqual(client.calls[0]["task_name"], "tradingagents_macro_analyst")

        client2 = _RecordingClient()
        sentinel = "DATA_UNAVAILABLE: Supabase has no point-in-time evidence for this domain. Do not fabricate values."
        result2 = analysts.run_macro_analyst(
            client2, ticker="AAPL", curr_date="2026-09-16", evidence_text=sentinel,
        )
        self.assertEqual(client2.calls, [])
        self.assertEqual(result2, sentinel)


if __name__ == "__main__":
    unittest.main()


class SharedMacroReportTest(unittest.TestCase):
    """거시 근거는 종목과 무관하다 — 같은 날 같은 근거의 요약을 종목마다 다시 만들지 않는다."""

    def test_one_call_serves_every_ticker_with_the_same_evidence(self):
        client, cache = _RecordingClient("macro regime"), {}
        for ticker in ("AAPL", "MSFT", "XOM"):
            self.assertEqual("macro regime", analysts.run_macro_analyst(
                client, ticker=ticker, curr_date="2026-09-16", evidence_text='{"rate": 4.1}', cache=cache))
        self.assertEqual(1, len(client.calls))

    def test_different_evidence_or_date_is_not_shared(self):
        client, cache = _RecordingClient(), {}
        analysts.run_macro_analyst(client, ticker="AAPL", curr_date="2026-09-16", evidence_text="a", cache=cache)
        analysts.run_macro_analyst(client, ticker="AAPL", curr_date="2026-09-16", evidence_text="b", cache=cache)
        analysts.run_macro_analyst(client, ticker="AAPL", curr_date="2026-09-17", evidence_text="a", cache=cache)
        self.assertEqual(3, len(client.calls))

    def test_the_prompt_does_not_name_a_ticker(self):
        """근거에 종목 정보가 없는데 종목을 물으면 근거 밖 사전지식으로 채운다."""
        client = _RecordingClient()
        analysts.run_macro_analyst(client, ticker="AAPL", curr_date="2026-09-16", evidence_text="{}")
        self.assertNotIn("AAPL", client.calls[0]["user"])

    def test_without_a_cache_every_call_reaches_the_model(self):
        client = _RecordingClient()
        for _ in range(2):
            analysts.run_macro_analyst(client, ticker="AAPL", curr_date="2026-09-16", evidence_text="{}")
        self.assertEqual(2, len(client.calls))
