"""사건 추출은 근거 캐시뿐 아니라 스케줄 수집 archive도 읽는다(IN-5·6)."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from investment_agent.intelligence.application import collect_news
from investment_agent.intelligence.evidence_cache import LocalEvidenceCache
from investment_agent.intelligence.repository import IntelligenceRepository
from investment_agent.research.commands.build_events import build_events

AS_OF = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


class _Store:
    def __init__(self) -> None:
        self.events: list = []
        self.snapshots: list = []

    def save_events(self, events) -> None:
        self.events.extend(events)

    def save_event_features(self, snapshots) -> None:
        self.snapshots.extend(snapshots)


def _payload(suffix: str, title: str) -> dict:
    return {"link": f"https://example.com/{suffix}", "title": title, "summary": f"{title} — details on {suffix}",
            "publisher": "Wire", "providerPublishTime": (AS_OF - timedelta(days=1)).timestamp()}


class ArchiveFeedsEventsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.cache = LocalEvidenceCache(root / "cache.duckdb")
        self.archive = IntelligenceRepository(root / "intelligence.duckdb")
        # 수집 archive: 한 기사를 두 종목이 언급한다(AAPL을 조회하니 MSFT 기사도 함께 왔다).
        self.now = AS_OF - timedelta(hours=2)
        collect_news.collect_news(
            repository=self.archive,
            fetch=lambda ticker: [_payload("shared", "Apple and Microsoft announce lawsuit settlement")],
            tickers=["AAPL", "MSFT"], now=self.now,
        )

    def _events(self, **kwargs) -> tuple[dict, _Store]:
        store = _Store()
        result = build_events(cache=self.cache, store=store, as_of_at=AS_OF.isoformat(),
                              tickers=("AAPL", "MSFT"), **kwargs)
        return result, store

    def test_without_the_archive_only_the_cache_is_read(self) -> None:
        result, _ = self._events()
        self.assertEqual(result["rows_read"], 0)

    def test_scheduled_collection_reaches_the_event_features(self) -> None:
        result, store = self._events(archive=self.archive)
        self.assertGreater(result["rows_from_archive"], 0)
        self.assertEqual(result["rows_from_cache"], 0)
        self.assertTrue(store.events)

    def test_one_article_mentioning_two_tickers_yields_a_row_per_ticker(self) -> None:
        rows = self.archive.event_contents(since=(AS_OF - timedelta(days=7)).isoformat(), until=AS_OF.isoformat())
        self.assertEqual(sorted(row["symbol"] for row in rows), ["AAPL", "MSFT"])
        self.assertEqual(len({row["item_id"] for row in rows}), 2)

    def test_articles_first_seen_after_the_cutoff_are_not_read(self) -> None:
        early = (AS_OF - timedelta(days=3)).isoformat()
        self.assertEqual(self.archive.event_contents(since=(AS_OF - timedelta(days=10)).isoformat(), until=early), ())

    def test_an_article_present_in_both_sources_is_counted_once(self) -> None:
        from investment_agent.intelligence.evidence_cache import ExternalContent

        title = "Apple and Microsoft announce lawsuit settlement"
        self.cache.store([ExternalContent(
            provider="yfinance", content_type="news", symbol="AAPL", published_at=self.now.isoformat(),
            fetched_at=self.now.isoformat(), url="https://example.com/shared", title=title,
            content=f"{title} — details on shared", source="Wire",
        )])
        result, _ = self._events(archive=self.archive)
        self.assertEqual(result["rows_deduplicated"], 1)  # AAPL의 같은 기사 한 건이 중복

    def test_the_same_article_from_both_sources_is_kept_once_per_ticker(self) -> None:
        from investment_agent.research.commands.build_events import _distinct
        from investment_agent.research.features.event_intelligence import normalize_content

        def row(item_id, ticker):
            return {"item_id": item_id, "provider": "yfinance", "content_type": "news", "symbol": ticker,
                    "published_at": "2026-09-20T00:00:00+00:00", "fetched_at": "2026-09-20T01:00:00+00:00",
                    "title": "Same headline", "content": "Same body text"}

        items = [normalize_content(row("cache-1", "AAPL")), normalize_content(row("archive-1|AAPL", "AAPL")),
                 normalize_content(row("archive-1|MSFT", "MSFT"))]
        kept = _distinct(items)
        self.assertEqual(sorted(item.ticker for item in kept), ["AAPL", "MSFT"])
        self.assertEqual(kept[0].item_id, "cache-1")  # 먼저 온 근거 캐시 행이 남는다


if __name__ == "__main__":
    unittest.main()
