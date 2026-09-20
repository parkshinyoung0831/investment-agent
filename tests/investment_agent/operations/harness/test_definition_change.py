"""배포로 stage 정의가 바뀌어도 저장된 실행 중 job 때문에 하네스가 죽지 않는다(OP-02)."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from investment_agent.operations.harness.contracts import HarnessMode, JobDefinition, StageDefinition, StageOutcome
from investment_agent.operations.harness.runtime import HarnessScheduler, JobRegistry
from investment_agent.operations.harness.state import JsonStateStore

T0 = datetime(2026, 8, 22, tzinfo=timezone.utc)


class _Reporter:
    def __init__(self) -> None:
        self.events: list[str] = []

    def event(self, kind: str, **_fields) -> None:
        self.events.append(kind)

    def error(self, *_a, **_k) -> None: ...


def _definition(*stage_ids: str, waiting_first: bool = False) -> JobDefinition:
    def handler(_context):
        return StageOutcome.waiting(resume_after_seconds=600.0) if waiting_first else StageOutcome.succeeded()

    return JobDefinition(
        job_id="pipeline", interval_seconds=3600, stale_after_seconds=180.0,
        stages=tuple(StageDefinition(stage_id, handler, max_attempts=2) for stage_id in stage_ids),
    )


def _scheduler(definition: JobDefinition, path: Path, reporter: _Reporter) -> HarnessScheduler:
    registry = JobRegistry()
    registry.register(definition)
    return HarnessScheduler(
        registry=registry, store=JsonStateStore(path), mode=HarnessMode.ANALYSIS_ONLY,
        environ={"TRADING_KILL_SWITCH": "on"}, reporter=reporter,
    )


class DefinitionChangeTest(unittest.TestCase):
    def test_waiting_job_with_an_old_stage_set_is_replaced_not_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.json"
            old = _scheduler(_definition("a", waiting_first=True), path, _Reporter())
            old.start(now=T0, process_id=1)
            old.tick(now=T0)
            self.assertEqual(old.state.jobs["pipeline"].status, "waiting")

            reporter = _Reporter()
            new = _scheduler(_definition("a", "b"), path, reporter)
            new.start(now=T0, process_id=2)
            new.tick(now=T0)  # 예전에는 KeyError: 'b'
            job = new.state.jobs["pipeline"]
            self.assertEqual(set(job.stages), {"a", "b"})
            self.assertIn("job_replaced", reporter.events)


class IntervalProviderTest(unittest.TestCase):
    """적응형 주기는 시작 시각이 아니라 판정 시각으로 계산한다(OP-03)."""

    def test_due_time_follows_the_provider_at_decision_time(self) -> None:
        from datetime import timedelta

        calls: list[int] = []

        def handler(_context):
            calls.append(1)
            return StageOutcome.succeeded()

        # 낮(T0~T0+1h)에는 60초, 그 뒤에는 300초.
        provider = lambda now: 60.0 if now < T0 + timedelta(hours=1) else 300.0
        definition = JobDefinition(
            job_id="reconcile", interval_seconds=300.0, stale_after_seconds=180.0,
            stages=(StageDefinition("run", handler, max_attempts=1),), interval_provider=provider,
        )
        with tempfile.TemporaryDirectory() as temp:
            scheduler = _scheduler(definition, Path(temp) / "s.json", _Reporter())
            scheduler.start(now=T0, process_id=1)
            scheduler.tick(now=T0)
            scheduler.tick(now=T0 + timedelta(seconds=61))     # 60초 주기 → 다시 돈다
            self.assertEqual(len(calls), 2)
            late = T0 + timedelta(hours=2)
            scheduler.tick(now=late)                            # 이전 실행이 오래돼 due
            scheduler.tick(now=late + timedelta(seconds=61))    # 300초 주기 → 아직 아님
            self.assertEqual(len(calls), 3)

    def test_provider_must_return_a_positive_finite_value(self) -> None:
        definition = JobDefinition(
            job_id="x", interval_seconds=60.0,
            stages=(StageDefinition("run", lambda _c: StageOutcome.succeeded(), max_attempts=1),),
            interval_provider=lambda _now: 0.0,
        )
        with self.assertRaises(ValueError):
            definition.interval_at(T0)


if __name__ == "__main__":
    unittest.main()
