"""일일 점검 카드: 자르기 한도는 목적지가 정하고, 카운터 실패는 0건과 구별된다."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from investment_agent.operations.monitoring import counters, digest

END = datetime(2026, 9, 21, 6, 40, tzinfo=timezone.utc)


def _verdict(count: int) -> dict[str, list[dict]]:
    def rows(prefix: str) -> list[dict]:
        return [
            {"name": f"{prefix}_workflow_with_a_fairly_long_name_{index}",
             "upstream": "fundamentals_daily", "crons": ["0 9 * * *", "0 21 * * *"],
             "last_at": END, "at": END, "conclusion": "failure", "count": 1, "streak": 1,
             "url": f"https://example.invalid/runs/{prefix}{index}"}
            for index in range(count)
        ]

    return {"healthy": [], "failed": rows("f"), "stopped": rows("s"),
            "missing": rows("m"), "idle": []}


def _channels(count: int) -> list[dict]:
    return [
        {"label": f"채널-{index:02d}", "count": index, "last_at": END,
         "verdict": " ⚠️ 24시간 조용", "alert": True}
        for index in range(count)
    ]


class DigestTruncationTest(unittest.TestCase):
    def test_the_embed_gets_the_embed_limit_not_the_plain_text_limit(self):
        verdict, channels = _verdict(6), _channels(16)
        embed = digest.build_embed(verdict, END, channels, ["대기 12건"])
        body = embed["description"]
        self.assertLessEqual(len(body), digest.EMBED_LIMIT)
        self.assertGreater(len(body), digest.PLAIN_TEXT_LIMIT,
                           "embed인데 평문 한도로 잘렸다")
        # 맨 뒤의 채널 표가 살아 있어야 한다 — 사고가 많은 날 가장 필요한 절이다.
        self.assertIn("채널 도착", body)
        self.assertIn("채널-15", body)

    def test_plain_text_still_uses_the_plain_limit(self):
        body = digest.render(_verdict(6), END, _channels(16), ["대기 12건"])
        self.assertLessEqual(len(body), digest.PLAIN_TEXT_LIMIT)

    def test_a_truncated_body_says_so(self):
        body = digest.render(_verdict(20), END, _channels(16), ["대기 12건"])
        self.assertIn("자 생략", body)

    def test_a_short_body_is_untouched(self):
        body = digest.render({"healthy": [], "failed": [], "stopped": [],
                              "missing": [], "idle": []}, END)
        self.assertNotIn("자 생략", body)


class CounterFailureVisibilityTest(unittest.TestCase):
    """카운터가 전부 실패하면 그 줄이 사라져 "0건"과 구별되지 않았다(감사 OP2-16)."""

    def test_collect_reports_the_failed_source_names(self):
        failures: list[str] = []
        with mock.patch.object(
            counters, "_SOURCES",
            [("fundamentals", lambda: (_ for _ in ()).throw(RuntimeError("supabase down"))),
             ("gurus", lambda: "13F 미발송 0(2026Q2)")],
        ):
            lines = counters.collect(failures)
        self.assertEqual(failures, ["fundamentals"])
        self.assertEqual(lines, ["13F 미발송 0(2026Q2)"])

    def test_all_sources_failing_is_not_an_empty_success(self):
        failures: list[str] = []
        with mock.patch.object(
            counters, "_SOURCES",
            [(name, lambda: (_ for _ in ()).throw(RuntimeError("down")))
             for name in ("a", "b")],
        ):
            lines = counters.collect(failures)
        self.assertEqual(lines, [])
        self.assertEqual(sorted(failures), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
