"""actions_budget은 실행 시간을 분 단위로 올림 과금한다(SC-01)."""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_SPEC = importlib.util.spec_from_file_location(
    "actions_budget", Path(__file__).resolve().parents[1] / "scripts" / "actions_budget.py"
)
budget = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(budget)


class BillingRoundingTest(unittest.TestCase):
    def test_sub_minute_runs_are_billed_as_a_full_minute(self) -> None:
        rows = [
            {"name": "w", "startedAt": "2026-09-01T00:00:00Z", "updatedAt": "2026-09-01T00:00:41Z"},
            {"name": "w", "startedAt": "2026-09-02T00:00:00Z", "updatedAt": "2026-09-02T00:00:42Z"},
        ]
        proc = SimpleNamespace(returncode=0, stdout=json.dumps(rows), stderr="")
        with mock.patch.object(budget.subprocess, "run", return_value=proc):
            self.assertEqual(budget._observed_minutes(10), {"w": 1.0})


class ScheduledRateTest(unittest.TestCase):
    """고빈도 cron이 큐에서 버려져 설계보다 훨씬 적게 도는 것을 이력에서 읽는다(SC-01)."""

    def test_monthly_rate_is_scaled_from_the_history_span(self) -> None:
        rows = [{"name": "w", "event": "schedule", "createdAt": f"2026-09-{day:02d}T00:00:00Z"} for day in range(1, 11)]
        rows.append({"name": "w", "event": "workflow_dispatch", "createdAt": "2026-09-11T00:00:00Z"})
        rate = budget.scheduled_rate_per_month(rows)
        self.assertAlmostEqual(rate["w"], 10 / 10 * budget.DAYS_PER_MONTH)  # 10일 동안 schedule 10회

    def test_too_short_history_gives_no_rate(self) -> None:
        self.assertEqual(budget.scheduled_rate_per_month([]), {})
        self.assertEqual(budget.scheduled_rate_per_month(
            [{"name": "w", "event": "schedule", "createdAt": "2026-09-01T00:00:00Z"}]), {})

    def test_a_dropped_cron_is_reported_in_the_output(self) -> None:
        rows = [{"name": "econ", "event": "schedule", "createdAt": f"2026-09-{d:02d}T12:00:00Z"} for d in (1, 15, 30)]
        workflows = {"econ": {"crons": ["*/15 12-15 * * 1-5"], "upstream": []}}
        with (
            mock.patch.object(budget, "_fetch_rows", return_value=rows),
            mock.patch.object(budget, "_parse_workflows", return_value=workflows),
            mock.patch("builtins.print") as printed,
        ):
            budget.main([])
        text = "\n".join(str(call.args[0]) for call in printed.call_args_list if call.args)
        self.assertIn("설계 빈도의 절반도 안 도는", text)
        self.assertIn("econ", text)


if __name__ == "__main__":
    unittest.main()
