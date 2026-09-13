"""알림 등록·전송이 실패하면 진입점이 실패로 끝나는지 검증한다.

producer는 서비스 결과를 버리는 경우가 많다. 진입점이 끝에서 묻지 않으면 등록 실패가
경고 로그 한 줄로만 남고 GitHub Actions 잡은 초록색으로 끝난다 — 실적 정밀 카드가
그렇게 며칠 동안 한 장도 나가지 않았다.
"""
from __future__ import annotations

import importlib
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from investment_agent.notifications.problems import note_problem, take_problems

class EntrypointExitCodeTest(unittest.TestCase):
    def setUp(self) -> None:
        take_problems()
        self.addCleanup(take_problems)

    def _notify_main(self, dispatch) -> int:
        from investment_agent.operations.commands import notify

        with (
            patch.object(sys, "argv", ["notify", "--kind", "strategy"]),
            patch.object(notify, "_dispatch", side_effect=dispatch),
        ):
            return notify.main()

    def test_notify_fails_when_a_producer_swallowed_a_problem(self) -> None:
        exit_code = self._notify_main(lambda _target: note_problem("strategy", "summary:2026-10", "알림 저장 실패"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(take_problems(), ())

    def test_notify_succeeds_without_problems(self) -> None:
        self.assertEqual(self._notify_main(lambda _target: None), 0)

    def test_problems_from_before_the_run_are_not_charged_to_it(self) -> None:
        note_problem("macro", "core:2026-09-12", "이전 실행의 잔여")

        self.assertEqual(self._notify_main(lambda _target: None), 0)

    def test_macro_entrypoints_called_directly_by_workflows_fail_too(self) -> None:
        from investment_agent.notifications.macro import core, watch

        def swallow(*_args, **_kwargs):
            note_problem("macro", "watch:2026-09-12", "알림 저장 실패")

        for module in (watch, core):
            with self.subTest(module=module.__name__), patch.object(module, "run", side_effect=swallow):
                self.assertEqual(module.main([]), 1)

    def test_econ_watcher_reports_swallowed_notification_problems(self) -> None:
        """수집과 한 프로세스인 감시기도 발송 문제를 재실행 가능한 실패로 올린다."""
        calendar_name = "investment_agent.data.macro.application.release_calendar"
        calendar = types.ModuleType(calendar_name)
        calendar.watch_once = Mock(return_value={"due": 0, "first_actuals": 0, "failures": []})
        application = importlib.import_module("investment_agent.data.macro.application")
        had_calendar = "release_calendar" in vars(application)
        previous_calendar = vars(application).get("release_calendar")
        self.addCleanup(
            lambda: setattr(application, "release_calendar", previous_calendar) if had_calendar
            else vars(application).pop("release_calendar", None)
        )
        releases_db = importlib.import_module("investment_agent.data.macro.releases.db")
        econ_run = importlib.import_module("investment_agent.notifications.econ_calendar.run")
        watcher_name = "investment_agent.operations.commands.econ_calendar_watch_releases"
        with patch.dict(sys.modules):
            try:
                watcher = importlib.import_module(watcher_name)
            except ImportError:
                # 수집 모듈이 로컬 DLL 정책으로 막힌 환경에서도 발송 경계만 따로 검증한다.
                sys.modules[calendar_name] = calendar
                sys.modules.pop(watcher_name, None)
                watcher = importlib.import_module(watcher_name)
            swallow = Mock(side_effect=lambda: note_problem("macro_releases", "first_actual:US_CPI:2026-08-01", "x") or 0)
            with (
                patch.object(watcher, "etl", calendar),
                patch.object(releases_db, "configure"),
                patch.object(releases_db, "seed_catalog"),
                patch.object(econ_run, "run", swallow),
                patch("investment_agent.config.load_config", return_value=Mock()),
                patch("investment_agent.platform.db.postgres.Database.from_config", return_value=Mock()),
            ):
                self.assertEqual(watcher.main(["--notify", "--poll-attempts", "1"]), 1)
                swallow.side_effect = lambda: 0
                self.assertEqual(watcher.main(["--notify", "--poll-attempts", "1"]), 0)


if __name__ == "__main__":
    unittest.main()
