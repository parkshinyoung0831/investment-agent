from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from investment_agent.operations.harness.contracts import (
    HarnessMode,
    JobDefinition,
    StageDefinition,
    StageOutcome,
)
from investment_agent.operations.harness.health import inspect_health
from investment_agent.operations.harness.pipeline import investment_pipeline_job
from investment_agent.operations.harness.runtime import HarnessScheduler, JobRegistry
from investment_agent.operations.harness.state import JsonStateStore

UTC = timezone.utc
T0 = datetime(2026, 8, 22, 0, 0, tzinfo=UTC)


class FakeReporter:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []
        self.errors: list[tuple[str, dict]] = []

    def event(self, event_type: str, **fields):
        self.events.append((event_type, fields))

    def error(self, event_type: str, **fields):
        self.errors.append((event_type, fields))


def registry_with(definition: JobDefinition) -> JobRegistry:
    registry = JobRegistry()
    registry.register(definition)
    return registry


class HarnessSchedulerTest(unittest.TestCase):
    def test_pipeline_waits_for_approval_and_resumes_with_same_idempotency_key(self):
        calls: list[tuple[str, str]] = []
        listener_calls = 0

        def complete(context):
            calls.append((context.stage_id, context.idempotency_key))
            return StageOutcome.succeeded()

        def listener(context):
            nonlocal listener_calls
            listener_calls += 1
            calls.append((context.stage_id, context.idempotency_key))
            if listener_calls == 1:
                return StageOutcome.waiting(resume_after_seconds=60.0)
            return StageOutcome.succeeded({"approval": "recorded"})

        definition = investment_pipeline_job(
            analysis=complete,
            portfolio=complete,
            approval_listener=listener,
            approval_worker=complete,
            interval_seconds=3_600,
        )
        with tempfile.TemporaryDirectory() as temp:
            scheduler = HarnessScheduler(
                registry=registry_with(definition),
                store=JsonStateStore(Path(temp) / "state.json"),
                mode=HarnessMode.APPROVAL_WORKFLOW,
                environ={"TRADING_KILL_SWITCH": "off"},
                reporter=FakeReporter(),
            )
            scheduler.start(now=T0, process_id=7)
            scheduler.tick(now=T0)
            job = scheduler.state.jobs[definition.job_id]
            self.assertEqual(job.status, "waiting")
            self.assertEqual([item[0] for item in calls], [
                "analysis", "portfolio", "approval_listener",
            ])
            scheduler.tick(now=T0 + timedelta(seconds=30))
            self.assertEqual(listener_calls, 1)
            scheduler.tick(now=T0 + timedelta(seconds=61))
            self.assertEqual(job.status, "succeeded")
            self.assertEqual([item[0] for item in calls][-2:], [
                "approval_listener", "approval_worker",
            ])
            listener_keys = [key for stage, key in calls if stage == "approval_listener"]
            self.assertEqual(len(set(listener_keys)), 1)

    def test_completed_job_is_not_duplicated_before_interval(self):
        calls: list[str] = []

        def handler(context):
            calls.append(context.run_id)
            return StageOutcome.succeeded()

        definition = JobDefinition(
            job_id="daily_analysis",
            stages=(StageDefinition("analysis", handler),),
            interval_seconds=3_600,
        )
        with tempfile.TemporaryDirectory() as temp:
            scheduler = HarnessScheduler(
                registry=registry_with(definition),
                store=JsonStateStore(Path(temp) / "state.json"),
                environ={},
                reporter=FakeReporter(),
            )
            scheduler.start(now=T0)
            scheduler.tick(now=T0)
            first_run = scheduler.state.jobs[definition.job_id].run_id
            scheduler.tick(now=T0 + timedelta(minutes=30))
            self.assertEqual(calls, [first_run])
            scheduler.tick(now=T0 + timedelta(hours=1, seconds=1))
            self.assertEqual(len(calls), 2)
            self.assertNotEqual(calls[0], calls[1])

    def test_later_stage_receives_only_completed_stage_metadata(self):
        observed = {}

        def first(context):
            return StageOutcome.succeeded({"batch_id": "signal_batch_safe"})

        def second(context):
            observed.update(context.completed_metadata)
            return StageOutcome.succeeded()

        definition = JobDefinition(
            job_id="metadata_pipeline",
            stages=(
                StageDefinition("first", first),
                StageDefinition("second", second),
            ),
            interval_seconds=60,
        )
        with tempfile.TemporaryDirectory() as temp:
            scheduler = HarnessScheduler(
                registry=registry_with(definition),
                store=JsonStateStore(Path(temp) / "state.json"),
                environ={},
                reporter=FakeReporter(),
            )
            scheduler.start(now=T0)
            scheduler.tick(now=T0)
        self.assertEqual(observed, {
            "first": {"batch_id": "signal_batch_safe"},
        })

    def test_read_only_approval_job_ignores_trading_kill_but_not_analysis_mode(self):
        calls = []

        def handler(context):
            calls.append(context.stage_id)
            return StageOutcome.succeeded()

        definition = JobDefinition(
            job_id="account_watch",
            stages=(StageDefinition(
                "capture",
                handler,
                approval_workflow_only=True,
                trading_sensitive=False,
            ),),
            interval_seconds=60,
        )
        with tempfile.TemporaryDirectory() as temp:
            scheduler = HarnessScheduler(
                registry=registry_with(definition),
                store=JsonStateStore(Path(temp) / "state.json"),
                mode=HarnessMode.APPROVAL_WORKFLOW,
                environ={"TRADING_KILL_SWITCH": "on"},
                reporter=FakeReporter(),
            )
            scheduler.start(now=T0)
            scheduler.tick(now=T0)
            self.assertEqual(calls, ["capture"])
        calls.clear()
        with tempfile.TemporaryDirectory() as temp:
            scheduler = HarnessScheduler(
                registry=registry_with(definition),
                store=JsonStateStore(Path(temp) / "state.json"),
                mode=HarnessMode.ANALYSIS_ONLY,
                environ={"TRADING_KILL_SWITCH": "off"},
                reporter=FakeReporter(),
            )
            scheduler.start(now=T0)
            scheduler.tick(now=T0)
            self.assertEqual(calls, [])
            self.assertEqual(
                scheduler.state.jobs["account_watch"].pause_reason,
                "analysis_only_mode",
            )

    def test_analysis_only_and_global_kill_pause_sensitive_stages(self):
        calls: list[str] = []

        def handler(context):
            calls.append(context.stage_id)
            return StageOutcome.succeeded()

        definition = investment_pipeline_job(
            analysis=handler,
            portfolio=handler,
            approval_listener=handler,
            approval_worker=handler,
        )
        with tempfile.TemporaryDirectory() as temp:
            environment = {"TRADING_KILL_SWITCH": "off"}
            scheduler = HarnessScheduler(
                registry=registry_with(definition),
                store=JsonStateStore(Path(temp) / "state.json"),
                mode=HarnessMode.ANALYSIS_ONLY,
                environ=environment,
                reporter=FakeReporter(),
            )
            scheduler.start(now=T0)
            scheduler.tick(now=T0)
            job = scheduler.state.jobs[definition.job_id]
            self.assertEqual(calls, ["analysis", "portfolio"])
            self.assertEqual(job.status, "paused")
            self.assertEqual(job.pause_reason, "analysis_only_mode")
            blocked_count = sum(1 for event, _ in scheduler.reporter.events if event == "stage_blocked")
            scheduler.tick(now=T0 + timedelta(seconds=10))
            self.assertEqual(
                sum(1 for event, _ in scheduler.reporter.events if event == "stage_blocked"),
                blocked_count,
            )

        with tempfile.TemporaryDirectory() as temp:
            scheduler = HarnessScheduler(
                registry=registry_with(definition),
                store=JsonStateStore(Path(temp) / "state.json"),
                mode=HarnessMode.APPROVAL_WORKFLOW,
                environ={},
                reporter=FakeReporter(),
            )
            calls.clear()
            scheduler.start(now=T0)
            scheduler.tick(now=T0)
            job = scheduler.state.jobs[definition.job_id]
            self.assertEqual(calls, ["analysis", "portfolio"])
            self.assertEqual(job.pause_reason, "trading_kill_switch")

    def test_job_kill_switch_blocks_the_whole_job_until_released(self):
        calls: list[str] = []

        def handler(context):
            calls.append(context.stage_id)
            return StageOutcome.succeeded()

        definition = JobDefinition(
            job_id="daily_analysis",
            stages=(StageDefinition("analysis", handler),),
            interval_seconds=60,
        )
        environment = {"HARNESS_JOB_DAILY_ANALYSIS_KILL_SWITCH": "on"}
        with tempfile.TemporaryDirectory() as temp:
            scheduler = HarnessScheduler(
                registry=registry_with(definition),
                store=JsonStateStore(Path(temp) / "state.json"),
                environ=environment,
                reporter=FakeReporter(),
            )
            scheduler.start(now=T0)
            scheduler.tick(now=T0)
            self.assertEqual(calls, [])
            self.assertNotIn(definition.job_id, scheduler.state.jobs)
            environment["HARNESS_JOB_DAILY_ANALYSIS_KILL_SWITCH"] = "off"
            scheduler.tick(now=T0 + timedelta(seconds=1))
            self.assertEqual(calls, ["analysis"])

    def test_failure_retries_then_alerts_terminal_error_without_exception_text(self):
        reporter = FakeReporter()

        def failure(context):
            raise RuntimeError("DISCORD_BOT_TOKEN=must-not-leak")

        definition = JobDefinition(
            job_id="failing_analysis",
            stages=(StageDefinition(
                "analysis", failure, max_attempts=2, retry_delay_seconds=10,
            ),),
            interval_seconds=3_600,
        )
        with tempfile.TemporaryDirectory() as temp:
            scheduler = HarnessScheduler(
                registry=registry_with(definition),
                store=JsonStateStore(Path(temp) / "state.json"),
                environ={},
                reporter=reporter,
            )
            scheduler.start(now=T0)
            scheduler.tick(now=T0)
            job = scheduler.state.jobs[definition.job_id]
            self.assertEqual(job.status, "waiting")
            scheduler.tick(now=T0 + timedelta(seconds=11))
            self.assertEqual(job.status, "failed")
            self.assertEqual(job.stages["analysis"].last_error, "RuntimeError")
            self.assertNotIn("must-not-leak", repr(reporter.errors))
            self.assertEqual(len(reporter.errors), 2)

    def test_restart_recovers_running_stage_and_health_detects_stale(self):
        calls: list[tuple[int, str]] = []

        def handler(context):
            calls.append((context.attempt, context.idempotency_key))
            return StageOutcome.waiting(resume_after_seconds=300)

        definition = JobDefinition(
            job_id="recovered_analysis",
            stages=(StageDefinition("analysis", handler),),
            interval_seconds=3_600,
            stale_after_seconds=90,
        )
        with tempfile.TemporaryDirectory() as temp:
            store = JsonStateStore(Path(temp) / "state.json")
            first = HarnessScheduler(
                registry=registry_with(definition), store=store,
                environ={}, reporter=FakeReporter(),
            )
            first.start(now=T0)
            first.tick(now=T0)
            job = first.state.jobs[definition.job_id]
            job.status = "running"
            job.stages["analysis"].status = "running"
            store.save(first.state)

            registry = registry_with(definition)
            restarted = HarnessScheduler(
                registry=registry, store=store, environ={}, reporter=FakeReporter(),
            )
            recovered = restarted.start(now=T0 + timedelta(seconds=10))
            self.assertEqual(recovered, (definition.job_id,))
            restarted.tick(now=T0 + timedelta(seconds=10))
            self.assertEqual(calls[0][1], calls[1][1])
            self.assertEqual(calls[1][0], 2)

            fresh = inspect_health(
                store=store,
                registry=registry,
                now=T0 + timedelta(seconds=60),
                process_stale_after_seconds=120,
            )
            self.assertTrue(fresh.healthy)
            stale = inspect_health(
                store=store,
                registry=registry,
                now=T0 + timedelta(seconds=200),
                process_stale_after_seconds=120,
            )
            self.assertFalse(stale.healthy)
            self.assertEqual(stale.process_status, "stale")
            self.assertEqual(stale.stale_jobs, (definition.job_id,))


if __name__ == "__main__":
    unittest.main()
