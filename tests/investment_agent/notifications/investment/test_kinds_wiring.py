"""`--kind`가 실제로 존재하는 러너를 가리키는지 검증한다.

배선이 어긋나면 import 에러가 아니라 실행 시점에야 드러난다 — 그때는 그날 카드가 안 나간 뒤다.
"""
from __future__ import annotations

import importlib
import unittest

from investment_agent.operations.commands.notify import KINDS

INVESTMENT_KINDS = {
    "investment_portfolio": "investment_agent.notifications.investment.run_portfolio:run",
    "investment_candidates": "investment_agent.notifications.investment.run_candidates:run",
    "investment_trades": "investment_agent.notifications.investment.run_trades:run",
}


class KindsWiringTest(unittest.TestCase):
    def test_investment_kinds_are_registered(self):
        for kind, target in INVESTMENT_KINDS.items():
            self.assertEqual(KINDS.get(kind), target, kind)

    def test_every_registered_target_resolves_to_a_callable(self):
        for kind, target in KINDS.items():
            module_path, function_name = target.split(":")
            module = importlib.import_module(module_path)
            self.assertTrue(callable(getattr(module, function_name)), kind)

    def test_the_fabricated_investment_report_package_is_gone(self):
        """가짜 케이스를 반환하던 패키지가 되살아나면 지어낸 분석이 발송된다."""
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("investment_agent.notifications.investment_report.run")


if __name__ == "__main__":
    unittest.main()
