"""실행 화면 로더가 주문 이벤트·대사 실행을 실제로 채운다(DB-03)."""
from __future__ import annotations

import unittest
from unittest import mock

from investment_agent.reporting.models import DataResult
from investment_agent.reporting.readers import dashboard


class ExecutionLoaderTest(unittest.TestCase):
    def _load(self, runtime):
        with mock.patch.object(dashboard, "_read", return_value=DataResult.ok(rows=[{"x": 1}], source="t")), \
             mock.patch.object(dashboard, "read_runtime_rows", side_effect=runtime):
            return dashboard.load_execution_data.__wrapped__() if hasattr(
                dashboard.load_execution_data, "__wrapped__") else dashboard.load_execution_data()

    def test_runtime_datasets_reach_the_payload_latest_first(self) -> None:
        data = {
            "order_events": [{"status": "filled"}],
            "reconciliation_runs": [{"started_at": "2026-09-01"}, {"started_at": "2026-09-02"}],
        }
        result = self._load(lambda name: data[name])
        self.assertEqual(result.value["order_events"], [{"status": "filled"}])
        self.assertEqual(result.value["reconciliations"][0]["started_at"], "2026-09-02")

    def test_runtime_failure_is_an_error_not_an_empty_history(self) -> None:
        def broken(name):
            raise OSError("locked")

        self.assertEqual(self._load(broken).status, "error")


if __name__ == "__main__":
    unittest.main()
