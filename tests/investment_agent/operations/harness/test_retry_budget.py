"""재시도 예산은 "handler가 실패한 횟수"로 센다 — 대기 복귀는 실패가 아니다.

`waiting`으로 폴링하는 stage(승인 대기·background로 감싼 13개)는 `resume_at`이 지나면
같은 자리로 다시 들어온다. 전에는 그때마다 `attempts`가 올라, 승인 TTL 15분을 15초마다
확인한 뒤(약 60회) 처음 만난 일시적 오류 하나가 `60 >= max_attempts`로 곧바로 terminal
실패가 됐다 — 선언한 재시도와 `retry_delay_seconds`가 한 번도 쓰이지 않았다(감사 OP2-01).
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from investment_agent.operations.harness.contracts import (
    JobDefinition,
    StageDefinition,
    StageOutcome,
)
from investment_agent.operations.harness.runtime import HarnessScheduler, JobRegistry
from investment_agent.operations.harness.state import JsonStateStore

T0 = datetime(2026, 9, 1, 22, 30, tzinfo=timezone.utc)


class _Reporter:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def event(self, *_a, **_k) -> None: ...

    def error(self, kind: str, **_fields) -> None:
        self.errors.append(kind)


class RetryBudgetTest(unittest.TestCase):
    def _scheduler(self, temp, handler, *, max_attempts: int, retry_delay: float):
        definition = JobDefinition(
            job_id="poller", interval_seconds=60.0, stale_after_seconds=600.0,
            stages=(StageDefinition(
                "run", handler, max_attempts=max_attempts, retry_delay_seconds=retry_delay,
            ),),
        )
        registry = JobRegistry()
        registry.register(definition)
        scheduler = HarnessScheduler(
            registry=registry, store=JsonStateStore(Path(temp) / "s.json"),
            environ={}, reporter=_Reporter(),
        )
        scheduler.start(now=T0, process_id=1)
        return scheduler

    def test_waiting_polls_do_not_consume_the_retry_budget(self):
        calls = {"n": 0}

        def handler(context):
            calls["n"] += 1
            # 열 번은 대기로 돌아오고, 그다음 한 번만 실제로 실패한다.
            if calls["n"] <= 10:
                return StageOutcome.waiting(resume_after_seconds=1.0)
            raise TimeoutError("transient")

        with tempfile.TemporaryDirectory() as temp:
            scheduler = self._scheduler(temp, handler, max_attempts=3, retry_delay=30.0)
            moment = T0
            for _ in range(12):
                scheduler.tick(now=moment)
                moment += timedelta(seconds=5)
            runtime = scheduler.state.jobs["poller"].stages["run"]
            # 대기 복귀로 attempts는 많이 올라갔지만 실패는 한 번이다.
            self.assertGreaterEqual(runtime.attempts, 11)
            self.assertEqual(runtime.failures, 1)
            # 재시도가 남아 있어야 한다 — terminal이 아니다.
            self.assertEqual(runtime.status, "waiting")
            self.assertNotEqual(scheduler.state.jobs["poller"].status, "failed")

    def test_the_budget_still_runs_out_on_repeated_real_failures(self):
        def handler(context):
            raise TimeoutError("always")

        with tempfile.TemporaryDirectory() as temp:
            scheduler = self._scheduler(temp, handler, max_attempts=2, retry_delay=1.0)
            moment = T0
            for _ in range(4):
                scheduler.tick(now=moment)
                moment += timedelta(seconds=5)
            runtime = scheduler.state.jobs["poller"].stages["run"]
            self.assertEqual(runtime.failures, 2)
            self.assertEqual(runtime.status, "failed")
            self.assertEqual(scheduler.state.jobs["poller"].status, "failed")


if __name__ == "__main__":
    unittest.main()
