"""화면이 계산 facade에서 가져오는 공개 이름과 일정 계약을 검증한다.

페이지 모듈은 import만으로 Streamlit·DB를 초기화할 수 있으므로, 파일을 직접
실행하지 않고 import 문과 순수 일정 함수를 오프라인에서 확인한다.
"""
from __future__ import annotations

import ast
import unittest
from datetime import date
from pathlib import Path

from investment_agent.dashboard import calculations
from investment_agent.dashboard.calculations import (
    DEFAULT_SCHEDULE_HORIZON,
    SCHEDULE_HORIZONS,
    schedule_window,
)

DASHBOARD = Path(__file__).resolve().parents[3] / "src" / "investment_agent" / "dashboard"
FACADE = "investment_agent.dashboard.calculations"


class CalculationsFacadeTest(unittest.TestCase):
    def test_every_name_imported_from_the_facade_exists(self) -> None:
        missing: list[str] = []
        for path in sorted(DASHBOARD.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.module != FACADE:
                    continue
                for alias in node.names:
                    if alias.name != "*" and not hasattr(calculations, alias.name):
                        missing.append(f"{path.relative_to(DASHBOARD.parent.parent)} -> {alias.name}")
        self.assertEqual([], sorted(missing), "계산 Facade가 내보내지 않는 이름을 화면이 가져옵니다")

    def test_schedule_window_resolves_every_horizon(self) -> None:
        today = date(2026, 8, 27)  # 목요일
        for horizon in SCHEDULE_HORIZONS:
            start, end, _group = schedule_window(horizon, today)
            self.assertLessEqual(start, end, horizon)

        # Discord 규칙 선택지는 Reporting의 주간 창(월–일)을 그대로 쓴다.
        self.assertEqual(
            (date(2026, 8, 24), date(2026, 8, 30), False),
            schedule_window("이번 주 (Discord 규칙)", today),
        )
        # 모르는 라벨은 예외 대신 기본 창으로 되돌린다.
        self.assertEqual(
            schedule_window(DEFAULT_SCHEDULE_HORIZON, today),
            schedule_window("존재하지 않는 지평", today),
        )
