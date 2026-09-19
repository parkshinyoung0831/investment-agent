"""Trading reader cache·원장·Research artifact 저장소의 소유권을 고정한다."""
from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path


PACKAGE = Path(__file__).parents[3] / "src" / "investment_agent"
RESEARCH_WRITE_METHODS = frozenset({
    "save_event_features",
    "save_events",
    "save_decision_experiences",
    "save_rl_feature_snapshots",
    "save_rl_training_labels",
    "save_training_sample_runs",
    "save_training_samples",
    "save_valuation_observations",
})
RESEARCH_READ_METHODS = frozenset({
    "decision_experience_rows",
    "rl_feature_snapshot_rows",
    "rl_training_label_rows",
    "training_sample_period_inputs",
})
RESEARCH_READ_CONSUMERS = frozenset({"operations", "reporting"})


def _research_write_violations(relative_path: Path, source: str) -> list[tuple[int, str]]:
    """Research 산출물 write가 owner 밖에서 호출된 위치를 반환한다."""
    calls = [
        (node.lineno, node.func.attr)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in RESEARCH_WRITE_METHODS
    ]
    if relative_path.parts and relative_path.parts[0] == "research":
        return []
    return calls


def _research_read_violations(relative_path: Path, source: str) -> list[tuple[int, str]]:
    """Research artifact read의 owner 밖 정의·호출을 반환한다."""
    owner = relative_path.parts[0] if relative_path.parts else ""
    if owner == "research":
        return []
    violations: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name in RESEARCH_READ_METHODS:
            violations.append((node.lineno, node.name))
        elif (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in RESEARCH_READ_METHODS
            and not (
                node.func.attr == "decision_experience_rows"
                and owner in RESEARCH_READ_CONSUMERS
            )
        ):
            violations.append((node.lineno, node.func.attr))
    return violations


class RepositoryOwnershipTest(unittest.TestCase):
    def test_point_in_time_cache_is_not_kept_on_the_compatibility_facade(self) -> None:
        from investment_agent.trading.supabase_repository import (
            PointInTimeReaderCache,
            SupabaseRepository,
        )

        self.assertIn("_memo_state", inspect.getsource(PointInTimeReaderCache))
        self.assertNotIn("_memo_state", inspect.getsource(SupabaseRepository._memo))

    def test_research_store_owns_recalculable_artifact_writes(self) -> None:
        from investment_agent.research.storage.repository import ResearchStore

        self.assertTrue({
            "save_events",
            "save_event_features",
            "save_training_samples",
            "save_training_sample_runs",
            "save_rl_feature_snapshots",
            "save_rl_training_labels",
            "save_valuation_observations",
            "save_decision_experiences",
            "model_evaluation_rows",
            "model_evaluation_summary",
            "save_promotion",
            "approve_model_promotion",
        } <= set(dir(ResearchStore)))

    def test_research_artifact_write_calls_stay_in_research_owner(self) -> None:
        violations: list[str] = []
        owner_calls = 0
        for path in PACKAGE.rglob("*.py"):
            relative = path.relative_to(PACKAGE)
            source = path.read_text(encoding="utf-8")
            calls = _research_write_violations(relative, source)
            if relative.parts and relative.parts[0] == "research":
                owner_calls += sum(
                    1
                    for node in ast.walk(ast.parse(source))
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in RESEARCH_WRITE_METHODS
                )
            violations.extend(f"{relative.as_posix()}:{line}:{method}" for line, method in calls)
        self.assertGreater(owner_calls, 0, "Research write ownership guard has no live subject")
        self.assertEqual(violations, [])

    def test_research_artifact_write_guard_rejects_a_trading_caller(self) -> None:
        source = "def leak(repository):\n    repository.save_rl_feature_snapshots([])\n"
        self.assertEqual(
            _research_write_violations(Path("trading/injected.py"), source),
            [(2, "save_rl_feature_snapshots")],
        )
        self.assertEqual(
            _research_write_violations(Path("research/commands/injected.py"), source),
            [],
        )
        valuation_source = (
            "def leak(repository):\n    repository.save_valuation_observations([])\n"
        )
        self.assertEqual(
            _research_write_violations(Path("trading/injected.py"), valuation_source),
            [(2, "save_valuation_observations")],
        )
        event_source = (
            "def leak(repository):\n"
            "    repository.save_events([])\n"
            "    repository.save_event_features([])\n"
        )
        self.assertEqual(
            _research_write_violations(Path("trading/injected.py"), event_source),
            [(2, "save_events"), (3, "save_event_features")],
        )
        experience_source = (
            "def leak(repository):\n    repository.save_decision_experiences([])\n"
        )
        self.assertEqual(
            _research_write_violations(Path("trading/injected.py"), experience_source),
            [(2, "save_decision_experiences")],
        )
        sample_source = (
            "def leak(repository):\n"
            "    repository.save_training_samples([])\n"
            "    repository.save_training_sample_runs([])\n"
        )
        self.assertEqual(
            _research_write_violations(Path("trading/injected.py"), sample_source),
            [(2, "save_training_samples"), (3, "save_training_sample_runs")],
        )

    def test_research_artifact_reads_stay_in_research_owner(self) -> None:
        from investment_agent.research.storage.repository import ResearchStore

        self.assertTrue(RESEARCH_READ_METHODS <= set(dir(ResearchStore)))
        violations = [
            f"{path.relative_to(PACKAGE).as_posix()}:{line}:{method}"
            for path in PACKAGE.rglob("*.py")
            for line, method in _research_read_violations(
                path.relative_to(PACKAGE), path.read_text(encoding="utf-8")
            )
        ]
        self.assertEqual(violations, [])

    def test_training_metadata_read_guard_rejects_trading_definition_and_caller(self) -> None:
        source = (
            "def training_sample_period_inputs(self):\n    pass\n"
            "def leak(reader):\n    reader.training_sample_period_inputs()\n"
        )
        self.assertEqual(
            _research_read_violations(Path("trading/injected.py"), source),
            [(1, "training_sample_period_inputs"), (4, "training_sample_period_inputs")],
        )

    def test_full_read_guard_rejects_trading_definitions_and_callers(self) -> None:
        source = (
            "def rl_feature_snapshot_rows(self):\n    pass\n"
            "def leak(reader):\n"
            "    reader.rl_training_label_rows()\n"
            "    reader.decision_experience_rows()\n"
        )
        self.assertEqual(
            _research_read_violations(Path("trading/injected.py"), source),
            [(1, "rl_feature_snapshot_rows"), (4, "rl_training_label_rows"),
             (5, "decision_experience_rows")],
        )


if __name__ == "__main__":
    unittest.main()
