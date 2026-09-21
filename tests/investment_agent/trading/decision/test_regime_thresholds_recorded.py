"""regime의 모든 경계값이 기록되는 thresholds·version에 실린다(HC-2). 인라인 숫자는 원장에서 재현할 수 없다."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from investment_agent.trading.decision.regime import DEFAULT_THRESHOLDS, RegimeThresholds, build_market_regime

AS_OF = "2026-09-21T21:00:00+00:00"
SOURCE = Path(__file__).resolve().parents[4] / "src" / "investment_agent" / "trading" / "decision" / "regime.py"


class RegimeThresholdsTest(unittest.TestCase):
    def test_liquidity_and_macro_boundaries_are_read_from_the_thresholds(self) -> None:
        strict = RegimeThresholds(liquidity_stressed=0.30, macro_supportive=0.50, macro_adverse=-0.50)
        # 기본 경계(0.20·0.25)에서는 각각 thin·supportive인 값이 엄격한 경계에서는 stressed·neutral이다.
        default = build_market_regime(AS_OF, liquidity=0.25, macro_score=0.30)
        custom = build_market_regime(AS_OF, liquidity=0.25, macro_score=0.30, thresholds=strict)
        self.assertEqual((default.liquidity_state, default.macro_state), ("thin", "supportive"))
        self.assertEqual((custom.liquidity_state, custom.macro_state), ("stressed", "neutral"))

    def test_the_recorded_thresholds_carry_every_boundary(self) -> None:
        recorded = build_market_regime(AS_OF, liquidity=0.5).metadata["thresholds"]
        for name in ("liquidity_stressed", "liquidity_thin", "liquidity_deep", "macro_supportive", "macro_adverse"):
            self.assertIn(name, recorded)
        self.assertEqual(recorded, DEFAULT_THRESHOLDS.to_dict())

    def test_no_numeric_boundary_is_written_inline_in_the_comparisons(self) -> None:
        """비교식에 숫자 리터럴이 있으면 그 경계는 기록되지 않는다(0과 ±1 범위 절단은 경계가 아니다)."""
        allowed = {0, 0.0, 1, 1.0, -1.0, 0.35, 0.65}
        offenders = []
        for node in ast.walk(ast.parse(SOURCE.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Compare):
                for operand in [node.left, *node.comparators]:
                    if isinstance(operand, ast.Constant) and isinstance(operand.value, float) and operand.value not in allowed:
                        offenders.append((node.lineno, operand.value))
        self.assertEqual([], offenders)

    def test_invalid_ordering_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RegimeThresholds(liquidity_thin=0.10)
        with self.assertRaises(ValueError):
            RegimeThresholds(macro_adverse=0.1)


if __name__ == "__main__":
    unittest.main()
