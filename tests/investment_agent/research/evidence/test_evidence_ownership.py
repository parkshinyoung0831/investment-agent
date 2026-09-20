"""PIT 증거 계약·조립기·통계는 Research가 소유하고 Trading은 공개 계약으로만 소비한다."""
from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[4] / "src" / "investment_agent"
OWNED_CLASSES = frozenset({"EvidenceItem", "EvidenceBundle", "ContextBuilder"})


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

    def test_definition_guard_detects_a_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "copy.py").write_text("class EvidenceBundle:\n    pass\n", encoding="utf-8")
            self.assertEqual(["copy.py:EvidenceBundle"], _class_definitions(root))


if __name__ == "__main__":
    unittest.main()
