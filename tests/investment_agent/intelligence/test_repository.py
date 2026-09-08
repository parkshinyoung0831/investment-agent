"""intelligence.duckdb 저장 경계의 계약."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from investment_agent.intelligence.domain.models import (
    CollectionRun,
    EntityMention,
    NewsArticleRecord,
    SocialPostRecord,
)
from investment_agent.intelligence.repository import IntelligenceRepository

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)


def _article(suffix: str, *, published: datetime | None = None) -> NewsArticleRecord:
    return NewsArticleRecord(
        article_id=f"article-{suffix}",
        provider="yfinance",
        source_name="Example Wire",
        canonical_url=f"https://example.com/{suffix}",
        url_hash=f"url-{suffix}",
        title=f"title {suffix}",
        summary=None,
        content_hash=f"content-{suffix}",
        published_at=published or NOW - timedelta(days=1),
        available_at=None,
        first_seen_at=NOW,
        collected_at=NOW,
    )


def _post(suffix: str, *, posted: datetime | None = None) -> SocialPostRecord:
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
        posted_at=posted or NOW - timedelta(days=1),
        available_at=None,
        first_seen_at=NOW,
        collected_at=NOW,
        content_hash=f"content-{suffix}",
    )


class IntelligenceRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = IntelligenceRepository(Path(self._tmp.name) / "intelligence.duckdb")

    def test_failed_catalog_commit_never_exposes_orphan_parquet(self):
        self.repo.store_news([_article("original")])
        refresh = self.repo._refresh_content_views
        calls = 0
        def fail_on_publish(connection):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("injected catalog failure")
            return refresh(connection)
        with patch.object(self.repo, "_refresh_content_views", side_effect=fail_on_publish):
            with self.assertRaises(RuntimeError):
                self.repo.store_news([_article("retry")])
        self.assertEqual(["article-original"], [row["article_id"] for row in self.repo.recent_news()])
        self.repo.store_news([_article("retry")])
        self.assertEqual(2, len(self.repo.recent_news()))

    def test_retention_uses_time_within_boundary_partition(self):
        cutoff = NOW - timedelta(days=90)
        self.repo.store_news([_article("expired", published=cutoff - timedelta(seconds=1)), _article("kept", published=cutoff)])
        result = self.repo.prune(cutoff=cutoff)
        self.assertEqual(1, result.news)
        self.assertEqual(["article-kept"], [row["article_id"] for row in self.repo.recent_news()])

    def test_null_only_optional_timestamp_does_not_poison_next_partition(self):
        self.repo.store_news([_article("null")])
        article = _article("dated", published=NOW)
        article.available_at = NOW
        self.repo.store_news([article])
        self.assertEqual(2, len(self.repo.recent_news()))

    def test_store_news_reports_stored_and_duplicate_counts(self) -> None:
        first = self.repo.store_news([_article("a"), _article("b")])
        self.assertEqual((2, 0), (first.stored, first.duplicates))

        again = self.repo.store_news([_article("a"), _article("c")])
        self.assertEqual((1, 1), (again.stored, again.duplicates))

    def test_same_content_from_another_url_is_a_duplicate(self) -> None:
        """다른 provider가 같은 기사를 줘도 한 행이어야 한다."""
        self.repo.store_news([_article("a")])
        twin = _article("a")
        twin.article_id = "article-twin"
        twin.canonical_url = "https://mirror.example.com/a"
        twin.url_hash = "url-twin"
        result = self.repo.store_news([twin])
        self.assertEqual((0, 1), (result.stored, result.duplicates))

    def test_store_mentions_is_idempotent(self) -> None:
        self.repo.store_news([_article("a")])
        mention = EntityMention(
            mention_id="m1",
            source_kind="news",
            source_id="article-a",
            ticker="AAPL",
            match_kind="queried",
            confidence=1.0,
            observed_at=NOW,
            first_seen_at=NOW,
        )
        self.assertEqual(1, self.repo.store_mentions([mention]))
        self.assertEqual(0, self.repo.store_mentions([mention]))

    def test_freshness_reports_oldest_and_newest(self) -> None:
        self.repo.store_news([
            _article("old", published=NOW - timedelta(days=30)),
            _article("new", published=NOW - timedelta(days=1)),
        ])
        rows = {row["domain"]: row for row in self.repo.freshness()}
        self.assertEqual(2, rows["news"]["row_count"])
        self.assertEqual(0, rows["social"]["row_count"])

    def test_record_run_is_readable(self) -> None:
        self.repo.record_run(
            CollectionRun(
                run_id="run-1",
                kind="collect",
                domain="news",
                provider="yfinance",
                started_at=NOW,
                finished_at=NOW,
                status="ok",
                stored_count=2,
            )
        )
        runs = self.repo.recent_runs(limit=5)
        self.assertEqual("run-1", runs[0]["run_id"])
        self.assertEqual("ok", runs[0]["status"])

    def test_store_news_attributes_intra_batch_collision_correctly(self) -> None:
        """같은 배치 안에서 서로 충돌하는 경우 — 기존 행과의 충돌과 다른 경로다.

        `executemany`는 행 단위로 실행되므로 두 번째 레코드가 이미 저장된 행이
        아니라 같은 배치의 첫 번째 레코드와 충돌한다. `stored`/`duplicates`
        계산이 이 경로에서도 맞는지 별도로 확인해야 한다 — `executemany`를
        단일 다중 행 INSERT로 바꾸면 이 구분이 조용히 깨질 수 있다.
        """
        first = _article("dup1")
        twin = _article("dup2")
        twin.content_hash = first.content_hash
        result = self.repo.store_news([first, twin])
        self.assertEqual((1, 1), (result.stored, result.duplicates))

    def test_store_social_attributes_intra_batch_collision_correctly(self) -> None:
        """같은 배치 안에서 서로 충돌하는 경우 — 기존 행과의 충돌과 다른 경로다.

        `SocialPostRecord`는 `content_hash`가 중복 제거 키다. 같은 배치에 든
        두 레코드가 서로 다른 `post_id`를 가져도 `content_hash`가 같으면 두
        번째가 첫 번째와 충돌해야 한다.
        """
        first = _post("dup1")
        twin = _post("dup2")
        twin.content_hash = first.content_hash
        result = self.repo.store_social([first, twin])
        self.assertEqual((1, 1), (result.stored, result.duplicates))

    def test_content_is_kept_once_in_date_partitioned_parquet(self) -> None:
        """DuckDB catalog에 title/body를 중복 보관하면 90일 archive 절감이 무너진다."""
        self.repo.store_news([_article("archive")])
        archive = self.repo.archive_root / "news" / "date=2026-09-05"
        self.assertEqual(1, len(list(archive.glob("*.parquet"))))
        with self.repo._connect() as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(content_index)").fetchall()}
        self.assertNotIn("title", columns)
        self.assertNotIn("summary", columns)
        self.assertNotIn("body", columns)

    def test_read_only_repository_refuses_to_write(self) -> None:
        self.repo.store_news([_article("a")])
        reader = IntelligenceRepository(self.repo.path, read_only=True)
        with self.assertRaises(PermissionError):
            reader.store_news([_article("z")])


if __name__ == "__main__":
    unittest.main()
