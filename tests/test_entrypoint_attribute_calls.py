"""진입점이 import한 클래스에 없는 속성을 부르면 실행 시점에야 죽는다.

실주문 CLI가 존재하지 않는 `LiveTradingControls.from_env()`를 부르던 결함은 worker 단위
테스트를 모두 통과했다. 진입점은 대개 단위 테스트가 없어서, 여기서 정적으로 막는다.
"""
from __future__ import annotations

import ast
import importlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "investment_agent"
# 실주문·승인·대사·하네스 조립처럼 단위 테스트가 닿지 않는 조립 코드가 모이는 곳이다.
SCANNED = ("operations/commands", "operations/harness", "execution")


def missing_class_attributes(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("investment_agent"):
            for alias in node.names:
                imported[alias.asname or alias.name] = (node.module, alias.name)
    problems = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)):
            continue
        target = imported.get(node.value.id)
        if target is None:
            continue
        try:
            obj = getattr(importlib.import_module(target[0]), target[1])
        except (ImportError, AttributeError):
            continue
        if isinstance(obj, type) and not hasattr(obj, node.attr):
            problems.append(f"{path.relative_to(ROOT)}:{node.lineno} {node.value.id}.{node.attr}")
    return problems


class EntrypointAttributeCallTest(unittest.TestCase):
    def test_scanned_directories_exist(self):
        # 대상 폴더가 옮겨지면 이 가드는 아무것도 검사하지 않고 통과한다.
        for relative in SCANNED:
            self.assertTrue(any((ROOT / relative).rglob("*.py")), relative)

    def test_detector_flags_a_missing_classmethod(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            probe = Path(directory) / "probe.py"
            probe.write_text(
                "from investment_agent.execution.safety.control import LiveTradingControls\n"
                "LiveTradingControls.from_env()\n",
                encoding="utf-8",
            )
            self.assertEqual(len(missing_class_attributes(probe)), 1)

    def test_entrypoints_only_call_attributes_that_exist(self):
        problems = []
        for relative in SCANNED:
            for path in sorted((ROOT / relative).rglob("*.py")):
                problems.extend(missing_class_attributes(path))
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
