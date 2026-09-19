"""Trading reader cache·원장·Research artifact 저장소의 소유권을 고정한다."""
from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path


PACKAGE = Path(__file__).parents[3] / "src" / "investment_agent"
RESEARCH_WRITE_METHODS = frozenset({
    "save_rl_feature_snapshots",
    "save_rl_training_labels",
    "save_valuation_observations",
})


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

    def test_feature_and_label_write_calls_stay_in_research_owner(self) -> None:
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

    def test_feature_and_label_write_guard_rejects_a_trading_caller(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
