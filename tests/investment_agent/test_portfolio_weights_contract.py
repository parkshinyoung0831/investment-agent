"""Research와 Trading이 같은 long-only 비중 벡터 계약을 소비하는지 검증한다."""
from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from investment_agent.platform.serialization import ContractError
from investment_agent.portfolio_weights import CASH_SYMBOL, TICKER_RE, validated_weights

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "investment_agent"
OWNED_NAMES = frozenset({"CASH_SYMBOL", "validated_weights"})


def _definitions(root: Path) -> list[str]:
    """`root` 아래에서 비중 계약 이름을 새로 정의하는 모듈을 `상대경로:이름`으로 모은다."""
    definitions: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Assign):
                names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            elif isinstance(node, ast.FunctionDef):
                names = [node.name]
            definitions.extend(f"{path.relative_to(root).as_posix()}:{name}" for name in names if name in OWNED_NAMES)
    return sorted(definitions)


class PortfolioWeightsContractTest(unittest.TestCase):
    def test_weights_are_validated_sorted_and_carry_cash(self) -> None:
        result = validated_weights({"msft": 0.25, "AAPL": 0.25, "CASH": 0.5})
        self.assertEqual({"AAPL": 0.25, "CASH": 0.5, "MSFT": 0.25}, result)
        self.assertEqual(sorted(result), list(result))

    def test_cash_is_added_when_missing_and_total_is_not_required(self) -> None:
        self.assertEqual({"AAPL": 0.1, CASH_SYMBOL: 0.0}, validated_weights({"AAPL": 0.1}, require_total=False))

    def test_invalid_weights_are_rejected_not_coerced(self) -> None:
        for bad in ({}, {"AAPL": True}, {"AAPL": -0.1, "CASH": 1.1}, {"aapl": 0.5, "AAPL": 0.5}, {"1BAD": 1.0}):
            with self.subTest(weights=bad), self.assertRaises(ContractError):
                validated_weights(bad)

    def test_total_must_be_one_including_cash(self) -> None:
        with self.assertRaises(ContractError):
            validated_weights({"AAPL": 0.1})

    def test_ticker_pattern_is_the_one_used_for_symbols(self) -> None:
        self.assertTrue(TICKER_RE.fullmatch("BRK.B"))
        self.assertFalse(TICKER_RE.fullmatch("CASH_"))


class PortfolioWeightsOwnershipTest(unittest.TestCase):
    def test_canonical_module_owns_both_names(self) -> None:
        owned = [item for item in _definitions(PACKAGE) if item.startswith("portfolio_weights.py:")]
        self.assertEqual(["portfolio_weights.py:CASH_SYMBOL", "portfolio_weights.py:validated_weights"], owned)

    def test_trading_and_research_do_not_redefine_the_contract(self) -> None:
        offenders = _definitions(PACKAGE / "trading") + _definitions(PACKAGE / "research")
        self.assertEqual([], offenders)

    def test_definition_guard_detects_a_redefinition(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "copy.py").write_text('CASH_SYMBOL = "CASH"\n\ndef validated_weights(weights):\n    return weights\n', encoding="utf-8")
            self.assertEqual(["copy.py:CASH_SYMBOL", "copy.py:validated_weights"], _definitions(root))


if __name__ == "__main__":
    unittest.main()
