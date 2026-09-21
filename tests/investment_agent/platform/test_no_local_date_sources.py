"""'오늘'은 platform.clock 한 곳에서만 계산한다.

`date.today()`는 실행 환경의 로컬 날짜라 UTC 러너와 KST 로컬 하네스가 같은 시각에 다른 날을 말하고,
`datetime.now(ZoneInfo("Asia/Seoul"))`류를 파일마다 다시 쓰면 같은 규칙이 여러 벌로 갈라진다.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "investment_agent"
CLOCK = SRC / "platform" / "clock.py"
MARKET_ZONES = {"America/New_York", "Asia/Seoul"}


def _violations(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        func = node.func
        if func.attr == "today" and isinstance(func.value, ast.Name) and func.value.id == "date":
            found.append((node.lineno, "date.today()"))
        if func.attr == "now" and any(
            isinstance(argument, ast.Call)
            and isinstance(argument.func, ast.Name) and argument.func.id == "ZoneInfo"
            and argument.args and isinstance(argument.args[0], ast.Constant)
            and argument.args[0].value in MARKET_ZONES
            for argument in node.args
        ):
            found.append((node.lineno, "datetime.now(ZoneInfo(<시장 시간대>))"))
    return found


class NoLocalDateSourcesTest(unittest.TestCase):
    def test_sources_take_today_from_the_clock_module(self):
        offenders = []
        checked = 0
        for path in sorted(SRC.rglob("*.py")):
            if path == CLOCK:
                continue
            checked += 1
            for lineno, what in _violations(ast.parse(path.read_text(encoding="utf-8"))):
                offenders.append(f"{path.relative_to(SRC)}:{lineno} {what}")
        self.assertGreater(checked, 500, "검사 대상을 못 찾으면 가드가 공허하게 통과한다")
        self.assertEqual([], offenders, "platform.clock의 kst_today()/us_market_today()를 쓴다")

    def test_the_detector_sees_both_patterns(self):
        tree = ast.parse(
            "from datetime import date, datetime\n"
            "a = date.today()\n"
            "b = datetime.now(ZoneInfo('Asia/Seoul')).date()\n"
            "c = datetime.now(timezone.utc)\n"
        )
        self.assertEqual([2, 3], [lineno for lineno, _ in _violations(tree)])


if __name__ == "__main__":
    unittest.main()
