"""90일 보존 경계. 기준 시각은 수집 시각이 아니라 발행 시각이다."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from investment_agent.intelligence.application import retention
from investment_agent.intelligence.domain.models import (
    EntityMention,
    NewsArticleRecord,
    SocialPostRecord,
)
from investment_agent.intelligence.repository import IntelligenceRepository

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)


def _article(suffix: str, *, age_days: int) -> NewsArticleRecord:
    published = NOW - timedelta(days=age_days)
    return NewsArticleRecord(
        article_id=f"article-{suffix}",
        provider="yfinance",
        source_name=None,
        canonical_url=f"https://example.com/{suffix}",
        url_hash=f"url-{suffix}",
        title=f"title {suffix}",
        summary=None,
        content_hash=f"content-{suffix}",
        published_at=published,
        available_at=None,
        first_seen_at=NOW,
        collected_at=NOW,
    )


def _post(suffix: str, *, age_days: int) -> SocialPostRecord:
    posted = NOW - timedelta(days=age_days)
    return SocialPostRecord(
        post_id=f"post-{suffix}",
        platform="reddit",
        channel="wallstreetbets",
        native_id=f"native-{suffix}",
        author_hash=f"author-{suffix}",
        title=f"title {suffix}",
        body=f"body {suffix}",
        permalink=f"https://example.com/{suffix}",
        score=1,
        num_comments=0,
        flair=None,
        posted_at=posted,
        available_at=None,
        first_seen_at=NOW,
        collected_at=NOW,
        content_hash=f"content-{suffix}",
    )


class RetentionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = IntelligenceRepository(Path(self._tmp.name) / "intelligence.duckdb")

    def test_boundary_keeps_89_and_90_and_drops_91(self) -> None:
        self.repo.store_news([
            _article("d89", age_days=89),
            _article("d90", age_days=90),
            _article("d91", age_days=91),
        ])
        result = retention.prune(self.repo, now=NOW)
        self.assertEqual(1, result.news)
        remaining = {row["article_id"] for row in self.repo.recent_news(limit=10)}
        self.assertEqual({"article-d89", "article-d90"}, remaining)

    def test_mentions_of_deleted_parents_are_removed(self) -> None:
        self.repo.store_news([_article("old", age_days=100), _article("fresh", age_days=1)])
        self.repo.store_mentions([
            EntityMention(
                mention_id="m-old", source_kind="news", source_id="article-old",
                ticker="AAPL", match_kind="queried", confidence=1.0,
                observed_at=NOW - timedelta(days=100),
                first_seen_at=NOW - timedelta(days=100),
            ),
            EntityMention(
                mention_id="m-fresh", source_kind="news", source_id="article-fresh",
                ticker="AAPL", match_kind="queried", confidence=1.0,
                observed_at=NOW - timedelta(days=1),
                first_seen_at=NOW - timedelta(days=1),
            ),
        ])
        result = retention.prune(self.repo, now=NOW)
        self.assertEqual(1, result.mentions)
        counts = self.repo.mention_counts(since="2000-01-01", limit=10)
        self.assertEqual(1, counts[0]["mention_count"])

    def test_prune_is_recorded_as_a_run(self) -> None:
        self.repo.store_news([_article("old", age_days=200)])
        retention.prune(self.repo, now=NOW)
        runs = [row for row in self.repo.recent_runs(limit=10) if row["kind"] == "prune"]
        self.assertEqual(1, len(runs))
        self.assertEqual(1, runs[0]["deleted_count"])

    def test_collected_at_does_not_extend_retention(self) -> None:
        """오래된 글을 오늘 수집해도 오래된 글이다."""
        stale = _article("stale", age_days=120)
        stale.first_seen_at = NOW
        stale.collected_at = NOW
        self.repo.store_news([stale])
        self.assertEqual(1, retention.prune(self.repo, now=NOW).news)

    def test_mention_deletion_is_scoped_by_source_kind(self) -> None:
        """source_id만으로 지우면 보존 기간 안의 mention이 함께 사라진다.

        news와 social의 id 문자열 공간은 서로 disjoint하다는 보장이 없다.
        신선한 social 글과 오래된 news 글이 우연히 같은 id를 쓸 때,
        source_kind로 갈라 지우지 않으면 신선한 social mention까지 지워진다.
        """
        shared_id = "shared-id"
        stale_news = _article("stale", age_days=91)
        stale_news.article_id = shared_id
        fresh_post = _post("fresh", age_days=1)
        fresh_post.post_id = shared_id
        self.repo.store_news([stale_news])
        self.repo.store_social([fresh_post])
        self.repo.store_mentions([
            EntityMention(
                mention_id="m-news", source_kind="news", source_id=shared_id,
                ticker="AAPL", match_kind="queried", confidence=1.0,
                observed_at=NOW - timedelta(days=91),
                first_seen_at=NOW - timedelta(days=91),
            ),
            EntityMention(
                mention_id="m-social", source_kind="social", source_id=shared_id,
                ticker="MSFT", match_kind="queried", confidence=1.0,
                observed_at=NOW - timedelta(days=1),
                first_seen_at=NOW - timedelta(days=1),
            ),
        ])
        result = retention.prune(self.repo, now=NOW)
        self.assertEqual(1, result.mentions)
        counts = {
            row["ticker"]: row["mention_count"]
            for row in self.repo.mention_counts(since="2000-01-01", limit=10)
        }
        self.assertEqual({"MSFT": 1}, counts)

    def test_pruning_news_leaves_fresh_social_alone(self) -> None:
        """뉴스와 소셜이 한 색인을 쓰므로, 정리 조회를 종류로 좁히지 않으면
        뉴스 차례에 소셜 행까지 지운다 — 개수는 0으로 보고되면서."""
        self.repo.store_news([_article("stale", age_days=120)])
        self.repo.store_social([_post("fresh", age_days=1)])

        result = retention.prune(self.repo, now=NOW)

        self.assertEqual(1, result.news)
        self.assertEqual(0, result.social)
        self.assertEqual(
            {"post-fresh"}, {row["post_id"] for row in self.repo.recent_social(limit=10)}
        )

    def test_pruning_social_leaves_fresh_news_alone(self) -> None:
        self.repo.store_news([_article("fresh", age_days=1)])
        self.repo.store_social([_post("stale", age_days=120)])

        result = retention.prune(self.repo, now=NOW)

        self.assertEqual(0, result.news)
        self.assertEqual(1, result.social)
        self.assertEqual(
            {"article-fresh"}, {row["article_id"] for row in self.repo.recent_news(limit=10)}
        )


if __name__ == "__main__":
    unittest.main()
