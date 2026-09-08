"""공통 Actions 실패 리포터가 원문을 안전한 사건 카드로 바꾸는지 검증한다."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from investment_agent.operations.commands import workflow_failure


class WorkflowFailureReporterTest(unittest.TestCase):
    def _environment(self) -> dict[str, str]:
        return {
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "acme/investment-agent",
            "GITHUB_EVENT_NAME": "schedule",
            "GITHUB_SHA": "abcdef0123456789",
        }

    def test_failed_job_is_sent_as_a_redacted_structured_incident(self) -> None:
        jobs = [{
            "id": 123,
            "name": "daily",
            "conclusion": "failure",
            "steps": [
                {"name": "Install", "conclusion": "success"},
                {"name": "Load prices", "conclusion": "failure"},
            ],
        }]
        raw_log = "ERROR provider timeout token=private-value"

        with (
            mock.patch.dict(os.environ, self._environment(), clear=False),
            mock.patch.object(
                workflow_failure.github, "jobs_for_run", return_value=jobs
            ) as jobs_for_run,
            mock.patch.object(
                workflow_failure.github, "job_log", return_value=raw_log
            ) as job_log,
            mock.patch.object(workflow_failure, "notify_ops", return_value=True) as notify,
        ):
            result = workflow_failure.main([
                "--conclusion", "failure",
                "--workflow", "market_daily",
                "--run-id", "77",
                "--run-attempt", "2",
            ])

        self.assertEqual(result, 0)
        jobs_for_run.assert_called_once_with(77, attempt=2)
        job_log.assert_called_once_with(123)
        embed = notify.call_args.kwargs["embeds"][0]
        self.assertEqual(embed["url"], "https://github.com/acme/investment-agent/actions/runs/77")
        self.assertIn("market_daily / daily / Load prices", embed["fields"][2]["value"])
        self.assertIn("provider timeout", embed["fields"][3]["value"])
        self.assertNotIn("private-value", embed["fields"][3]["value"])
        self.assertIn("시도 2", embed["fields"][7]["value"])

    def test_actions_lookup_failure_still_sends_a_fallback_card(self) -> None:
        with (
            mock.patch.dict(os.environ, self._environment(), clear=False),
            mock.patch.object(
                workflow_failure.github,
                "jobs_for_run",
                side_effect=RuntimeError("API unavailable"),
            ),
            mock.patch.object(workflow_failure.time, "sleep"),
            mock.patch.object(workflow_failure, "notify_ops", return_value=False) as notify,
        ):
            result = workflow_failure.main([
                "--conclusion", "cancelled",
                "--workflow", "macro_etl",
                "--run-id", "88",
            ])

        self.assertEqual(result, 0)
        embed = notify.call_args.kwargs["embeds"][0]
        self.assertEqual(embed["fields"][0]["value"], "중단")
        self.assertIn("취소", embed["fields"][3]["value"])


if __name__ == "__main__":
    unittest.main()
