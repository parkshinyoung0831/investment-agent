"""경제지표 발표 속보는 Actions cron이 아니라 하네스가 발표 시간대에 1분마다 확인한다(WF-01)."""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from threading import Event
from unittest import mock

from investment_agent.operations.adapters.data import DataAdapters, in_econ_release_window
from investment_agent.operations.commands.investment_harness import build_registry
from investment_agent.operations.harness.commands import CommandResult
from investment_agent.operations.harness.contracts import StageContext

UTC = timezone.utc
MONDAY_RELEASE = datetime(2026, 9, 21, 12, 31, tzinfo=UTC)   # 08:31 ET
MONDAY_EVENING = datetime(2026, 9, 21, 20, 0, tzinfo=UTC)
SATURDAY_RELEASE = datetime(2026, 9, 19, 12, 31, tzinfo=UTC)


class _Runner:
    def __init__(self) -> None:
        self.commands = []

    def run(self, command, *, stop_event):
        self.commands.append(command)
        return CommandResult(command.module, 0, 0.1)


class _Adapters(DataAdapters):
    def __init__(self, now: datetime) -> None:
        self.command_runner = _Runner()
        self.timeouts = {}
        self._now = now

    def now(self) -> datetime:
        return self._now


def _context(now: datetime) -> StageContext:
    return StageContext(job_id="econ_release_watch", run_id="run", stage_id="watch", attempt=1,
                        idempotency_key="key", now=now, stop_event=Event(), prior_metadata={}, completed_metadata={})


class ReleaseWindowTest(unittest.TestCase):
    def test_window_is_weekday_utc_12_to_15(self) -> None:
        self.assertTrue(in_econ_release_window(MONDAY_RELEASE))
        self.assertTrue(in_econ_release_window(datetime(2026, 9, 21, 15, 59, tzinfo=UTC)))
        self.assertFalse(in_econ_release_window(datetime(2026, 9, 21, 11, 59, tzinfo=UTC)))
        self.assertFalse(in_econ_release_window(datetime(2026, 9, 21, 16, 0, tzinfo=UTC)))
        self.assertFalse(in_econ_release_window(SATURDAY_RELEASE))


class WatchStageTest(unittest.TestCase):
    def test_outside_the_window_no_process_is_started(self) -> None:
        adapters = _Adapters(MONDAY_EVENING)
        outcome = adapters.watch_releases(_context(MONDAY_EVENING))
        self.assertEqual(outcome.status, "succeeded")
        self.assertEqual(adapters.command_runner.commands, [])

    def test_inside_the_window_runs_the_canonical_entry_and_notifies_when_a_token_exists(self) -> None:
        adapters = _Adapters(MONDAY_RELEASE)
        with mock.patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "x"}):
            adapters.watch_releases(_context(MONDAY_RELEASE))
        command = adapters.command_runner.commands[0]
        self.assertEqual(command.module, "investment_agent.operations.commands.econ_calendar_watch_releases")
        self.assertEqual(command.arguments, ("--poll-attempts", "1", "--notify"))

    def test_without_a_token_it_only_checks(self) -> None:
        adapters = _Adapters(MONDAY_RELEASE)
        with mock.patch.dict(os.environ, {}, clear=True):
            adapters.watch_releases(_context(MONDAY_RELEASE))
        self.assertEqual(adapters.command_runner.commands[0].arguments, ("--poll-attempts", "1"))


class RegistryTest(unittest.TestCase):
    def test_job_is_registered_when_the_adapters_provide_it_and_is_not_trading_gated(self) -> None:
        class Full:
            def __getattr__(self, name):
                return lambda *a, **k: None

        registry = build_registry(adapters=Full())
        job = registry.get("econ_release_watch")
        self.assertIsNotNone(job)
        self.assertEqual(job.interval_seconds, 60.0)
        self.assertFalse(any(stage.trading_sensitive or stage.approval_workflow_only for stage in job.stages))


class HarnessAndActionsShareOnePathTest(unittest.TestCase):
    """하네스(1차)와 Actions(안전망)가 같은 진입점·같은 발송 원장을 쓴다 — 둘이 겹쳐도 한 번만 나간다."""

    def test_both_call_the_same_entry_module(self) -> None:
        from pathlib import Path

        module = "investment_agent.operations.commands.econ_calendar_watch_releases"
        workflow = (Path(__file__).resolve().parents[4] / ".github" / "workflows" / "econ_calendar_watch.yml").read_text(
            encoding="utf-8")
        self.assertIn(module, workflow)
        adapters = _Adapters(MONDAY_RELEASE)
        adapters.watch_releases(_context(MONDAY_RELEASE))
        self.assertEqual(adapters.command_runner.commands[0].module, module)

    def test_the_entry_publishes_through_the_shared_ledger(self) -> None:
        """중복은 발송 전 원장 선점(`publish`)이 막는다 — 진입점이 원장을 우회하면 두 경로가 두 번 보낸다."""
        from pathlib import Path

        source = (Path(__file__).resolve().parents[4] / "src" / "investment_agent" / "notifications" / "econ_calendar"
                  / "run.py").read_text(encoding="utf-8")
        self.assertIn("publish(", source)


if __name__ == "__main__":
    unittest.main()
