"""수집 실행의 상태는 예외 유무가 아니라 결과로 판정한다.

실측: 로컬 runtime의 `intelligence:collect:news`가 `ok`, stored 0, duplicate 0으로 12일째 신규 0건이었는데
"응답이 비었다"와 "전부 파싱 실패했다"를 기록만으로는 가를 수 없었다. 상태 판정이 예외 유무만 봤고,
`unparsed_count`는 실행 기록의 detail에 저장되지도 않았다.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from investment_agent.intelligence.application import collect_news as service
from investment_agent.intelligence.repository import IntelligenceRepository

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
UNPARSABLE = {"title": "URL이 없어 기록으로 못 바꾼다"}


def _payload(suffix: str) -> dict:
    return {
        "link": f"https://example.com/{suffix}",
        "title": f"title {suffix}",
        "publisher": "Example Wire",
        "providerPublishTime": (NOW - timedelta(days=1)).timestamp(),
    }


class CollectRunStatusTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = IntelligenceRepository(Path(self._tmp.name) / "intelligence.duckdb")

    def _collect(self, fetch, tickers=("AAPL", "MSFT")):
        return service.collect_news(repository=self.repo, fetch=fetch, tickers=list(tickers), now=NOW)

    def _job_detail(self) -> dict:
        with closing(sqlite3.connect(self.repo.runtime_path)) as connection:
            row = connection.execute(
                "SELECT last_status, detail FROM local_job_state WHERE job_name = 'intelligence:collect:news'"
            ).fetchone()
        return {"last_status": row[0], **json.loads(row[1])}

    def test_a_healthy_run_is_ok(self):
        run = self._collect(lambda ticker: [_payload(ticker)])
        self.assertEqual("ok", run.status)
        self.assertIsNone(run.error_kind)

    def test_every_article_unparsable_is_an_error_not_a_quiet_success(self):
        """provider 응답 형식이 바뀌면 전부 파싱에 실패한다 — 그것이 성공으로 접히면 안 된다."""
        run = self._collect(lambda ticker: [UNPARSABLE, UNPARSABLE])
        self.assertEqual("error", run.status)
        self.assertEqual("parse_failed", run.error_kind)
        self.assertEqual(4, run.unparsed_count)
        self.assertIn("4", run.message)

    def test_some_unparsable_articles_among_good_ones_are_still_ok(self):
        run = self._collect(lambda ticker: [UNPARSABLE, _payload(ticker)])
        self.assertEqual("ok", run.status)
        self.assertEqual(2, run.unparsed_count)

    def test_no_articles_from_any_ticker_is_reported_as_partial(self):
        """대상이 있는데 전 종목이 빈 응답이면 '뉴스가 없다'와 '수집이 죽었다'를 구분할 수 없다."""
        run = self._collect(lambda ticker: [])
        self.assertEqual("partial", run.status)
        self.assertEqual("no_articles", run.error_kind)

    def test_an_empty_ticker_list_is_not_reported_as_missing_articles(self):
        run = self._collect(lambda ticker: [], tickers=())
        self.assertEqual("ok", run.status)

    def test_a_ticker_failure_keeps_its_own_status(self):
        def fetch(ticker):
            raise RuntimeError("boom")

        run = self._collect(fetch)
        self.assertEqual("partial", run.status)
        self.assertEqual("provider_error", run.error_kind)

    def test_the_job_state_detail_keeps_the_unparsed_count_and_error_kind(self):
        self._collect(lambda ticker: [UNPARSABLE])
        detail = self._job_detail()
        self.assertEqual(2, detail["unparsed_count"])
        self.assertEqual("parse_failed", detail["error_kind"])
        self.assertEqual("failed", detail["last_status"])


class ResumeCursorTest(unittest.TestCase):
    """호출 한도가 종목 수보다 작은 날 항상 앞에서부터 돌면 뒤쪽 종목은 영영 수집되지 않는다(IN-2)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = IntelligenceRepository(Path(self._tmp.name) / "intelligence.duckdb")

    def test_rotate_from_starts_at_the_stopped_ticker_and_wraps_around(self) -> None:
        self.assertEqual(["CCC", "DDD", "AAA", "BBB"], service.rotate_from(["AAA", "BBB", "CCC", "DDD"], "ccc"))
        self.assertEqual(["AAA", "BBB"], service.rotate_from(["AAA", "BBB"], None))
        self.assertEqual(["AAA", "BBB"], service.rotate_from(["AAA", "BBB"], "GONE"))

    def test_a_capped_run_remembers_where_it_stopped_and_the_next_run_resumes_there(self) -> None:
        from investment_agent.intelligence.infrastructure.sources.news.yfinance import NewsQuotaExhausted

        fetched: list[str] = []

        def capped_after_two(ticker):
            if len(fetched) == 2:
                raise NewsQuotaExhausted()
            fetched.append(ticker)
            return [_payload(ticker)]

        run = service.collect_news(repository=self.repo, fetch=capped_after_two, tickers=["AAA", "BBB", "CCC", "DDD"], now=NOW)
        self.assertEqual("capped", run.status)
        self.assertEqual("CCC", run.resume_from)
        self.assertEqual("CCC", self.repo.resume_cursor("collect", "news"))

        second: list[str] = []
        service.collect_news(
            repository=self.repo, fetch=lambda t: second.append(t) or [_payload(t + "2")],
            tickers=["AAA", "BBB", "CCC", "DDD"], now=NOW, resume_from=self.repo.resume_cursor("collect", "news"),
        )
        self.assertEqual(["CCC", "DDD", "AAA", "BBB"], second)
        self.assertIsNone(self.repo.resume_cursor("collect", "news"), "끝까지 돌면 커서를 비운다")

    def test_no_cursor_before_any_run(self) -> None:
        self.assertIsNone(self.repo.resume_cursor("collect", "news"))


if __name__ == "__main__":
    unittest.main()
