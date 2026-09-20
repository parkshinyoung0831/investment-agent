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


if __name__ == "__main__":
    unittest.main()
