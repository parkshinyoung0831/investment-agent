from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from investment_agent.trading.evidence.cache import ExternalContent, LocalEvidenceCache, canonicalize_url


class LocalEvidenceCacheTest(unittest.TestCase):
    def _item(
        self,
        fetched_at: datetime,
        *,
        url: str,
        content: str = "same story",
        symbol: str = "AAPL",
    ) -> ExternalContent:
        return ExternalContent(
            provider="free-provider", content_type="news", symbol=symbol,
            published_at=(fetched_at - timedelta(minutes=5)).isoformat(),
            fetched_at=fetched_at.isoformat(), url=url, title="title", content=content,
        )

    def test_canonical_url_and_content_deduplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = LocalEvidenceCache(Path(temp) / "cache.duckdb")
            now = datetime.now(timezone.utc)
            first = cache.store([self._item(now, url="https://EXAMPLE.com/a?utm_source=x")])
            second = cache.store([self._item(now, url="https://example.com/a#section")])
            self.assertEqual(first, second)
            self.assertEqual(cache.count(), 1)
            self.assertEqual(canonicalize_url("https://EXAMPLE.com/a?utm_source=x#x"), "https://example.com/a")

    def test_store_keeps_one_row_per_article(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = LocalEvidenceCache(Path(temp) / "cache.duckdb")
            now = datetime.now(timezone.utc)
            cache.store([
                self._item(now, url="https://example.com/a", content="first story"),
                self._item(now, url="https://example.com/b", content="second story"),
            ])
            self.assertEqual(cache.count(), 2)

    def test_request_payload_round_trips_until_it_expires(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = LocalEvidenceCache(Path(temp) / "cache.duckdb")
            old = datetime(2026, 1, 1, tzinfo=timezone.utc)
            cache.remember_request("request", "## raw blob", cached_at=old.isoformat(), ttl_hours=1)
            self.assertEqual(cache.get_request("request", now=old + timedelta(minutes=30)), "## raw blob")
            self.assertIsNone(cache.get_request("request", now=old + timedelta(hours=2)))

    def test_request_payload_does_not_need_a_stored_article(self):
        """blob replay와 기사 데이터셋은 서로 독립이다 — 못 쪼갠 응답도 캐시된다."""
        with tempfile.TemporaryDirectory() as temp:
            cache = LocalEvidenceCache(Path(temp) / "cache.duckdb")
            now = datetime.now(timezone.utc)
            cache.remember_request("request", "unparseable", cached_at=now.isoformat())
            self.assertEqual(cache.count(), 0)
            self.assertEqual(cache.get_request("request", now=now), "unparseable")

    def test_ninety_day_retention_clears_articles_and_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = LocalEvidenceCache(Path(temp) / "cache.duckdb", retention_days=90)
            old = datetime(2026, 1, 1, tzinfo=timezone.utc)
            cache.store([self._item(old, url="https://example.com/old")])
            cache.remember_request("request", "blob", cached_at=old.isoformat(), ttl_hours=1)
            result = cache.cleanup(now=old + timedelta(days=91))
            self.assertEqual(result, {"requests_removed": 1, "content_removed": 1})
            self.assertEqual(cache.count(), 0)

    def test_iter_contents_returns_rows_for_event_extraction(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = LocalEvidenceCache(Path(temp) / "cache.duckdb")
            now = datetime(2026, 3, 1, tzinfo=timezone.utc)
            cache.store([
                self._item(now, url="https://example.com/a", content="apple story", symbol="AAPL"),
                self._item(now, url="https://example.com/b", content="msft story", symbol="MSFT"),
                self._item(now - timedelta(days=40), url="https://example.com/c", content="stale", symbol="AAPL"),
            ])

            rows = cache.iter_contents(symbols=["AAPL"], since=(now - timedelta(days=7)).isoformat())

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["symbol"], "AAPL")
            self.assertEqual(rows[0]["content"], "apple story")
            self.assertIsInstance(rows[0]["metadata"], dict)

    def test_iter_contents_without_filters_returns_every_row(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = LocalEvidenceCache(Path(temp) / "cache.duckdb")
            now = datetime(2026, 3, 1, tzinfo=timezone.utc)
            cache.store([
                self._item(now, url="https://example.com/a", content="one"),
                self._item(now, url="https://example.com/b", content="two"),
            ])

            self.assertEqual(len(cache.iter_contents()), 2)


if __name__ == "__main__":
    unittest.main()
