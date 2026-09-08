"""뉴스 provider의 정규화와 fail-closed 정책을 검증한다."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from investment_agent.intelligence.infrastructure.sources.news import provider
from investment_agent.reporting.readers import news as reporting_news


def _uncached(function):
    return getattr(function, "__wrapped__", function)


class NewsProviderTests(unittest.TestCase):
    def test_preserves_actual_related_tickers(self) -> None:
        item = {
            "content": {
                "title": "Apple supplier outlook",
                "summary": "Earnings outlook remains uncertain.",
                "canonicalUrl": {"url": "https://finance.example.test/story"},
                "relatedTickers": ["AAPL", "2330.TW", "invalid symbol"],
            }
        }

        row = provider._normalized_news_item(item, "AAPL")

        self.assertIsNotNone(row)
        self.assertEqual(row["related_tickers"], ["AAPL", "2330.TW"])

    def test_social_providers_are_fail_closed(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "DASHBOARD_OFFLINE": "0",
                "AI_INVESTOR_EXTERNAL_NEWS_SOCIAL": "true",
                "AI_INVESTOR_EXTERNAL_SOCIAL_VENDORS": "",
                "DASHBOARD_NEWS_PROVIDER": "reddit",
            },
            clear=False,
        ):
            result = _uncached(reporting_news.load_live_news)("markets")
            statuses = _uncached(reporting_news.provider_statuses)()

        self.assertEqual(result.status, "blocked")
        by_provider = {row["provider"]: row["status"] for row in statuses.rows}
        self.assertEqual(by_provider["reddit"], "blocked")
        self.assertEqual(by_provider["stocktwits"], "blocked")


if __name__ == "__main__":
    unittest.main()
