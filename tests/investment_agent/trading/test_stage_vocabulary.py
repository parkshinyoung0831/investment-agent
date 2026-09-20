"""모델 수명주기 단계 목록은 원본 두 곳에만 있다.

Research(`research/promotion/gate.py`)와 Trading(`trading/run_context.py`)은 서로 import할 수 없어
각자 선언하고 정합 테스트로 묶는다. 그 밖의 파일이 같은 목록을 다시 적으면 조용히 갈라진다.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

PACKAGE = Path(__file__).parents[3] / "src" / "investment_agent"
STAGE_NAMES = frozenset({"shadow", "backtest", "out_of_sample", "walk_forward", "paper", "live"})
OWNERS = frozenset({"research/promotion/gate.py", "trading/run_context.py"})
MIN_STAGES_IN_A_LIST = 4


def _stage_lists(source: str) -> list[int]:
    """단계 이름을 4개 이상 담은 set·tuple·list 리터럴의 줄 번호."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
            names = {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            if len(names & STAGE_NAMES) >= MIN_STAGES_IN_A_LIST:
                lines.append(node.lineno)
    return lines


class StageVocabularyTest(unittest.TestCase):
    def test_stage_lists_are_declared_only_by_their_owners(self) -> None:
        offenders: list[str] = []
        owner_hits = 0
        for path in PACKAGE.rglob("*.py"):
            relative = path.relative_to(PACKAGE).as_posix()
            lines = _stage_lists(path.read_text(encoding="utf-8"))
            if relative in OWNERS:
                owner_hits += len(lines)
            else:
                offenders.extend(f"{relative}:{line}" for line in lines)
        self.assertGreaterEqual(owner_hits, 2, "단계 목록 원본이 사라져 가드가 공허해졌다")
        self.assertEqual([], offenders)

    def test_detector_finds_a_copied_list(self) -> None:
        self.assertEqual([1], _stage_lists('X = {"shadow", "backtest", "out_of_sample", "walk_forward", "paper", "live"}'))
        self.assertEqual([], _stage_lists('X = ("paper", "live")'))


if __name__ == "__main__":
    unittest.main()
