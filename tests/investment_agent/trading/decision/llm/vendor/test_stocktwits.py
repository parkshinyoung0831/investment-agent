"""StockTwits fetcher가 메시지 포맷·감성 집계·오류 처리를 지키는지 검증한다(네트워크 없음)."""
from __future__ import annotations

import json
import unittest

from investment_agent.trading.decision.llm.vendor.stocktwits import fetch_stocktwits_messages


def _payload(messages: list[dict]) -> bytes:
    return json.dumps({"messages": messages}).encode("utf-8")


class FetchStocktwitsMessagesTest(unittest.TestCase):
    def test_summarizes_sentiment_counts_and_lists_messages(self):
        messages = [
            {
                "created_at": "2026-09-16T10:00:00Z",
                "user": {"username": "trader_one"},
                "entities": {"sentiment": {"basic": "Bullish"}},
                "body": "breaking out",
            },
            {
                "created_at": "2026-09-15T10:00:00Z",
                "user": {"username": "trader_two"},
                "entities": {"sentiment": {"basic": "Bearish"}},
                "body": "looks heavy",
            },
        ]
        result = fetch_stocktwits_messages(
            "AAPL", http_get=lambda url, headers, timeout: _payload(messages),
        )
        self.assertIn("Bullish: 1 (50%)", result)
        self.assertIn("Bearish: 1 (50%)", result)
        self.assertIn("@trader_one", result)
        self.assertIn("breaking out", result)

    def test_no_messages_returns_placeholder(self):
        result = fetch_stocktwits_messages(
            "AAPL", http_get=lambda url, headers, timeout: _payload([]),
        )
        self.assertIn("no StockTwits messages found for $AAPL", result)

    def test_network_failure_returns_placeholder_not_an_exception(self):
        import os

        def _boom(url, headers, timeout):
            raise OSError("connection reset")

        result = fetch_stocktwits_messages("AAPL", http_get=_boom)
        self.assertIn("stocktwits unavailable", result)

    def test_crypto_symbol_uses_dot_x_suffix_in_request(self):
        seen_urls = []

        def _capture(url, headers, timeout):
            seen_urls.append(url)
            return _payload([])

        fetch_stocktwits_messages("BTCUSD", http_get=_capture)
        self.assertIn("BTC.X", seen_urls[0])


if __name__ == "__main__":
    unittest.main()
