"""Research와 Trading이 같은 예측 기간 계약을 소비하는지 검증한다."""
from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from investment_agent.forecasting import SIGNAL_HORIZON_DAYS

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "investment_agent"


def _signal_horizon_definitions(root: Path) -> list[str]:
    definitions: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            targets = node.targets if isinstance(node, ast.Assign) else ()
            if any(isinstance(target, ast.Name) and target.id == "SIGNAL_HORIZON_DAYS" for target in targets):
                definitions.append(path.relative_to(root).as_posix())
    return sorted(definitions)


class ForecastingContractTest(unittest.TestCase):
    def test_signal_horizon_is_one_shared_trading_day_contract(self):
        self.assertEqual(20, SIGNAL_HORIZON_DAYS)

    def test_signal_horizon_has_one_canonical_definition(self):
        self.assertEqual(["forecasting.py"], _signal_horizon_definitions(PACKAGE))

    def test_definition_guard_detects_a_duplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "forecasting.py").write_text("SIGNAL_HORIZON_DAYS = 20\n", encoding="utf-8")
            (root / "duplicate.py").write_text("SIGNAL_HORIZON_DAYS = 5\n", encoding="utf-8")

            self.assertEqual(
                ["duplicate.py", "forecasting.py"],
                _signal_horizon_definitions(root),
            )


if __name__ == "__main__":
    unittest.main()
