"""뉴스 응답 정규화와 중복 키 계약."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from investment_agent.intelligence.domain import news_normalize as normalize

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)


class CanonicalUrlTest(unittest.TestCase):
    def test_tracking_parameters_do_not_change_identity(self) -> None:
        """추적 파라미터만 다른 같은 기사가 두 행이 되면 안 된다."""
        left = normalize.canonical_url("https://example.com/a?utm_source=x&utm_medium=y")
        right = normalize.canonical_url("https://example.com/a")
        self.assertEqual(left, right)

    def test_scheme_and_host_case_are_normalised(self) -> None:
        self.assertEqual(
            normalize.canonical_url("HTTPS://Example.COM/a"),
            normalize.canonical_url("https://example.com/a"),
        )

    def test_fragment_is_dropped(self) -> None:
        self.assertEqual(
            normalize.canonical_url("https://example.com/a#section"),
            normalize.canonical_url("https://example.com/a"),
        )


class ToRecordTest(unittest.TestCase):
    def test_nested_yfinance_content_is_preserved(self) -> None:
        record = normalize.to_record({"id": "article-1", "content": {
            "title": "실적 발표", "summary": "분기 실적 요약",
            "canonicalUrl": {"url": "https://example.com/a?utm_source=yahoo"},
            "provider": {"displayName": "Example Wire"},
            "pubDate": "2026-09-06T10:00:00Z",
        }}, provider="yfinance", now=NOW)
        self.assertIsNotNone(record)
        self.assertEqual(record.canonical_url, "https://example.com/a")
        self.assertEqual(record.title, "실적 발표")
        self.assertEqual(record.summary, "분기 실적 요약")
        self.assertEqual(record.source_name, "Example Wire")
        self.assertEqual(record.published_at, datetime(2026, 9, 6, 10, tzinfo=timezone.utc))

    def test_payload_without_a_url_is_rejected(self) -> None:
        """URL이 없으면 중복 제거를 할 수 없다 — 저장하지 않는다."""
        self.assertIsNone(
            normalize.to_record({"title": "제목"}, provider="yfinance", now=NOW)
        )

    def test_payload_without_a_title_is_rejected(self) -> None:
        self.assertIsNone(
            normalize.to_record(
                {"link": "https://example.com/a"}, provider="yfinance", now=NOW
            )
        )

    def test_epoch_publish_time_is_read_as_utc(self) -> None:
        record = normalize.to_record(
            {
                "link": "https://example.com/a",
                "title": "제목",
                "publisher": "Example Wire",
                "providerPublishTime": 1757160000,
            },
            provider="yfinance",
            now=NOW,
        )
        self.assertIsNotNone(record)
        self.assertEqual(timezone.utc, record.published_at.tzinfo)
        self.assertEqual("Example Wire", record.source_name)

    def test_available_at_stays_empty_when_the_provider_gives_none(self) -> None:
        """PIT 계산은 coalesce(available_at, first_seen_at)을 쓴다 —
        빈칸을 수집 시각으로 채우면 그 계약이 거짓이 된다."""
        record = normalize.to_record(
            {"link": "https://example.com/a", "title": "제목"},
            provider="yfinance",
            now=NOW,
        )
        self.assertIsNone(record.available_at)
        self.assertEqual(NOW, record.first_seen_at)


if __name__ == "__main__":
    unittest.main()
