"""의사 종목 "CASH"의 이름은 한 곳(`portfolio_weights.CASH_SYMBOL`)이 소유한다.

실측(2026-09): 같은 문자열이 선언 4곳·리터럴 26곳에 흩어져 있었다. 어느 한 곳이 철자를 바꾸거나 소문자로
정규화하면 목표 비중의 현금 칸이 "종목"으로 읽히거나 사라지는데, 예외 없이 조용히 어긋난다.

`execution`은 일부러 자기 사본(`execution/orders/intents.py`)을 갖는다 — 주문 경계가 Trading 검증 변경에
딸려 가지 않게 하려는 안전 계약이다(CLAUDE.md "일부러 다르게 둔 모양"). 대신 두 값이 같은지를 여기서 고정한다.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from investment_agent import portfolio_weights
from investment_agent.execution.orders import intents

SRC = Path(__file__).resolve().parents[2] / "src"
CASH_LITERAL = "CASH"
# 이름의 원본 두 곳. 나머지는 모두 portfolio_weights에서 가져와야 한다.
OWNERS = frozenset({
    "investment_agent/portfolio_weights.py",
    "investment_agent/execution/orders/intents.py",
})


def _literal_sites() -> dict[str, list[int]]:
    sites: dict[str, list[int]] = {}
    for path in sorted((SRC / "investment_agent").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        lines = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and node.value == CASH_LITERAL
            and id(node) not in docstrings
        ]
        if lines:
            sites[path.relative_to(SRC).as_posix()] = lines
    return sites


class CashSymbolSingleOwnerTest(unittest.TestCase):
    def test_the_execution_copy_agrees_with_the_shared_one(self):
        self.assertEqual(intents.CASH_SYMBOL, portfolio_weights.CASH_SYMBOL)

    def test_the_scan_finds_the_two_owners(self):
        """스캔이 원본을 못 찾으면 아래 검사는 공허하게 통과한다."""
        self.assertLessEqual(OWNERS, set(_literal_sites()))

    def test_no_other_module_spells_the_literal(self):
        strays = {path: lines for path, lines in _literal_sites().items() if path not in OWNERS}
        self.assertEqual({}, strays)


if __name__ == "__main__":
    unittest.main()
