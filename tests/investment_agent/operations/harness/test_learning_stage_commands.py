"""학습 원장 단계가 실행 가능한 명령 계약을 유지하는지 검증한다.

각 단계는 allowlist에 있는 모듈 하나를 호출하고, 문자열 인자 튜플과 유한한 양수
timeout을 사용해야 한다.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from threading import Event

from investment_agent.operations.harness.commands import CommandResult, PythonModuleCommand
from investment_agent.operations.harness.contracts import StageContext
from investment_agent.operations.harness_adapters import _MODULES, ProductionInvestmentAdapters

UTC = timezone.utc
NOW = datetime(2026, 9, 4, 3, 0, tzinfo=UTC)

# 학습 원장 job(`feature_store`)이 순서대로 부르는 단계와, 각 단계가 불러야 할 모듈.
LEARNING_STAGES = (
    ("build_valuations", "investment_agent.research.commands.build_valuations"),
    ("build_features", "investment_agent.research.commands.build_features"),
    ("build_labels", "investment_agent.research.commands.build_labels"),
    ("build_training_samples", "investment_agent.research.commands.build_training_samples"),
    ("evaluate_decisions", "investment_agent.operations.commands.evaluate_decisions"),
    ("diagnose_system", "investment_agent.operations.commands.system_diagnosis"),
    ("evaluate_system", "investment_agent.operations.commands.system_evaluations"),
    ("build_events", "investment_agent.research.commands.build_events"),
    ("build_decision_experiences", "investment_agent.operations.commands.build_decision_experiences"),
    ("update_performance", "investment_agent.operations.commands.update_performance"),
)


class RecordingRunner:
    def __init__(self) -> None:
        self.commands: list[PythonModuleCommand] = []

    def run(self, command, *, stop_event):
        self.commands.append(command)
        return CommandResult(command.module, 0, 0.1)


def _context(stage_id: str) -> StageContext:
    return StageContext(
        job_id="feature_store",
        run_id="run_learning",
        stage_id=stage_id,
        attempt=1,
        idempotency_key="key",
        now=NOW,
        stop_event=Event(),
        prior_metadata={},
        completed_metadata={},
    )


class LearningStageCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = RecordingRunner()
        self.adapters = ProductionInvestmentAdapters(
            command_runner=self.runner,
            decision_repository=None,
            approval_repository=None,
            system_store=None,
            follow_target=lambda **kwargs: None,
            create_execution_intent=lambda **kwargs: None,
            now=lambda: NOW,
        )

    def test_each_stage_issues_exactly_one_allowlisted_command(self):
        for stage_id, module in LEARNING_STAGES:
            with self.subTest(stage=stage_id):
                self.runner.commands.clear()
                outcome = getattr(self.adapters, stage_id)(_context(stage_id))

                self.assertEqual(outcome.status, "succeeded")
                self.assertEqual(len(self.runner.commands), 1)
                command = self.runner.commands[0]
                self.assertIsInstance(command, PythonModuleCommand)
                self.assertEqual(command.module, module)
                self.assertIn(command.module, _MODULES)
                self.assertTrue(all(isinstance(arg, str) for arg in command.arguments))
                self.assertGreater(command.timeout_seconds, 0)

    def test_stages_that_need_a_reference_time_pass_the_stage_clock(self):
        """`--as-of`는 context.now여야 한다 — 벽시계를 쓰면 재시도가 다른 날을 본다."""
        for stage_id, _ in LEARNING_STAGES:
            with self.subTest(stage=stage_id):
                self.runner.commands.clear()
                getattr(self.adapters, stage_id)(_context(stage_id))
                arguments = self.runner.commands[0].arguments
                if "--as-of" in arguments:
                    self.assertEqual(
                        arguments[arguments.index("--as-of") + 1],
                        NOW.isoformat(),
                    )

    def test_production_feature_store_scores_system_stages_after_decisions(self):
        """가짜 adapters에는 이 stage가 없어도 된다 — 실제 운영 adapters로 등록되는지를 본다."""
        from investment_agent.operations.commands.investment_harness import build_registry

        definitions = {definition.job_id: definition for definition in build_registry(adapters=self.adapters).definitions()}
        stages = [stage.stage_id for stage in definitions["feature_store"].stages]
        self.assertEqual(stages.index("evaluate_decisions") + 1, stages.index("diagnose_system"))

    def test_production_harness_produces_promotion_evidence_weekly(self):
        """승격 게이트가 읽는 증거를 만드는 job이 운영 adapters로 등록된다 — 없으면 실계좌 추종이 영구히 막힌다."""
        from investment_agent.operations.commands.investment_harness import build_registry

        definitions = {definition.job_id: definition for definition in build_registry(adapters=self.adapters).definitions()}
        self.assertEqual(7 * 24 * 60 * 60, definitions["system_evaluation"].interval_seconds)

    def test_unready_learning_is_not_reported_as_trained(self):
        import json
        from pathlib import Path
        def run(command, *, stop_event):
            path = Path(command.arguments[command.arguments.index('--result-path') + 1])
            path.write_text(json.dumps({'status':'pending','reason':'not enough independent periods'}))
        self.runner.run = run
        outcome = self.adapters.continuous_learning(_context('continuous_learning'))
        self.assertEqual(outcome.status, 'skipped')
        self.assertEqual(outcome.metadata['status'], 'pending')


if __name__ == "__main__":
    unittest.main()
