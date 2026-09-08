from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from investment_agent.operations.commands.investment_harness import build_registry, main
from investment_agent.operations.harness.contracts import HarnessMode, StageOutcome
from investment_agent.operations.harness.runtime import HarnessScheduler
from investment_agent.operations.harness.state import JsonStateStore


class HarnessEntryBoundaryTest(unittest.TestCase):
    def test_default_is_dry_run_and_does_not_create_state(self):
        with tempfile.TemporaryDirectory() as temp:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(["--state-dir", temp])
            self.assertEqual(result, 0)
            self.assertIn('"dry_run":true', output.getvalue())
            self.assertFalse((Path(temp) / "state.json").exists())

    def test_harness_source_has_no_execution_or_broker_dependency(self):
        root = Path(__file__).resolve().parents[4]
        paths = list(
            (
                root
                / "src"
                / "investment_agent"
                / "operations"
                / "harness"
            ).glob("*.py")
        )
        paths.append(root / "src" / "investment_agent" / "operations" / "commands" / "investment_harness.py")
        combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
        for forbidden in ("investment_agent.execution", "submit_order", "/api/v1/orders", "toss_manual"):
            self.assertNotIn(forbidden, combined)

    def test_analysis_keeps_its_daily_cycle_while_live_workflow_is_paused(self):
        calls = []

        def handler(context):
            calls.append((context.job_id, context.stage_id))
            return StageOutcome.succeeded()

        adapters = SimpleNamespace(
            analysis=handler,
            select_signal=handler,
            portfolio=handler,
            execution_intent=handler,
            approval_request=handler,
            approval_worker=handler,
            risk_snapshot=handler,
            reconcile=handler,
            watch=handler,
            build_valuations=handler,
            build_features=handler,
            build_labels=handler,
            build_training_samples=handler,
            build_events=handler,
            evaluate_decisions=handler,
            notify_investment=handler,
            notify_trades=handler,
            # 수집 단계는 stage handler와 서명이 다르다(database_path 하나를 받는다).
            # 넘기지 않으면 진짜 provider가 붙어 이 테스트가 네트워크를 때린다.
            collect_news=lambda _path=None: {"stored": 0},
            collect_social=lambda _path=None: {"status": "skipped", "stored": 0},
            prune_intelligence=lambda _path=None: {"total": 0},
        )
        registry = build_registry(interval_seconds=60, adapters=adapters)
        start = datetime(2026, 8, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp:
            scheduler = HarnessScheduler(
                registry=registry,
                store=JsonStateStore(Path(temp) / "state.json"),
                mode=HarnessMode.ANALYSIS_ONLY,
                environ={"TRADING_KILL_SWITCH": "off"},
            )
            scheduler.start(now=start)
            scheduler.tick(now=start)
            self.assertEqual(calls, [
                ("account_risk_snapshot", "capture"),
                ("earnings_watch", "watch"),
                ("feature_store", "build_valuations"),
                ("feature_store", "build_features"),
                ("feature_store", "build_labels"),
                ("feature_store", "build_training_samples"),
                # 과거 판단 채점. 이게 돌아야 CaseMemory가 비지 않는다.
                ("feature_store", "evaluate_decisions"),
                # 사건 추출은 되살릴 수 있는 로컬 원문에서 나오므로 맨 뒤다 —
                # 여기서 실패해도 그날의 PIT 관측값은 이미 적재돼 있다.
                ("feature_store", "build_events"),
                ("investment_analysis", "analysis"),
                # 판단 직후에 보고서를 보낸다. 실패해도 분석 결과를 가리지 않는다.
                ("investment_analysis", "notify_investment"),
                ("toss_reconciliation", "reconcile"),
            ])
            self.assertEqual(
                scheduler.state.jobs["investment_pipeline"].pause_reason,
                "analysis_only_mode",
            )
            scheduler.tick(now=start + timedelta(seconds=61))
            self.assertEqual(calls, [
                ("account_risk_snapshot", "capture"),
                ("earnings_watch", "watch"),
                ("feature_store", "build_valuations"),
                ("feature_store", "build_features"),
                ("feature_store", "build_labels"),
                ("feature_store", "build_training_samples"),
                # 과거 판단 채점. 이게 돌아야 CaseMemory가 비지 않는다.
                ("feature_store", "evaluate_decisions"),
                # 사건 추출은 되살릴 수 있는 로컬 원문에서 나오므로 맨 뒤다 —
                # 여기서 실패해도 그날의 PIT 관측값은 이미 적재돼 있다.
                ("feature_store", "build_events"),
                ("investment_analysis", "analysis"),
                ("investment_analysis", "notify_investment"),
                ("toss_reconciliation", "reconcile"),
                # 정확 시각 대상은 1분 안에 다시 확인해야 한다.
                ("earnings_watch", "watch"),
                ("investment_analysis", "analysis"),
                ("investment_analysis", "notify_investment"),
                ("toss_reconciliation", "reconcile"),
                # feature_store는 하루 주기라 같은 날 두 번 돌지 않는다.
            ])


if __name__ == "__main__":
    unittest.main()


class HarnessModuleAllowlistTest(unittest.TestCase):
    """등록만 하고 allowlist에 안 넣으면 런타임에서야 드러난다."""

    def test_every_stage_module_is_allowed(self):
        import re
        from pathlib import Path
        from investment_agent.operations.harness_adapters import _MODULES

        source = (
            Path(__file__).resolve().parents[4]
            / "src"
            / "investment_agent"
            / "operations"
            / "harness_adapters.py"
        ).read_text(encoding="utf-8")
        called = set(re.findall(r'PythonModuleCommand\(\s*\n\s*"([\w.]+)"', source))
        self.assertTrue(called, "PythonModuleCommand 호출을 하나도 못 찾았다")
        self.assertEqual(sorted(called - _MODULES), [])

    def test_every_allowed_module_is_runnable(self):
        """allowlist에 실행할 수 없는 이름이 들어가면 그 단계는 런타임에야 죽는다.

        `python -m X`가 성립하는 경우는 둘이다 — 모듈이 main을 갖거나,
        패키지가 __main__을 갖는 경우다.
        """
        import importlib
        import importlib.util
        from investment_agent.operations.harness_adapters import _MODULES

        for module in sorted(_MODULES):
            with self.subTest(module=module):
                imported = importlib.import_module(module)
                runnable = hasattr(imported, "main") or (
                    hasattr(imported, "__path__")
                    and importlib.util.find_spec(f"{module}.__main__") is not None
                )
                self.assertTrue(runnable)
