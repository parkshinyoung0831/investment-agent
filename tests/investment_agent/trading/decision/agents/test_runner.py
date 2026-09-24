"""로컬 그래프에 넘기는 뉴스 기간이 주말 사건을 잃지 않는지 검증한다."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from investment_agent.research.evidence.contracts import EvidenceBundle
from investment_agent.trading.decision.agents.runner import TradingAgentsRunner


class RunnerNewsWindowTest(unittest.TestCase):
    def test_news_window_includes_previous_week_and_never_requests_future_date(self):
        bundle = EvidenceBundle(ticker="AAPL", as_of_at="2026-09-14T13:00:00+00:00",
                                source_kind="live_shadow", evidence=(), missing_data=())
        def graph(_client, **kwargs):
            kwargs["fetch_news_evidence"]()
            return {"final_trade_decision": "neutral"}

        prefix = "investment_agent.trading.decision.agents.runner"
        with patch.dict("os.environ", {"AI_INVESTOR_LOCAL_NEWS_CACHE_ENABLED": "false",
                                       "AI_INVESTOR_TRADINGAGENTS_NEWS_VENDOR": "yfinance"}), \
                patch(prefix + ".OpenAICompatibleClient.from_env"), \
                patch(prefix + ".orchestrator.run_compact_graph", side_effect=graph), \
                patch(prefix + ".runtime.fetch_external_news", return_value="no data") as fetch:
            TradingAgentsRunner().run(bundle, memory_text="")
        self.assertEqual(fetch.call_args.args, ("AAPL", "2026-09-07", "2026-09-14"))


class RunnerGraphSelectionTest(unittest.TestCase):
    def test_the_compact_committee_graph_is_the_default_and_full_is_opt_in(self):
        with patch.dict("os.environ", {"AI_INVESTOR_AGENT_GRAPH": ""}):
            default = TradingAgentsRunner()
        self.assertEqual("compact", default.graph)
        self.assertIn("compact", default.version)
        with patch.dict("os.environ", {"AI_INVESTOR_AGENT_GRAPH": "full"}):
            self.assertEqual("full", TradingAgentsRunner().graph)
        with patch.dict("os.environ", {"AI_INVESTOR_AGENT_GRAPH": "tiny"}), self.assertRaises(ValueError):
            TradingAgentsRunner()
