"""LLM을 부르는 모듈은 실행 범위에 들어가지 않는다. broker 비밀은 주문·대사·계좌 조회 모듈에만 간다."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from investment_agent.operations.harness_adapters import EXECUTION_MODULES, _MODULES

ROOT = Path(__file__).resolve().parents[4] / "src"
# 이 이름을 import하는 모듈은 LLM 판단을 부른다.
LLM_MARKERS = ("trading.decision.llm", "trading.decision.analysis", "OpenAICompatibleClient")


class SecretScopedModulesTest(unittest.TestCase):
    def test_execution_modules_never_import_llm_decision_code(self):
        self.assertTrue(EXECUTION_MODULES <= _MODULES)
        for module in sorted(EXECUTION_MODULES):
            source = (ROOT / (module.replace(".", "/") + ".py")).read_text(encoding="utf-8")
            imports = " ".join(
                (getattr(node, "module", None) or "") + " " + " ".join(alias.name for alias in node.names)
                for node in ast.walk(ast.parse(source)) if isinstance(node, (ast.Import, ast.ImportFrom))
            )
            for marker in LLM_MARKERS:
                self.assertNotIn(marker, imports, module)

    def test_llm_modules_stay_in_the_analysis_scope(self):
        for module in ("investment_agent.trading.decision.analysis",
                       "investment_agent.operations.commands.system_portfolio",
                       "investment_agent.operations.commands.event_reanalysis"):
            self.assertIn(module, _MODULES)
            self.assertNotIn(module, EXECUTION_MODULES)


if __name__ == "__main__":
    unittest.main()
