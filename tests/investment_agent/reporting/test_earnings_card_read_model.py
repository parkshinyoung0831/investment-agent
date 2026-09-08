"""카드가 쓰는 파생 read model이 실제로 값을 만드는지 지킨다.

이 다섯은 한동안 `return {}`으로 박혀 있었다("v1에 view가 없다"). 그동안 카드의
밸류에이션·수익성·재무건전성 블록이 통째로 사라졌는데, **예외가 없어서 카드는
정상으로 보였다** — 빈 블록은 그냥 안 그려진다. 값이 없어도 조용하다는 것이
이 검사가 필요한 이유다.
"""
from __future__ import annotations

import unittest
from unittest import mock

from investment_agent.reporting.notifications import earnings_report as db


def _quarters() -> list[dict]:
    """8분기치 최소 재무. TTM(4분기)과 전년 동기 비교가 성립하는 최소 크기다."""
    rows = []
    for index in range(8):
        rows.append({
            "ticker": "TEST",
            "fiscal_period": ("Q1", "Q2", "Q3", "Q4")[index % 4],
            "period_end": f"202{4 + index // 4}-{3 * (index % 4) + 3:02d}-30",
            "filed_at": f"202{4 + index // 4}-{3 * (index % 4) + 4:02d}-15",
            "revenue": 1000.0,
            "operating_income_loss": 200.0,
            "net_income": 150.0,
            "depreciation_amortization_cf": 50.0,
            "net_cash_from_operating_activities": 250.0,
            "capital_expenses": -60.0,
            "assets": 5000.0,
            "liabilities": 3000.0,
            "common_equity": 2000.0,
            "current_assets_total": 1800.0,
            "current_liabilities_total": 1200.0,
            "retained_earnings": 900.0,
            "cash_and_cash_equivalents": 400.0,
            "total_debt_including_current": 1000.0,
            "interest_expense": 20.0,
        })
    return rows


class DerivedReadModelTest(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(db, "_financial_rows", return_value=_quarters())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_health_is_not_empty(self):
        health = db.load_health(["TEST"])["TEST"]
        # 순이익 TTM 600 / 자본 2000
        self.assertAlmostEqual(0.30, health["roe"], places=4)
        self.assertAlmostEqual(0.12, health["roa"], places=4)
        self.assertIsNotNone(health["altman_z"])
        # 순부채 = 부채 1000 − 현금 400 = 600, EBITDA TTM = 800+200
        self.assertAlmostEqual(0.60, health["net_debt_to_ebitda"], places=4)

    def test_altman_z_uses_ttm_operating_income(self):
        """분기 영업이익을 연간 자산과 견주면 항이 1/4로 줄어 우량 기업이 위험으로 나온다."""
        health = db.load_health(["TEST"])["TEST"]
        quarterly_ebit_z = db._altman_z(_quarters()[-1], operating_ttm=200.0)
        self.assertGreater(health["altman_z"], quarterly_ebit_z)

    def test_earnings_quality_is_not_empty(self):
        quality = db.load_earnings_quality(["TEST"])["TEST"]
        self.assertEqual(600.0, quality["net_income_ttm"])
        self.assertEqual(1000.0, quality["operating_cash_flow_ttm"])
        self.assertEqual(760.0, quality["free_cash_flow_ttm"])
        # 발생액 = (순이익 − 영업현금) / 자산
        self.assertAlmostEqual((600.0 - 1000.0) / 5000.0, quality["accruals_ttm"])

    def test_valuation_snapshots_are_point_in_time(self):
        """스냅샷의 기준일은 공시 접수일이다 — 그 전 거래일에 이 숫자를 쓰면 미래를 본다."""
        snapshots = db.load_valuation_snapshots(["TEST"])["TEST"]
        self.assertTrue(snapshots)
        self.assertEqual(sorted(s["available_date"] for s in snapshots),
                         [s["available_date"] for s in snapshots])
        for snapshot in snapshots:
            self.assertEqual(600.0, snapshot["earnings_ttm"])
            self.assertEqual(4000.0, snapshot["revenue_ttm"])

    def test_ttm_refuses_a_partial_window(self):
        """네 분기가 안 되면 합치지 않는다. 부분 합은 틀린 TTM이다."""
        self.assertIsNone(db._ttm(_quarters()[:3], "revenue"))
        self.assertEqual(4000.0, db._ttm(_quarters(), "revenue"))


class AsOfLookupTest(unittest.TestCase):
    """정렬을 가정한 조기 종료가 값을 조용히 엉뚱한 날짜로 만든 적이 있다."""

    POINTS = [("2026-03-01", 10.0), ("2026-01-01", 5.0), ("2026-02-01", 7.0)]

    def test_unsorted_input_still_resolves_the_latest(self):
        self.assertEqual(7.0, db._as_of_value(self.POINTS, "2026-02-15"))

    def test_strictly_before_excludes_the_day_itself(self):
        self.assertEqual(7.0, db._as_of_value(self.POINTS, "2026-03-01", strictly_before=True))
        self.assertEqual(10.0, db._as_of_value(self.POINTS, "2026-03-01"))

    def test_no_usable_point_returns_none(self):
        self.assertIsNone(db._as_of_value(self.POINTS, "2025-12-31"))


if __name__ == "__main__":
    unittest.main()
