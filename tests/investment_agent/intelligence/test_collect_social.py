"""Reddit 수집 유스케이스와 저장 형태."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from investment_agent.intelligence.repository import IntelligenceRepository
from investment_agent.intelligence.domain import social_normalize as normalize
from investment_agent.intelligence.application import collect_social as service

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
TRACKED = frozenset({"AAPL", "NVDA", "ALL"})


def _payload(suffix: str, *, body: str = "$NVDA looks strong", age_days: int = 1) -> dict:
    return {
        "id": suffix,
        "author": "someone",
        "title": f"title {suffix}",
        "selftext": body,
        "permalink": f"/r/stocks/comments/{suffix}/",
        "score": 12,
        "num_comments": 3,
        "link_flair_text": "DD",
        "created_utc": (NOW - timedelta(days=age_days)).timestamp(),
    }


class NormalizeSocialTest(unittest.TestCase):
    def test_author_is_stored_as_a_hash(self) -> None:
        """작성자 원문을 90일 들고 있을 이유가 없다."""
        record = normalize.to_record(_payload("a"), channel="stocks", now=NOW)
        self.assertIsNotNone(record.author_hash)
        self.assertNotIn("someone", str(record.author_hash))

    def test_payload_without_an_id_is_rejected(self) -> None:
        self.assertIsNone(normalize.to_record({"title": "x"}, channel="stocks", now=NOW))

    def test_deleted_author_leaves_the_hash_empty(self) -> None:
        payload = _payload("a")
        payload["author"] = "[deleted]"
        self.assertIsNone(normalize.to_record(payload, channel="stocks", now=NOW).author_hash)


class CollectSocialTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = IntelligenceRepository(Path(self._tmp.name) / "intelligence.duckdb")

    def test_stores_posts_and_extracted_mentions(self) -> None:
        run = service.collect_social(
            repository=self.repo,
            fetch=lambda channel: [_payload("a")],
            channels=["stocks"],
            tracked=TRACKED,
            now=NOW,
        )
        self.assertEqual(1, run.stored_count)
        counts = self.repo.mention_counts(since="2000-01-01", limit=5)
        self.assertEqual([{"ticker": "NVDA", "mention_count": 1}], counts)

    def test_posts_without_any_tracked_ticker_are_still_stored(self) -> None:
        """언급이 없다고 게시물을 버리면 나중에 규칙을 고쳐도 다시 못 찾는다."""
        run = service.collect_social(
            repository=self.repo,
            fetch=lambda channel: [_payload("a", body="no symbols here")],
            channels=["stocks"],
            tracked=TRACKED,
            now=NOW,
        )
        self.assertEqual(1, run.stored_count)
        self.assertEqual([], self.repo.mention_counts(since="2000-01-01", limit=5))

    def test_missing_credentials_are_recorded_as_skipped(self) -> None:
        def fetch(channel: str) -> list[dict]:
            raise service.SocialCredentialsMissing("no credentials")

        run = service.collect_social(
            repository=self.repo,
            fetch=fetch,
            channels=["stocks"],
            tracked=TRACKED,
            now=NOW,
        )
        self.assertEqual("skipped", run.status)
        self.assertEqual("no_credentials", run.error_kind)

    def test_quota_exhaustion_stops_the_batch_and_reports_capped(self) -> None:
        """cap 소진은 provider 오류가 아니다 — 남은 채널을 계속 돌면 예약만 반복 소모한다."""
        seen: list[str] = []

        def fetch(channel: str) -> list[dict]:
            seen.append(channel)
            if channel == "stocks":
                return [_payload("a")]
            raise service.SocialQuotaExhausted("reddit daily cap reached (25)")

        run = service.collect_social(
            repository=self.repo,
            fetch=fetch,
            channels=["stocks", "wallstreetbets"],
            tracked=TRACKED,
            now=NOW,
        )
        self.assertEqual(["stocks", "wallstreetbets"], seen)
        self.assertEqual("capped", run.status)
        self.assertEqual("quota_exhausted", run.error_kind)
        self.assertEqual(1, run.stored_count)

    def test_items_older_than_retention_are_not_stored(self) -> None:
        run = service.collect_social(
            repository=self.repo,
            fetch=lambda channel: [_payload("old", age_days=120)],
            channels=["stocks"],
            tracked=TRACKED,
            now=NOW,
        )
        self.assertEqual(0, run.stored_count)


if __name__ == "__main__":
    unittest.main()
