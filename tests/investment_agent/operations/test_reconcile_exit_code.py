"""대사 명령의 종료 코드는 "재실행하면 달라지는가"를 뜻해야 한다.

전에는 `unresolved_unknown`·`external_open_order_ids`·`position_mismatches`가 비지
않으면 1을 돌려줬다. 그 셋은 사람이 확인할 사실이고 재실행으로 사라지지 않으므로,
토스 앱에서 직접 낸 미체결 주문 하나가 `toss_reconciliation` job을 60초마다 영구
실패시켰다. 실패마다 운영 채널로 경보가 나가 진짜 대사 장애가 묻혔다(감사 OP2-19).
"""
from __future__ import annotations

import unittest
from unittest import mock

from investment_agent.execution.reconciliation.positions import PositionMismatch
from investment_agent.execution.reconciliation.worker import ReconciliationSummary
from investment_agent.operations.commands import reconcile_toss


def _summary(**overrides) -> ReconciliationSummary:
    base = dict(
        inspected=1, updated=0, unresolved_unknown=(), external_open_order_ids=(),
        completed_intents=(), failed_intents=(), card_updates=(),
        position_check="ok", position_mismatches=(),
    )
    base.update(overrides)
    return ReconciliationSummary(**base)


class ReconcileExitCodeTest(unittest.TestCase):
    def _run(self, summary):
        published = mock.Mock(failed=(), sent=())
        with (
            mock.patch.object(reconcile_toss.toss, "resolve_account_seq", return_value=7),
            mock.patch.object(reconcile_toss, "ExecutionRepository"),
            mock.patch.object(reconcile_toss, "TossOrderApi"),
            mock.patch.object(reconcile_toss, "publish_reconciliation_statuses", return_value=published),
            mock.patch.object(reconcile_toss, "TossReconciliationWorker") as worker,
            mock.patch.object(reconcile_toss, "HarnessReporter") as reporter_cls,
        ):
            worker.return_value.run_once.return_value = summary
            reporter = reporter_cls.return_value
            code = reconcile_toss.main([])
        return code, reporter

    def test_operator_findings_do_not_make_the_job_fail(self):
        code, reporter = self._run(_summary(
            external_open_order_ids=("B1",),
            position_mismatches=(PositionMismatch("AAPL", 10.0, 12.0),),
        ))
        self.assertEqual(code, 0)
        # 조용해지지는 않는다 — 발견 사항은 한 번 올라간다.
        events = [call.args[0] for call in reporter.error.call_args_list]
        self.assertIn("toss_reconciliation_needs_operator_review", events)

    def test_a_clean_pass_reports_nothing(self):
        code, reporter = self._run(_summary())
        self.assertEqual(code, 0)
        self.assertEqual(reporter.error.call_args_list, [])

    def test_an_execution_failure_still_fails(self):
        published = mock.Mock(failed=(), sent=())
        with (
            mock.patch.object(reconcile_toss.toss, "resolve_account_seq", return_value=7),
            mock.patch.object(reconcile_toss, "ExecutionRepository"),
            mock.patch.object(reconcile_toss, "TossOrderApi"),
            mock.patch.object(reconcile_toss, "publish_reconciliation_statuses", return_value=published),
            mock.patch.object(reconcile_toss, "TossReconciliationWorker") as worker,
            mock.patch.object(reconcile_toss, "HarnessReporter") as reporter_cls,
        ):
            worker.return_value.run_once.side_effect = RuntimeError("broker down")
            code = reconcile_toss.main([])
            reporter = reporter_cls.return_value
        self.assertEqual(code, 1)
        self.assertIn("toss_reconciliation_failed", [c.args[0] for c in reporter.error.call_args_list])


if __name__ == "__main__":
    unittest.main()
