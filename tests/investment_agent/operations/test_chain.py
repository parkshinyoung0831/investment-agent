"""체인 감시·연속 일수·심각도 색 — 전부 '조용히 틀리는' 자리다."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.operations.monitoring import counters, digest

UTC = timezone.utc
NOW = datetime(2026, 8, 19, 6, 30, tzinfo=UTC)
START = NOW - timedelta(hours=24)


def _run(conclusion, hour=4, *, status="completed"):
    return {"created_at": datetime(2026, 8, 19, hour, 0, tzinfo=UTC),
            "event": "workflow_run", "status": status,
            "conclusion": conclusion, "url": "https://example.invalid/run"}


def _wf(name, runs, *, upstreams=(), crons=(), expected=False):
    return {"name": name, "runs": runs, "upstreams": list(upstreams),
            "crons": list(crons), "expected": expected}


class ChainTest(unittest.TestCase):
    """cron이 없는 워크플로는 상류 성공 말고는 '돌았어야 함'을 알 길이 없다."""

    def test_upstream_success_without_downstream_run_is_flagged(self):
        gaps = digest.chain_expectations([
            _wf("macro_etl", [_run("success", hour=1)]),
            _wf("notify_macro_core", [], upstreams=["macro_etl"]),
        ], NOW)

        self.assertEqual(gaps, {"notify_macro_core": "macro_etl"})

    def test_downstream_that_ran_after_upstream_is_fine(self):
        gaps = digest.chain_expectations([
            _wf("macro_etl", [_run("success", hour=1)]),
            _wf("notify_macro_core", [_run("success", hour=2)], upstreams=["macro_etl"]),
        ], NOW)

        self.assertEqual(gaps, {})

    def test_recent_upstream_is_still_within_grace(self):
        """상류가 방금 끝났으면 하류는 아직 큐에 있을 수 있다."""
        gaps = digest.chain_expectations([
            _wf("macro_etl", [{**_run("success"), "created_at": NOW - timedelta(minutes=3)}]),
            _wf("notify_macro_core", [], upstreams=["macro_etl"]),
        ], NOW)

        self.assertEqual(gaps, {})

    def test_failed_upstream_does_not_expect_a_downstream(self):
        """상류가 실패했으면 하류가 안 도는 게 맞다 — 그걸 하류 탓으로 세면 안 된다."""
        gaps = digest.chain_expectations([
            _wf("macro_etl", [_run("failure", hour=1)]),
            _wf("notify_macro_core", [], upstreams=["macro_etl"]),
        ], NOW)

        self.assertEqual(gaps, {})

    def test_missing_line_names_the_upstream_not_a_cron(self):
        verdict = digest.evaluate(
            [{**_wf("notify_strategy", [], upstreams=["strategy_monthly"], expected=True),
              "expected_by": "strategy_monthly"}], START, NOW)
        body = digest.render(verdict, NOW)

        self.assertIn("상류 `strategy_monthly`", body)


class StreakTest(unittest.TestCase):
    def test_streak_counts_distinct_days(self):
        runs = [_run("failure", hour=1), _run("failure", hour=5)]
        runs.append({**_run("failure"), "created_at": datetime(2026, 8, 17, 4, tzinfo=UTC)})

        self.assertEqual(digest.failure_streak(runs), 2)

    def test_failures_and_stops_are_counted_separately(self):
        """인프라 타임아웃 이틀 뒤 코드가 깨진 것을 '3일째 실패'라 부르면 안 된다."""
        runs = [
            {**_run("cancelled"), "created_at": datetime(2026, 8, 17, 4, tzinfo=UTC)},
            {**_run("cancelled"), "created_at": datetime(2026, 8, 18, 4, tzinfo=UTC)},
            _run("failure", hour=4),
        ]

        self.assertEqual(digest.failure_streak(runs), 1)
        self.assertEqual(digest.failure_streak(runs, stopped=True), 2)


class AccountingTest(unittest.TestCase):
    def test_a_workflow_with_both_problems_is_counted_once(self):
        """두 칸에 모두 넣으면 분류의 합이 총수를 넘어 합을 맞춘 의미가 사라진다."""
        verdict = digest.evaluate(
            [_wf("notify_macro_core", [_run("failure", hour=2), _run("cancelled", hour=3)])],
            START, NOW)

        buckets = ("healthy", "failed", "stopped", "missing", "idle")
        self.assertEqual(sum(len(verdict[k]) for k in buckets), 1)
        self.assertEqual([x["name"] for x in verdict["failed"]], ["notify_macro_core"])
        self.assertEqual(verdict["stopped"], [])


class EmbedTest(unittest.TestCase):
    def _verdict(self, runs):
        return digest.evaluate([_wf("wf", runs)], START, NOW)

    def test_color_rises_with_severity(self):
        self.assertEqual(digest.severity_color(self._verdict([_run("success")])),
                         digest.COLOR_OK)
        self.assertEqual(digest.severity_color(self._verdict([_run("cancelled")])),
                         digest.COLOR_WARN)
        self.assertEqual(digest.severity_color(self._verdict([_run("failure")])),
                         digest.COLOR_FAIL)

    def test_embed_title_carries_the_date_and_body_has_no_duplicate_head(self):
        embed = digest.build_embed(self._verdict([_run("success")]), NOW)

        self.assertIn("08-19", embed["title"])
        self.assertNotIn("일일 점검", embed["description"])

    def test_counters_line_is_rendered(self):
        body = digest.render(self._verdict([_run("success")]), NOW, None,
                             ["관심종목 50 · 미발송 공시 0"])

        self.assertIn("대기 상태", body)
        self.assertIn("미발송 공시 0", body)


class CountersTest(unittest.TestCase):
    def test_a_broken_source_never_kills_the_digest(self):
        """카운터 하나가 실패했다고 점검이 사라지면 점검이 없는 것보다 나쁘다."""
        def boom() -> str:
            raise RuntimeError("supabase down")

        original = counters._SOURCES
        try:
            counters._SOURCES = [("ok", lambda: "관심종목 50"), ("bad", boom)]
            self.assertEqual(counters.collect(), ["관심종목 50"])
        finally:
            counters._SOURCES = original

    def test_ping_without_url_does_nothing(self):
        self.assertFalse(counters.ping(""))


if __name__ == "__main__":
    unittest.main()
