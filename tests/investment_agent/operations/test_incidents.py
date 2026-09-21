"""Discord 사건 카드의 위치 추출·보안·표현 계약."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from investment_agent.operations.monitoring.incidents import (
    Incident,
    build_incident_embed,
    classify_incident,
    extract_error_summary,
    failed_job,
    failed_step,
    redact,
)
from investment_agent.operations.palette import STATUS_DANGER, STATUS_WARNING


class ClassifyIncidentTest(unittest.TestCase):
    """상태 코드 패턴은 단어 경계에서만 맞는다 — 요약문의 아무 숫자열이 401·403·429로 읽히면 안 된다(OP-09)."""

    def test_status_codes_match_only_as_whole_numbers(self):
        self.assertEqual(classify_incident("적재 4030행 처리 뒤 종료"), "code")
        self.assertEqual(classify_incident("processed 14290 rows"), "code")
        self.assertEqual(classify_incident("HTTP 403 Forbidden"), "configuration")
        self.assertEqual(classify_incident("status 401"), "configuration")
        self.assertEqual(classify_incident("status 429 too many"), "provider")

    def test_earlier_rules_keep_precedence(self):
        self.assertEqual(classify_incident("request timeout after 30s"), "timeout")


class IncidentTest(unittest.TestCase):
    def test_structured_json_error_wins_and_secrets_are_redacted(self):
        body = "\n".join((
            "2026-09-02T00:00:00Z harmless line",
            '{"level":"ERROR","msg":"request failed token=abc123",'
            '"exc":{"type":"TimeoutError","message":"Bearer private-token"}}',
        ))

        summary = extract_error_summary(body, fallback="unknown")

        self.assertIn("request failed", summary)
        self.assertIn("TimeoutError", summary)
        self.assertNotIn("abc123", summary)
        self.assertNotIn("private-token", summary)

    def test_webhook_jwt_credentials_and_mentions_are_redacted(self):
        unsafe = (
            "https://discord.com/api/webhooks/123/secret "
            "https://user:pass@example.com token=qwerty "
            "eyJaaaaaaaaaaaaaaaaaaaaaaaa.abcdefghijklmno.signature @everyone"
        )

        safe = redact(unsafe)

        for secret in ("/123/secret", "user:pass", "qwerty", "eyJaaaaaaaa", "@everyone"):
            self.assertNotIn(secret, safe)

    def test_failed_job_and_step_exclude_reporter(self):
        jobs = [
            {"id": 1, "name": "collect", "conclusion": "failure", "steps": [
                {"name": "Install", "conclusion": "success"},
                {"name": "Load observations", "conclusion": "failure"},
            ]},
            {"id": 2, "name": "Discord failure report", "conclusion": None},
        ]

        job = failed_job(jobs, "failure")

        self.assertEqual(job["name"], "collect")
        self.assertEqual(failed_step(job), "Load observations")

    def test_embed_uses_navigating_error_order_and_run_link(self):
        incident = Incident(
            workflow="market_daily",
            conclusion="failure",
            job="daily",
            step="Load prices",
            summary="provider timeout",
            category="timeout",
            url="https://github.com/acme/repo/actions/runs/1",
            occurred_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        )

        embed = build_incident_embed(incident)

        self.assertEqual(embed["color"], STATUS_DANGER)
        self.assertEqual(embed["url"], incident.url)
        self.assertEqual(
            [field["name"] for field in embed["fields"][:6]],
            ["상태", "분류", "실패 위치", "원인", "영향", "다음 행동"],
        )
        self.assertIn("market_daily / daily / Load prices", embed["fields"][2]["value"])
        self.assertEqual(embed["fields"][6]["name"], "발생 시각")
        self.assertIn("KST", embed["fields"][6]["value"])

    def test_cancelled_incident_uses_warning_color(self):
        incident = Incident(
            workflow="macro_etl",
            conclusion="cancelled",
            job="run",
            step="잡 실행",
            summary="GitHub Actions가 작업을 취소했어요.",
            category="cancelled",
            url="",
            occurred_at=datetime.now(timezone.utc),
        )

        self.assertEqual(build_incident_embed(incident)["color"], STATUS_WARNING)


if __name__ == "__main__":
    unittest.main()
