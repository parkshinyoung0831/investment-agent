"""BackgroundStages — 워커 용량 부족과 무한 대기를 실패로 드러내는지 검증한다(감사 OP2-02·OP2-03)."""
from __future__ import annotations

import time
import unittest
from dataclasses import dataclass
from threading import Event

from investment_agent.operations.harness.background import BackgroundStages, StageTimeoutError
from investment_agent.operations.harness.contracts import StageOutcome


@dataclass
class _Context:
    job_id: str
    run_id: str
    stage_id: str


def _context(*, run_id: str = "run-1", stage_id: str = "stage-1") -> _Context:
    return _Context(job_id="job-1", run_id=run_id, stage_id=stage_id)


class BackgroundStagesTest(unittest.TestCase):
    def test_first_call_submits_and_returns_waiting_until_done(self) -> None:
        release = Event()
        started = Event()

        def handler(_context):
            started.set()
            release.wait(timeout=5)
            return StageOutcome.succeeded({"done": True})

        stages = BackgroundStages(max_workers=2)
        wrapped = stages.wrap(handler)
        outcome = wrapped(_context())
        self.assertEqual(outcome.status, "waiting")
        self.assertTrue(started.wait(timeout=1))
        release.set()

        # 완료될 때까지 폴링한다 — 스레드 완료 타이밍은 테스트 환경에 따라 다르다.
        deadline = time.monotonic() + 2
        outcome = None
        while time.monotonic() < deadline:
            outcome = wrapped(_context())
            if outcome.status == "succeeded":
                break
            time.sleep(0.01)
        self.assertEqual(outcome.status, "succeeded")
        self.assertEqual(outcome.metadata, {"done": True})
        stages.executor.shutdown(wait=False)

    def test_a_stage_stuck_past_its_timeout_raises_instead_of_waiting_forever(self) -> None:
        """워커가 부족해 시작도 못 했거나, 시작했지만 안 끝나는 경우를 구분하지 않고 실패로 올린다."""
        release = Event()

        def handler(_context):
            release.wait(timeout=5)
            return StageOutcome.succeeded()

        stages = BackgroundStages(max_workers=2)
        wrapped = stages.wrap(handler, timeout_seconds=0.05)
        wrapped(_context())  # 제출
        time.sleep(0.1)
        with self.assertRaises(StageTimeoutError):
            wrapped(_context())
        # 타임아웃으로 실패시킨 뒤에는 같은 key를 더 이상 추적하지 않는다 — 재시도가 새로 제출한다.
        self.assertEqual(stages.pending, {})
        release.set()
        stages.executor.shutdown(wait=True)

    def test_without_a_timeout_it_waits_forever_like_before(self) -> None:
        release = Event()

        def handler(_context):
            release.wait(timeout=5)
            return StageOutcome.succeeded()

        stages = BackgroundStages(max_workers=1)
        wrapped = stages.wrap(handler)  # timeout_seconds=None
        outcome = wrapped(_context())
        self.assertEqual(outcome.status, "waiting")
        time.sleep(0.1)
        outcome = wrapped(_context())
        self.assertEqual(outcome.status, "waiting")  # 여전히 대기 — 예외 없음
        release.set()
        stages.executor.shutdown(wait=True)

    def test_a_stale_run_entry_for_the_same_stage_is_dropped_not_accumulated(self) -> None:
        """잡이 재시작돼 run_id가 바뀌면 옛 run의 pending 항목이 쌓이지 않는다(감사 OP2-02)."""
        release = Event()

        def handler(_context):
            release.wait(timeout=5)
            return StageOutcome.succeeded()

        stages = BackgroundStages(max_workers=2)
        wrapped = stages.wrap(handler)
        wrapped(_context(run_id="run-old", stage_id="stage-1"))
        self.assertEqual(len(stages.pending), 1)
        wrapped(_context(run_id="run-new", stage_id="stage-1"))
        # 같은 stage_id의 새 run이 오면 옛 run 항목은 버려지고 새 항목 하나만 남는다.
        self.assertEqual(list(stages.pending), [("run-new", "stage-1")])
        release.set()
        stages.executor.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
