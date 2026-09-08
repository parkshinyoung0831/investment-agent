"""뉴스 수집 유스케이스. 네트워크를 타지 않는다 — fetch는 주입한다."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from investment_agent.intelligence.repository import IntelligenceRepository
from investment_agent.intelligence.application import collect_news as service
from investment_agent.intelligence.infrastructure.sources.news.yfinance import NewsQuotaExhausted

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)


def _payload(suffix: str, *, age_days: int = 1) -> dict:
    return {
        "link": f"https://example.com/{suffix}",
        "title": f"title {suffix}",
        "publisher": "Example Wire",
        "providerPublishTime": (NOW - timedelta(days=age_days)).timestamp(),
    }


class CollectNewsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = IntelligenceRepository(Path(self._tmp.name) / "intelligence.duckdb")

    def test_stores_articles_and_queried_mentions(self) -> None:
        run = service.collect_news(
            repository=self.repo,
            fetch=lambda ticker: [_payload(f"{ticker}-1"), _payload(f"{ticker}-2")],
            tickers=["AAPL"],
            now=NOW,
        )
        self.assertEqual("ok", run.status)
        self.assertEqual(2, run.stored_count)
        counts = self.repo.mention_counts(since="2000-01-01", limit=5)
        self.assertEqual([{"ticker": "AAPL", "mention_count": 2}], counts)

    def test_mention_match_kind_is_queried(self) -> None:
        """조회해서 받은 것은 '화제'가 아니다 — 등급을 남긴다."""
        service.collect_news(
            repository=self.repo,
            fetch=lambda ticker: [_payload("a")],
            tickers=["AAPL"],
            now=NOW,
        )
        with self.repo._connect() as connection:
            kinds = {row[0] for row in connection.execute(
                "SELECT match_kind FROM entity_mentions"
            ).fetchall()}
        self.assertEqual({"queried"}, kinds)

    def test_items_older_than_retention_are_not_stored(self) -> None:
        """저장한 뒤 다음 정리에서 지우면 그 사이 화면에 잠깐 나타난다."""
        run = service.collect_news(
            repository=self.repo,
            fetch=lambda ticker: [_payload("stale", age_days=120)],
            tickers=["AAPL"],
            now=NOW,
        )
        self.assertEqual(0, run.stored_count)
        self.assertEqual([], self.repo.recent_news(limit=5))

    def test_unparsable_items_are_counted_apart_from_duplicates(self) -> None:
        """파싱 실패를 중복으로 세면 '조용한 0건'을 못 알아본다."""
        run = service.collect_news(
            repository=self.repo,
            fetch=lambda ticker: [{"title": "URL 없음"}, _payload("ok")],
            tickers=["AAPL"],
            now=NOW,
        )
        self.assertEqual(1, run.unparsed_count)
        self.assertEqual(1, run.stored_count)
        self.assertEqual(0, run.duplicate_count)

    def test_a_failing_ticker_does_not_stop_the_others(self) -> None:
        def fetch(ticker: str) -> list[dict]:
            if ticker == "BOOM":
                raise RuntimeError("provider exploded")
            return [_payload(ticker)]

        run = service.collect_news(
            repository=self.repo,
            fetch=fetch,
            tickers=["BOOM", "AAPL"],
            now=NOW,
        )
        self.assertEqual(1, run.stored_count)
        self.assertEqual("partial", run.status)
        self.assertEqual("provider_error", run.error_kind)

    def test_quota_exhaustion_stops_the_batch_and_reports_capped(self) -> None:
        """cap 소진은 provider 오류가 아니다 — 남은 종목을 계속 돌면 예약만 반복 소모한다."""
        seen: list[str] = []

        def fetch(ticker: str) -> list[dict]:
            seen.append(ticker)
            if ticker == "AAPL":
                return [_payload("aapl")]
            raise NewsQuotaExhausted("yfinance daily cap reached (25)")

        run = service.collect_news(
            repository=self.repo,
            fetch=fetch,
            tickers=["AAPL", "MSFT", "GOOG"],
            now=NOW,
        )
        self.assertEqual(["AAPL", "MSFT"], seen)
        self.assertEqual("capped", run.status)
        self.assertEqual("quota_exhausted", run.error_kind)
        self.assertEqual(1, run.stored_count)

    def test_the_run_is_recorded_even_when_nothing_is_stored(self) -> None:
        service.collect_news(
            repository=self.repo, fetch=lambda ticker: [], tickers=["AAPL"], now=NOW
        )
        runs = [row for row in self.repo.recent_runs(limit=5) if row["kind"] == "collect"]
        self.assertEqual(1, len(runs))
        self.assertEqual("news", runs[0]["domain"])


if __name__ == "__main__":
    unittest.main()
