from __future__ import annotations

import unittest

from investment_agent.reporting.services.earnings import metrics, thresholds

RED = 0xCF202F
ORANGE = 0xF4B000
GREEN = 0x05B169
BLUE = 0x3182F6

CURRENT = {
    "revenue": 1_000.0,
    "gross_profit": 400.0,
    "operating_income_loss": 200.0,
    "net_income": 150.0,
    "net_income_to_common_shareholders": 150.0,
    "shares_fully_diluted_average": 100.0,
    "net_cash_from_operating_activities": 300.0,
    "capital_expenses": 50.0,
    "cash_and_cash_equivalents": 500.0,
    "long_term_debt": 800.0,
}
PRIOR = {
    "revenue": 800.0,
    "gross_profit": 300.0,
    "operating_income_loss": 140.0,
    "net_income": 100.0,
    "net_income_to_common_shareholders": 100.0,
    "shares_fully_diluted_average": 100.0,
}


class EarningsMetricsTest(unittest.TestCase):
    """실적 카드와 실적 화면이 공유하는 파생 지표·등급 계약."""

    def test_as_float_coerces_only_what_it_can(self) -> None:
        self.assertEqual(1.5, metrics.as_float("1.5"))
        self.assertIsNone(metrics.as_float(None))
        self.assertIsNone(metrics.as_float("n/a"))

    def test_derive_computes_margins_yoy_and_balance_items(self) -> None:
        d = metrics.derive(CURRENT, PRIOR)
        self.assertAlmostEqual(0.40, d["gross_margin"])
        self.assertAlmostEqual(0.20, d["operating_margin"])
        self.assertAlmostEqual(0.25, d["revenue_yoy"])
        self.assertAlmostEqual(0.50, d["net_income_yoy"])
        self.assertAlmostEqual(1.50, d["eps_diluted"])
        # FCF = 영업현금흐름 − capex(양수 = 유출), 순부채 = 차입 − 현금성.
        self.assertAlmostEqual(250.0, d["fcf"])
        self.assertAlmostEqual(300.0, d["net_debt"])
        self.assertFalse(d["is_first"])

    def test_first_observation_has_no_comparison(self) -> None:
        d = metrics.derive(CURRENT, None)
        self.assertTrue(d["is_first"])
        self.assertIsNone(d["revenue_yoy"])
        self.assertEqual(("신규", BLUE), thresholds.grade(d, has_anomaly=False)[:2])

    def test_grade_reads_the_most_dangerous_signal_first(self) -> None:
        healthy = metrics.derive(CURRENT, PRIOR)
        self.assertEqual(GREEN, thresholds.grade(healthy, has_anomaly=False)[1])
        # 대차대조표 불일치는 다른 무엇보다 앞선다.
        self.assertEqual(RED, thresholds.grade(healthy, has_anomaly=True)[1])

        loss_turn = metrics.derive({**CURRENT, "net_income": -10.0}, PRIOR)
        badge, color, _label = thresholds.grade(loss_turn, has_anomaly=False)
        self.assertEqual(("위험", RED), (badge, color))

        shrinking = metrics.derive({**CURRENT, "revenue": 780.0}, PRIOR)
        self.assertEqual(ORANGE, thresholds.grade(shrinking, has_anomaly=False)[1])
