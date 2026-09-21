"""PIT 증거 계약·조립기·통계는 Research가 소유하고 Trading은 공개 계약으로만 소비한다."""
from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[4] / "src" / "investment_agent"
OWNED_CLASSES = frozenset({"EvidenceItem", "EvidenceBundle", "ContextBuilder", "PitReader", "PointInTimeReaderCache"})

# PIT 읽기 조립은 Research reader가 소유한다. Trading 저장소는 이것을 상속만 하고 다시 구현하지 않는다.
PIT_READ_METHODS = frozenset({
    "market_prices", "fundamentals", "fundamentals_pit", "estimates", "macro_snapshot", "macro_histories",
    "segment_snapshot", "guru_snapshot", "econ_snapshot", "technical_snapshot", "current_tracked_tickers",
    "historical_sp500_membership", "sp500_sector_map", "prepare_historical_replay", "prepare_valuation_inputs", "share_class_snapshots_pit",
    "valuation_observation_rows", "label_price_rows", "forward_prices_for_labels", "rl_historical_membership_rows",
})


def _class_definitions(root: Path) -> list[str]:
    found: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found.extend(
            f"{path.relative_to(root).as_posix()}:{node.name}"
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name in OWNED_CLASSES
        )
    return sorted(found)


class EvidenceOwnershipTest(unittest.TestCase):
    def test_contracts_and_builder_are_defined_only_in_research_evidence(self) -> None:
        self.assertEqual(
            [
                "research/evidence/context.py:ContextBuilder",
                "research/evidence/contracts.py:EvidenceBundle",
                "research/evidence/contracts.py:EvidenceItem",
                "research/evidence/reader.py:PitReader",
                "research/evidence/reader.py:PointInTimeReaderCache",
            ],
            _class_definitions(PACKAGE),
        )

    def test_the_old_trading_modules_are_gone(self) -> None:
        for name in ("context.py", "tools.py"):
            with self.subTest(module=name):
                self.assertFalse((PACKAGE / "trading" / "evidence" / name).exists())
        for name in ("context.py", "statistics.py", "contracts.py"):
            with self.subTest(module=name):
                self.assertTrue((PACKAGE / "research" / "evidence" / name).is_file())

    def test_trading_repository_inherits_the_pit_reads_instead_of_redefining_them(self) -> None:
        tree = ast.parse((PACKAGE / "trading" / "supabase_repository.py").read_text(encoding="utf-8"))
        repository = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SupabaseRepository")
        self.assertEqual(["PitReader", "CandidateSelection", "PromotionLedger"], [base.id for base in repository.bases if isinstance(base, ast.Name)])
        redefined = sorted(n.name for n in repository.body if isinstance(n, ast.FunctionDef) and n.name in PIT_READ_METHODS)
        self.assertEqual([], redefined)

    def test_research_evidence_never_imports_trading(self) -> None:
        offenders = []
        for path in (PACKAGE / "research" / "evidence").glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("investment_agent.trading"):
                    offenders.append(f"{path.name}:{node.module}")
        self.assertEqual([], offenders)

    def test_definition_guard_detects_a_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "copy.py").write_text("class EvidenceBundle:\n    pass\n", encoding="utf-8")
            self.assertEqual(["copy.py:EvidenceBundle"], _class_definitions(root))


if __name__ == "__main__":
    unittest.main()
