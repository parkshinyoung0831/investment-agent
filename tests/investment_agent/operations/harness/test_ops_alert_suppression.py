"""같은 사건이 반복되면 webhook은 한동안 다시 보내지 않는다 — 로그는 매번 남는다.

주기 60초 job이 영구 원인으로 실패하면 stage 실패마다 webhook POST가 나가 하루 약
1,400건이 되고, Discord 한도에서 나는 429는 `notify_ops`가 삼킨다. 그러면 **다른 실패
알림이 그 홍수에 묻힌다**(감사 OP2-15).
"""
from __future__ import annotations

import unittest

from investment_agent.operations.harness.reporting import (
    OPS_ALERT_REPEAT_SECONDS,
    HarnessReporter,
)


class _Alerts:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(self, event) -> bool:
        self.sent.append(dict(event))
        return True


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class _Logger:
    def __init__(self) -> None:
        self.errors = 0

    def error(self, *args, **kwargs) -> None:
        self.errors += 1

    def info(self, *args, **kwargs) -> None:
        pass


class OpsAlertSuppressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.alerts = _Alerts()
        self.clock = _Clock()
        self.logger = _Logger()
        self.reporter = HarnessReporter(
            logger=self.logger, alerts=self.alerts, monotonic=self.clock
        )

    def test_sixty_repeats_of_one_cause_send_once(self):
        for _ in range(60):
            self.reporter.error("stage_failed", job_id="earnings_watch", stage_id="scan",
                               error_type="CommandExecutionError")
            self.clock.value += 60.0
        # 30분 창이므로 60분 동안은 2번만 나간다.
        self.assertLessEqual(len(self.alerts.sent), 2)
        self.assertGreaterEqual(len(self.alerts.sent), 1)
        # 로그는 억제하지 않는다 — 사실이 사라지지 않는다.
        self.assertEqual(self.logger.errors, 60)

    def test_a_different_job_is_not_suppressed_together(self):
        self.reporter.error("stage_failed", job_id="earnings_watch", stage_id="scan",
                            error_type="CommandExecutionError")
        self.reporter.error("stage_failed", job_id="toss_reconciliation", stage_id="scan",
                            error_type="CommandExecutionError")
        self.assertEqual(len(self.alerts.sent), 2)

    def test_a_new_error_type_on_the_same_job_is_not_suppressed(self):
        self.reporter.error("stage_failed", job_id="watch", error_type="TimeoutError")
        self.reporter.error("stage_failed", job_id="watch", error_type="ValueError")
        self.assertEqual(len(self.alerts.sent), 2)

    def test_the_repeat_report_carries_how_many_were_suppressed(self):
        for _ in range(5):
            self.reporter.error("stage_failed", job_id="watch", error_type="TimeoutError")
        self.clock.value += OPS_ALERT_REPEAT_SECONDS + 1
        self.reporter.error("stage_failed", job_id="watch", error_type="TimeoutError")
        self.assertEqual(len(self.alerts.sent), 2)
        self.assertEqual(self.alerts.sent[-1]["suppressed_repeats"], 4)

    def test_a_quiet_gap_sends_again_without_a_suppression_count(self):
        self.reporter.error("stage_failed", job_id="watch", error_type="TimeoutError")
        self.clock.value += OPS_ALERT_REPEAT_SECONDS + 1
        self.reporter.error("stage_failed", job_id="watch", error_type="TimeoutError")
        self.assertEqual(len(self.alerts.sent), 2)
        self.assertNotIn("suppressed_repeats", self.alerts.sent[-1])


if __name__ == "__main__":
    unittest.main()
