"""레지스트리에 없는 job은 집계를 흐리지 않고, 성공에 가려진 단계 실패는 드러난다(OP-07·OP-08)."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from investment_agent.operations.harness.contracts import JobDefinition, StageDefinition, StageOutcome
from investment_agent.operations.harness.health import inspect_health
from investment_agent.operations.harness.runtime import HarnessScheduler, JobRegistry
from investment_agent.operations.harness.state import JobRuntime, JsonStateStore, StageRuntime, utc_iso

T0 = datetime(2026, 9, 21, 3, 0, tzinfo=timezone.utc)


class _Reporter:
    def event(self, *_a, **_k) -> None: ...

    def error(self, *_a, **_k) -> None: ...


def _job(handler, job_id: str = "intel") -> JobDefinition:
    return JobDefinition(
        job_id=job_id, interval_seconds=24 * 3600, stale_after_seconds=3600,
        stages=(StageDefinition("news", handler, max_attempts=1),),
    )


def _run(definition: JobDefinition, path: Path) -> tuple[JsonStateStore, JobRegistry]:
    registry = JobRegistry()
    registry.register(definition)
    store = JsonStateStore(path)
    scheduler = HarnessScheduler(registry=registry, store=store, environ={}, reporter=_Reporter())
    scheduler.start(now=T0, process_id=1)
    scheduler.tick(now=T0)
    return store, registry


class OrphanJobsTest(unittest.TestCase):
    def test_a_job_without_a_definition_is_reported_apart_and_not_counted_as_paused(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, registry = _run(_job(lambda _c: StageOutcome.succeeded()), Path(temp) / "s.json")
            state = store.load()
            stamp = utc_iso(T0)
            state.jobs["investment_pipeline"] = JobRuntime(
                job_id="investment_pipeline", run_id="run_x", status="paused", scheduled_at=stamp,
                started_at=stamp, heartbeat_at=stamp, stages={"select_signal": StageRuntime()},
                pause_reason="job_kill_switch",
            )
            store.save(state)
            report = inspect_health(store=store, registry=registry, now=T0 + timedelta(seconds=30))
        self.assertEqual(report.orphan_jobs, ("investment_pipeline",))
        self.assertNotIn("investment_pipeline", report.paused_jobs)
        self.assertNotIn("investment_pipeline", report.stale_jobs)


class DegradedJobsTest(unittest.TestCase):
    def test_a_skipped_step_with_an_error_marks_the_job_degraded_but_still_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, registry = _run(
                _job(lambda _c: StageOutcome.skipped({"error_type": "HTTPError"})), Path(temp) / "s.json",
            )
            report = inspect_health(store=store, registry=registry, now=T0 + timedelta(seconds=30))
        self.assertEqual(report.degraded_jobs, ("intel",))
        self.assertTrue(report.healthy)  # 다음 단계를 살리려는 선택이라 job 상태는 바꾸지 않는다

    def test_a_clean_run_is_not_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, registry = _run(_job(lambda _c: StageOutcome.succeeded({"stored": 3})), Path(temp) / "s.json")
            report = inspect_health(store=store, registry=registry, now=T0 + timedelta(seconds=30))
        self.assertEqual(report.degraded_jobs, ())


if __name__ == "__main__":
    unittest.main()
