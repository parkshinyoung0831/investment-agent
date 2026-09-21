"""외부 근거의 가용 여부는 응답의 시작 문구로 가른다.

본문 전체에서 부분 문자열을 찾으면 정상 기사 안의 "services unavailable: ..." 같은 문장 하나로
뉴스 전체가 unavailable이 되어 분석가가 근거 없이 판단한다.
"""
from __future__ import annotations

import unittest

from investment_agent.trading.decision.llm import runtime


class ExternalStatusTest(unittest.TestCase):
    def test_provider_failure_sentinels_are_unavailable(self):
        for text in (
            "No news found for AAPL",
            "No news found for AAPL between 2026-09-01 and 2026-09-08",
            "Error fetching news for AAPL: timeout",
            "DATA_UNAVAILABLE: external provider daily cap exhausted",
            "<stocktwits unavailable: HTTPError>",
            "<no Reddit posts found mentioning AAPL across r/stocks in the past 7 days>",
            "<no StockTwits messages found for $AAPL>",
            "  \nno global news found",
        ):
            with self.subTest(text=text):
                self.assertEqual("unavailable", runtime._external_status(text))

    def test_a_normal_article_that_mentions_the_same_words_stays_available(self):
        for text in (
            "## AAPL News\n### Cloud outage (source: Wire)\nservices unavailable: users report errors",
            "## AAPL News\n### Analysts say no news found on the rumor; error fetching data is common",
            "Apple shares rose. DATA_UNAVAILABLE was the label in the old dashboard.",
        ):
            with self.subTest(text=text):
                self.assertEqual("available", runtime._external_status(text))


if __name__ == "__main__":
    unittest.main()
