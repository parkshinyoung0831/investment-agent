"""하루 단위 job은 시작 시각에 맞춰 돌고, 분 단위 job은 완료 뒤 간격을 지킨다(OP-05)."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event

from investment_agent.operations.harness.contracts import JobDefinition, StageDefinition, StageOutcome
from investment_agent.operations.harness.lock import ProcessFileLock
from investment_agent.operations.harness.runtime import HarnessScheduler, JobRegistry
from investment_agent.operations.harness.service import HarnessService
from investment_agent.operations.harness.state import JsonStateStore

T0 = datetime(2026, 9, 1, 22, 30, tzinfo=timezone.utc)


class _Reporter:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def event(self, *_a, **_k) -> None: ...

    def error(self, kind: str, **_fields) -> None:
        self.errors.append(kind)


def _run(interval: float, *, duration: timedelta, checks: list[timedelta]) -> list[bool]:
    """T0에 시작해 `duration` 뒤 끝난 job이 `checks` 각 시점에 다시 도는지."""
    starts: list[datetime] = []
    clock = {"now": T0}

    def handler(context):
        starts.append(context.now)
        return StageOutcome.succeeded()

    definition = JobDefinition(
        job_id="cadence", interval_seconds=interval, stale_after_seconds=interval * 2,
        stages=(StageDefinition("run", handler, max_attempts=1),),
    )
    registry = JobRegistry()
    registry.register(definition)
    with tempfile.TemporaryDirectory() as temp:
        scheduler = HarnessScheduler(
            registry=registry, store=JsonStateStore(Path(temp) / "s.json"), environ={}, reporter=_Reporter(),
        )
        scheduler.start(now=T0, process_id=1)
        scheduler.tick(now=T0)
        # 실행 시간이 걸렸다는 것을 완료 시각으로 표현한다.
        job = scheduler.state.jobs["cadence"]
        job.completed_at = (T0 + duration).isoformat()
        ran: list[bool] = []
        for offset in checks:
            before = len(starts)
            scheduler.tick(now=T0 + offset)
            ran.append(len(starts) > before)
            if ran[-1]:
                scheduler.state.jobs["cadence"].completed_at = (T0 + offset + duration).isoformat()
        return ran


class CadenceAnchorTest(unittest.TestCase):
    def test_daily_job_keeps_its_start_time_despite_a_long_run(self) -> None:
        day = 24 * 3600.0
        ran = _run(day, duration=timedelta(minutes=40), checks=[timedelta(days=1) - timedelta(minutes=1),
                                                                   timedelta(days=1)])
        # 완료 시각 기준이면 T0+24h 시점에 아직 이르다(24h40m). 시작 기준이라 정각에 돈다.
        self.assertEqual(ran, [False, True])

    def test_daily_job_does_not_drift_over_a_week(self) -> None:
        day = 24 * 3600.0
        ran = _run(day, duration=timedelta(minutes=40), checks=[timedelta(days=n) for n in range(1, 8)])
        self.assertEqual(ran, [True] * 7)

    def test_polling_job_keeps_a_gap_after_a_slow_run(self) -> None:
        # 60초 주기 job이 50초 걸렸다: 시작 기준이면 완료 즉시 다시 도는데, 완료 뒤 60초를 지킨다.
        ran = _run(60.0, duration=timedelta(seconds=50), checks=[timedelta(seconds=61),
                                                                    timedelta(seconds=111)])
        self.assertEqual(ran, [False, True])


class HeartbeatFailureIsReportedTest(unittest.TestCase):
    def test_a_failing_heartbeat_write_is_reported_once_not_swallowed(self) -> None:
        reporter = _Reporter()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            scheduler = HarnessScheduler(
                registry=JobRegistry(), store=JsonStateStore(path / "s.json"), environ={}, reporter=reporter,
            )
            stop = Event()
            service = HarnessService(
                scheduler=scheduler, lock=ProcessFileLock(path / "l.lock"), poll_seconds=0.01, reporter=reporter,
            )
            calls = {"n": 0}

            def failing(now=None):
                calls["n"] += 1
                if calls["n"] >= 4:
                    service.request_stop()
                raise OSError("disk full")

            scheduler.update_process_heartbeat = failing
            service.stop_event = scheduler.stop_event = stop
            self.assertEqual(service.run_forever(install_signal_handlers=False), 0)
        self.assertGreaterEqual(calls["n"], 2)
        self.assertEqual(reporter.errors.count("heartbeat_failed"), 1)


if __name__ == "__main__":
    unittest.main()
