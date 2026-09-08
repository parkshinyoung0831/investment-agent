"""provider 응답 blob을 기사 단위 ExternalContent로 쪼개는 파서 테스트."""
from __future__ import annotations

import unittest

from investment_agent.trading.decision.llm.agents.external_parsing import parse_external_payload

FETCHED_AT = "2026-09-03T00:00:00+00:00"

YFINANCE_TICKER_NEWS = """## CF News, from 2026-08-26 to 2026-09-02:

### CF Shares Up 15% in 3 Months: Here's What's Driving the Upside (source: Zacks)
CF Industries has rallied 14.6% in three months, fueled by strong nitrogen demand.
Link: https://finance.yahoo.com/markets/stocks/articles/cf-shares-15-3-months-120600755.html

### CF Industries & Partners Break Ground on Low-Carbon Ammonia Plant (source: Zacks)
CF begins construction of the $3.7B Blue Point One ammonia plant.
Link: https://finance.yahoo.com/energy/articles/cf-industries-partners-break-ground-155100036.html

### Fertilizer Giants Ready New Plants (source: The Wall Street Journal)
Link: https://www.wsj.com/livecoverage/card/fertilizer-giants-6BLC0PQ8?siteid=yhoof2

"""


class YFinanceNewsParsingTest(unittest.TestCase):
    def test_splits_markdown_blob_into_one_item_per_article(self) -> None:
        items = parse_external_payload(
            domain="news",
            provider="yfinance",
            request={"ticker": "CF", "start_date": "2026-08-26", "end_date": "2026-09-02"},
            raw=YFINANCE_TICKER_NEWS,
            fetched_at=FETCHED_AT,
        )

        self.assertEqual(len(items), 3)
        first = items[0]
        self.assertEqual(first.title, "CF Shares Up 15% in 3 Months: Here's What's Driving the Upside")
        self.assertEqual(first.source, "Zacks")
        self.assertEqual(first.symbol, "CF")
        self.assertEqual(first.content_type, "news")
        self.assertEqual(
            first.url,
            "https://finance.yahoo.com/markets/stocks/articles/cf-shares-15-3-months-120600755.html",
        )
        self.assertIn("rallied 14.6%", first.content)

    def test_article_without_summary_keeps_the_headline_as_content(self) -> None:
        items = parse_external_payload(
            domain="news",
            provider="yfinance",
            request={"ticker": "CF"},
            raw=YFINANCE_TICKER_NEWS,
            fetched_at=FETCHED_AT,
        )

        third = items[2]
        self.assertEqual(third.title, "Fertilizer Giants Ready New Plants")
        self.assertEqual(third.content, "Fertilizer Giants Ready New Plants")


STOCKTWITS = """Bullish: 8 (27%) · Bearish: 0 (0%) · Unlabeled: 22 · Total: 30 most-recent messages

[2026-09-02T16:09:43Z · @Dr_Stoxx · no-label] $CF +68.5% rather...
[2026-09-01T17:48:31Z · @NeverFadeTheOracle · Bullish] $CF Moving
[2026-08-30T20:38:47Z · @Shiftseer · Bearish] CF Industries $CF closed below the neckline.
second line of the same message
"""


class StockTwitsParsingTest(unittest.TestCase):
    def test_splits_one_item_per_message_with_author_and_time(self) -> None:
        items = parse_external_payload(
            domain="social",
            provider="stocktwits",
            request={"ticker": "CF", "limit": 30},
            raw=STOCKTWITS,
            fetched_at=FETCHED_AT,
        )

        self.assertEqual(len(items), 3)
        self.assertEqual(items[0].author, "Dr_Stoxx")
        self.assertEqual(items[0].published_at, "2026-09-02T16:09:43+00:00")
        self.assertEqual(items[0].content_type, "social")
        self.assertEqual(items[0].symbol, "CF")
        self.assertIsNone(items[0].sentiment)

    def test_maps_bullish_and_bearish_tags_to_sentiment(self) -> None:
        items = parse_external_payload(
            domain="social",
            provider="stocktwits",
            request={"ticker": "CF"},
            raw=STOCKTWITS,
            fetched_at=FETCHED_AT,
        )

        self.assertEqual(items[1].sentiment, 1.0)
        self.assertEqual(items[2].sentiment, -1.0)

    def test_message_published_after_the_fetch_drops_its_timestamp(self) -> None:
        items = parse_external_payload(
            domain="social",
            provider="stocktwits",
            request={"ticker": "CF"},
            raw=STOCKTWITS,
            fetched_at="2026-08-31T00:00:00+00:00",
        )

        self.assertIsNone(items[0].published_at)
        self.assertEqual(items[2].published_at, "2026-08-30T20:38:47+00:00")

    def test_continuation_line_stays_with_its_message(self) -> None:
        items = parse_external_payload(
            domain="social",
            provider="stocktwits",
            request={"ticker": "CF"},
            raw=STOCKTWITS,
            fetched_at=FETCHED_AT,
        )

        self.assertIn("second line of the same message", items[2].content)


REDDIT = """r/wallstreetbets — 2 recent posts mentioning CF:
  [2026-09-01 ·   12↑ ·   3c] Fertilizer names are ripping
    body excerpt: nitrogen spreads look tight into Q4
  [2026-08-30 ·    4↑ ·   0c] CF earnings recap

r/stocks: <no posts found mentioning CF in the past 7 days>
"""


class RedditParsingTest(unittest.TestCase):
    def test_splits_one_item_per_post_with_its_date(self) -> None:
        items = parse_external_payload(
            domain="social",
            provider="reddit",
            request={"ticker": "CF"},
            raw=REDDIT,
            fetched_at=FETCHED_AT,
        )

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].published_at, "2026-09-01T00:00:00+00:00")
        self.assertIn("Fertilizer names are ripping", items[0].content)
        self.assertIn("nitrogen spreads look tight", items[0].content)
        self.assertIsNone(items[0].author)

    def test_next_subreddit_block_does_not_bleed_into_the_previous_post(self) -> None:
        items = parse_external_payload(
            domain="social",
            provider="reddit",
            request={"ticker": "CF"},
            raw=REDDIT,
            fetched_at=FETCHED_AT,
        )

        self.assertNotIn("no posts found", items[1].content)


class FallbackTest(unittest.TestCase):
    def test_unrecognised_payload_is_kept_whole_rather_than_dropped(self) -> None:
        raw = '{"feed": [{"title": "x"}]}'
        items = parse_external_payload(
            domain="news",
            provider="alpha_vantage",
            request={"ticker": "AAPL"},
            raw=raw,
            fetched_at=FETCHED_AT,
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].content, raw)
        self.assertEqual(items[0].symbol, "AAPL")

    def test_global_news_without_a_ticker_stores_no_symbol(self) -> None:
        items = parse_external_payload(
            domain="news",
            provider="yfinance",
            request={"curr_date": "2026-09-02", "look_back_days": 7},
            raw=YFINANCE_TICKER_NEWS,
            fetched_at=FETCHED_AT,
        )

        self.assertEqual(len(items), 3)
        self.assertIsNone(items[0].symbol)


if __name__ == "__main__":
    unittest.main()
