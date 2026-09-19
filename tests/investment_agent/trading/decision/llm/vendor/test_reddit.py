"""Reddit RSS 검색 fetcher가 포맷·재시도·크립토 심볼 처리를 지키는지 검증한다(네트워크 없음)."""
from __future__ import annotations

import unittest
from urllib.error import HTTPError

from investment_agent.trading.decision.llm.vendor.reddit import fetch_reddit_posts

_ATOM_ONE_ENTRY = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>AAPL earnings beat</title>
    <published>2026-09-16T10:00:00Z</published>
    <content type="html">&lt;!-- SC_OFF --&gt;Great quarter&lt;!-- SC_ON --&gt;</content>
  </entry>
</feed>
"""

_ATOM_EMPTY = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>
"""


class FetchRedditPostsTest(unittest.TestCase):
    def test_formats_a_post_from_one_subreddit(self):
        result = fetch_reddit_posts(
            "AAPL", subreddits=("stocks",), inter_request_delay=0,
            http_get=lambda url, headers, timeout: _ATOM_ONE_ENTRY,
            sleep=lambda seconds: None,
        )
        self.assertIn("r/stocks", result)
        self.assertIn("AAPL earnings beat", result)
        self.assertIn("Great quarter", result)

    def test_no_posts_anywhere_returns_placeholder(self):
        result = fetch_reddit_posts(
            "AAPL", subreddits=("stocks", "investing"), inter_request_delay=0,
            http_get=lambda url, headers, timeout: _ATOM_EMPTY,
            sleep=lambda seconds: None,
        )
        self.assertIn("no Reddit posts found mentioning AAPL", result)

    def test_crypto_ticker_searches_by_base_symbol(self):
        seen_urls = []

        def _capture(url, headers, timeout):
            seen_urls.append(url)
            return _ATOM_EMPTY

        fetch_reddit_posts(
            "BTC-USD", subreddits=("stocks",), inter_request_delay=0,
            http_get=_capture, sleep=lambda seconds: None,
        )
        self.assertIn("q=BTC", seen_urls[0])

    def test_429_retries_once_then_succeeds(self):
        calls = {"n": 0}
        slept = []

        def _flaky(url, headers, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                raise HTTPError(url, 429, "too many requests", {"Retry-After": "1"}, None)
            return _ATOM_ONE_ENTRY

        result = fetch_reddit_posts(
            "AAPL", subreddits=("stocks",), inter_request_delay=0,
            http_get=_flaky, sleep=slept.append,
        )
        self.assertEqual(calls["n"], 2)
        self.assertEqual(slept, [1.0])
        self.assertIn("AAPL earnings beat", result)

    def test_network_failure_degrades_to_no_posts_for_that_subreddit_not_an_exception(self):
        def _boom(url, headers, timeout):
            raise OSError("connection reset")

        result = fetch_reddit_posts(
            "AAPL", subreddits=("stocks",), inter_request_delay=0,
            http_get=_boom, sleep=lambda seconds: None,
        )
        self.assertIn("no Reddit posts found mentioning AAPL", result)


if __name__ == "__main__":
    unittest.main()
