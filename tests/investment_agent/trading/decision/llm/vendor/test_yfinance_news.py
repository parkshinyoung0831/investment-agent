"""yfinance 종목 뉴스 fetcher가 시점 창 필터링과 포맷을 지키는지 검증한다(네트워크 없음)."""
from __future__ import annotations

import unittest

from investment_agent.trading.decision.llm.vendor.yfinance_news import get_news_yfinance


class _FakeTicker:
    def __init__(self, articles):
        self._articles = articles

    def get_news(self, count):
        return self._articles[:count]


def _flat_article(title: str, epoch_seconds: int, *, publisher: str = "Zacks", link: str = "https://x/"):
    return {
        "title": title,
        "summary": f"{title} summary",
        "publisher": publisher,
        "link": link,
        "providerPublishTime": epoch_seconds,
    }


class GetNewsYfinanceTest(unittest.TestCase):
    def test_returns_no_news_message_when_ticker_has_none(self):
        result = get_news_yfinance(
            "AAPL", "2026-09-01", "2026-09-16", ticker_factory=lambda symbol: _FakeTicker([]),
        )
        self.assertIn("No news found for AAPL", result)

    def test_formats_articles_within_the_window(self):
        import calendar
        from datetime import datetime, timezone

        in_window = int(calendar.timegm(datetime(2026, 9, 10, tzinfo=timezone.utc).timetuple()))
        out_of_window = int(calendar.timegm(datetime(2026, 1, 1, tzinfo=timezone.utc).timetuple()))
        articles = [
            _flat_article("Apple beats on services revenue", in_window),
            _flat_article("Old news from January", out_of_window),
        ]
        result = get_news_yfinance(
            "AAPL", "2026-09-01", "2026-09-16",
            ticker_factory=lambda symbol: _FakeTicker(articles),
        )
        self.assertIn("Apple beats on services revenue", result)
        self.assertNotIn("Old news from January", result)
        self.assertIn("Link: https://x/", result)

    def test_resolves_broker_alias_and_notes_it_in_the_header(self):
        result = get_news_yfinance(
            "XAUUSD", "2026-09-01", "2026-09-16", ticker_factory=lambda symbol: _FakeTicker([]),
        )
        self.assertIn("resolved to GC=F", result)

    def test_exceptions_are_reported_not_raised(self):
        def _broken_factory(symbol):
            raise RuntimeError("network down")

        result = get_news_yfinance("AAPL", "2026-09-01", "2026-09-16", ticker_factory=_broken_factory)
        self.assertIn("Error fetching news for AAPL", result)


if __name__ == "__main__":
    unittest.main()
