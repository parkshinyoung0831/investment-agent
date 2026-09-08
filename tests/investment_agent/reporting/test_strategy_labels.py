from __future__ import annotations

import unittest

from investment_agent.research.strategies.catalog import STRATEGY_CATALOG
from investment_agent.research.strategies.strategies import STRATEGY_IDS
from investment_agent.reporting.services import strategy_labels as labels


class StrategyLabelsTest(unittest.TestCase):
    """화면이 읽는 전략 표시 계약."""

    def test_strategy_ids_match_the_registered_compute_functions(self) -> None:
        # 화면이 이 순서를 그대로 나열하므로 순서까지 같아야 한다.
        self.assertEqual(STRATEGY_IDS, labels.strategy_ids())

    def test_label_exposes_display_names_only(self) -> None:
        label = labels.strategy_label("gem")
        assert label is not None
        self.assertEqual("gem", label.strategy_id)
        self.assertEqual(STRATEGY_CATALOG["gem"].notify_name, label.name)
        self.assertEqual(STRATEGY_CATALOG["gem"].notify_description, label.description)
        # 저장 계층 이름은 계약에 없다 — 화면이 DB 표기를 알 이유가 없다.
        self.assertFalse(hasattr(label, "db_name"))

    def test_unknown_ids_are_not_invented(self) -> None:
        self.assertIsNone(labels.strategy_label("nope"))
        self.assertIsNone(labels.strategy_label(None))

    def test_mode_label_keeps_unknown_text_and_marks_the_empty_case(self) -> None:
        self.assertEqual("🛡 방어 · 안전자산 도피", labels.mode_label("Risk-Off"))
        self.assertEqual("🛡 방어 · 안전자산 도피", labels.mode_label("  Risk-Off  "))
        self.assertEqual("Unmapped mode", labels.mode_label("Unmapped mode"))
        self.assertEqual("—", labels.mode_label(None))
        self.assertEqual("—", labels.mode_label(""))

    def test_ticker_label_returns_none_for_unknown_symbols(self) -> None:
        self.assertEqual("미국 대형주", labels.ticker_label("SPY"))
        self.assertIsNone(labels.ticker_label("ZZZ"))
        self.assertIsNone(labels.ticker_label(None))
