"""일일 점검 요약 — 무엇을 문제로 셀지가 이 카드의 전부다."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.operations.monitoring import digest

UTC = timezone.utc
END = datetime(2026, 8, 18, 6, 30, tzinfo=UTC)
START = END - timedelta(hours=24)


def _run(conclusion, *, status="completed", hour=4):
    return {"created_at": datetime(2026, 8, 18, hour, 0, tzinfo=UTC),
            "event": "schedule", "status": status,
            "conclusion": conclusion, "url": "https://example.invalid/run"}


def _wf(name, runs, *, expected=True, crons=("25 0 * * 2-6",)):
    return {"name": name, "crons": list(crons), "expected": expected, "runs": runs}


class EvaluateTest(unittest.TestCase):
    def test_success_is_healthy(self):
        v = digest.evaluate([_wf("macro_etl", [_run("success")])], START, END)

        self.assertEqual([x["name"] for x in v["healthy"]], ["macro_etl"])
        self.assertEqual(v["failed"], [])
        self.assertEqual(v["missing"], [])

    def test_cancelled_is_never_treated_as_normal(self):
        """타임아웃은 conclusion이 cancelled로 찍힌다 — 이걸 놓쳐서 알림이 안 갔었다.

        실패와 색은 나누되(원인도 대응도 다르다) 정상으로 묻지는 않는다.
        """
        v = digest.evaluate([_wf("notify_macro_core", [_run("cancelled")])], START, END)

        self.assertEqual(len(v["stopped"]), 1)
        self.assertEqual(v["stopped"][0]["conclusion"], "cancelled")
        self.assertEqual(v["healthy"], [])
        self.assertIn("notify_macro_core", digest.render(v, END))

    def test_broken_and_stopped_are_separated(self):
        """인프라가 끊은 것과 코드가 깨진 것을 같은 줄에 두면 매일 훑고 넘기게 된다."""
        v = digest.evaluate([
            _wf("tech_indicators", [_run("failure")]),
            _wf("notify_macro_core", [_run("cancelled")]),
        ], START, END)

        self.assertEqual([x["name"] for x in v["failed"]], ["tech_indicators"])
        self.assertEqual([x["name"] for x in v["stopped"]], ["notify_macro_core"])

    def test_failure_followed_by_success_is_marked_recovered(self):
        """아침에 깨졌다가 고쳐 다시 돌린 것을 지금도 깨진 것과 같이 읽으면 안 된다."""
        v = digest.evaluate([
            _wf("fundamentals_daily", [_run("failure", hour=4), _run("success", hour=5)]),
        ], START, END)

        self.assertEqual(len(v["failed"]), 1)
        self.assertTrue(v["failed"][0]["recovered"])
        body = digest.render(v, END)
        self.assertIn("이후 성공", body)
        self.assertIn("그중 1건은 뒤이은 실행이 성공했다.", body)
        # 지금 깨진 게 없으면 빨강이 아니다 — 빨강은 오늘 손대야 할 날에만 쓴다.
        self.assertEqual(digest.severity_color(v), digest.COLOR_WARN)

    def test_failure_with_no_later_success_stays_red(self):
        """마지막 실행이 실패로 끝난 것은 계속 빨강이어야 한다."""
        v = digest.evaluate([
            _wf("fundamentals_daily", [_run("success", hour=3), _run("failure", hour=5)]),
        ], START, END)

        self.assertFalse(v["failed"][0]["recovered"])
        self.assertNotIn("이후 성공", digest.render(v, END))
        self.assertEqual(digest.severity_color(v), digest.COLOR_FAIL)

    def test_skipped_is_not_a_failure(self):
        """게이트가 정상 동작해 건너뛴 것을 실패로 세면 매일 거짓 경보가 뜬다."""
        v = digest.evaluate([_wf("notify_macro_watch", [_run("skipped")])], START, END)

        self.assertEqual(v["failed"], [])
        self.assertEqual(len(v["healthy"]), 1)

    def test_scheduled_but_never_ran_is_missing(self):
        """DB로는 절대 못 보는 항목 — 리네임·배선 오류가 여기 걸린다."""
        v = digest.evaluate([_wf("fundamentals_dimensions", [], expected=True)], START, END)

        self.assertEqual([x["name"] for x in v["missing"]], ["fundamentals_dimensions"])

    def test_manual_only_workflow_without_runs_is_ignored(self):
        """백필처럼 cron이 없는 워크플로는 안 돌아도 정상이다 — 다만 세기는 한다."""
        v = digest.evaluate([_wf("macro_backfill", [], expected=False, crons=())], START, END)

        self.assertEqual(v["missing"], [])
        self.assertEqual(v["failed"], [])
        self.assertEqual([x["name"] for x in v["idle"]], ["macro_backfill"])

    def test_every_workflow_lands_in_exactly_one_bucket(self):
        """합이 총수와 맞아야 카드가 무엇을 안 보고 있는지 드러난다."""
        workflows = [
            _wf("a", [_run("success")]),
            _wf("b", [_run("failure")]),
            _wf("c", [_run("cancelled")]),
            _wf("d", [], expected=True),
            _wf("e", [], expected=False, crons=()),
        ]
        v = digest.evaluate(workflows, START, END)

        self.assertEqual(sum(len(v[k]) for k in
                             ("healthy", "failed", "stopped", "missing", "idle")),
                         len(workflows))

    def test_in_progress_run_is_not_a_failure(self):
        v = digest.evaluate(
            [_wf("macro_etl", [_run(None, status="in_progress")])], START, END)

        self.assertEqual(v["failed"], [])
        self.assertEqual(v["healthy"][0]["running"], 1)

    def test_repeated_failures_collapse_to_one_line_with_a_count(self):
        v = digest.evaluate(
            [_wf("notify_macro_watch", [_run("failure", hour=2), _run("failure", hour=5)])],
            START, END)

        self.assertEqual(v["failed"][0]["count"], 2)


class RenderTest(unittest.TestCase):
    def test_all_clear_message_is_short(self):
        v = digest.evaluate([_wf("macro_etl", [_run("success")])], START, END)
        body = digest.render(v, END)

        self.assertIn("이상 없습니다", body)
        self.assertIn("2026-08-18(화)", body)

    def test_failure_line_links_to_the_run(self):
        """링크가 없으면 원인을 보려고 GitHub에서 그 실행을 손으로 찾아야 한다."""
        v = digest.evaluate([_wf("tech_indicators", [_run("failure")])], START, END)
        body = digest.render(v, END)

        # <>로 감싸야 링크 미리보기가 목록을 밀어내지 않는다.
        self.assertIn("<https://example.invalid/run>", body)

    def test_problem_message_names_the_workflow_and_kst_time(self):
        v = digest.evaluate([_wf("notify_macro_core", [_run("cancelled", hour=4)])], START, END)
        body = digest.render(v, END)

        self.assertIn("notify_macro_core", body)
        self.assertIn("cancelled", body)
        self.assertIn("13:00 KST", body)  # 04:00 UTC = 13:00 KST

    def test_body_stays_within_discord_limit(self):
        many = [_wf(f"wf_{i}", [_run("failure")]) for i in range(40)]
        body = digest.render(digest.evaluate(many, START, END), END)

        self.assertLessEqual(len(body), 1900)
        self.assertIn("외", body)


if __name__ == "__main__":
    unittest.main()
