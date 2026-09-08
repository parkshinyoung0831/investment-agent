"""홈 화면이 부르는 매크로 지표 스트립 계산.

실측 2026-09-04: 홈 페이지가 NameError로 통째로 죽었다 — macro.py가
MACRO_SPARK_POINTS를 쓰면서 import하지 않았다. 대시보드 첫 화면이 안 뜬다.
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from investment_agent.dashboard.calculations.macro import macro_indicator_rows
from investment_agent.dashboard.calculations.schedule import MACRO_SPARK_POINTS


def _window(points: int = 60):
    start = date(2026, 1, 1)
    return [
        {
            "series_id": "VIX",
            "name_ko": "변동성지수",
            "category": "risk",
            "unit": "index",
            "series_kind": "level",
            "frequency": "daily",
            "obs_date": (start + timedelta(days=i)).isoformat(),
            "value": 15.0 + (i % 7),
        }
        for i in range(points)
    ]


class MacroIndicatorRowsTest(unittest.TestCase):
    def test_it_returns_rows_instead_of_raising(self):
        rows = macro_indicator_rows(_window())

        self.assertTrue(rows)
        self.assertEqual(rows[0]["series_id"], "VIX")

    def test_spark_is_capped_at_the_declared_point_count(self):
        rows = macro_indicator_rows(_window(points=200))

        self.assertLessEqual(len(rows[0]["spark"]), MACRO_SPARK_POINTS)

    def test_a_short_history_is_not_padded(self):
        rows = macro_indicator_rows(_window(points=5))

        self.assertLessEqual(len(rows[0]["spark"]), 5)


if __name__ == "__main__":
    unittest.main()
