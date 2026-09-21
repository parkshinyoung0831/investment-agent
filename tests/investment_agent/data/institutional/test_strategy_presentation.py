"""매니저 성향·설명의 owner는 `strategy_group` catalog 하나다.

전에는 13F 화면이 매니저 이름 부분문자열 14쌍으로 같은 것을 다시 골랐다. 거장을 한 명
추가하면 성향·설명이 조용히 비고, 한글 needle 7개는 카탈로그 표기("세스 클라먼")와 달라
죽어 있었고, 같은 성씨가 둘이면 오매칭이었다(감사 AU-03).
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from investment_agent.data.institutional.domain.managers import (
    MANAGER_PRESENTATION,
    STRATEGY_GROUP_PRESENTATION,
    active_managers,
    presentation_for,
)


class StrategyPresentationTest(unittest.TestCase):
    def test_every_tracked_manager_resolves_a_label_and_summary(self):
        rows = active_managers()
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(cik=row["manager_cik"]):
                self.assertTrue(str(row.get("strategy_label") or "").strip())
                self.assertTrue(str(row.get("strategy_summary") or "").strip())

    def test_every_declared_strategy_group_has_a_presentation(self):
        """카탈로그에 새 group을 넣고 라벨을 잊으면 화면이 조용히 빈다."""
        declared = {
            str(row.get("strategy_group") or "") for row in MANAGER_PRESENTATION.values()
        }
        self.assertEqual(declared - set(STRATEGY_GROUP_PRESENTATION), set())

    def test_an_unknown_group_leaves_the_fields_absent_instead_of_guessing(self):
        row = presentation_for("0000000000")
        self.assertNotIn("strategy_label", row)

    def test_the_dashboard_no_longer_matches_manager_names(self):
        source = Path("src/investment_agent/dashboard/app_pages/gurus.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        needles = {
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        for forbidden in ("버핏", "klarman", "클라만", "druckenmiller", "ackman"):
            self.assertNotIn(forbidden, needles, "성향을 이름으로 다시 고르고 있다")


if __name__ == "__main__":
    unittest.main()
