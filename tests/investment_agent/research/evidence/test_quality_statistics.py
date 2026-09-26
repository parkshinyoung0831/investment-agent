"""TTM 품질·재무건전성·성장 통계와 v5 factor feature의 계산 규칙."""
from __future__ import annotations

import unittest

from investment_agent.research.features.layer import _momentum, _revisions, _valuation
from investment_agent.research.evidence.statistics import estimate_statistics, quality_statistics


def _quarter(year: int, period: int, **values) -> dict:
    month = {1: "03", 2: "06", 3: "09", 4: "12"}[period]
    base = {"fiscal_year": year, "fiscal_period": f"Q{period}", "period_end": f"{year}-{month}-30",
            "revenue": 100.0, "net_income": 10.0, "operating_income_loss": 15.0, "gross_profit": 40.0,
            "net_cash_from_operating_activities": 14.0, "capital_expenses": 4.0, "interest_expense": 1.0,
            "common_equity": 200.0, "assets": 400.0, "long_term_debt": 100.0}
    base.update(values)
    return base


def _eight_quarters(**latest) -> list[dict]:
    rows = [_quarter(2024, q, revenue=80.0) for q in (1, 2, 3, 4)] + [_quarter(2025, q) for q in (1, 2, 3, 4)]
    rows[-1].update(latest)
    return list(reversed(rows))


class QualityStatisticsTest(unittest.TestCase):
    def test_ttm_ratios_use_four_quarter_sums_and_latest_balance(self):
        stats = quality_statistics(_eight_quarters())
        self.assertAlmostEqual(stats["roe_ttm"], 40 / 200)
        self.assertAlmostEqual(stats["roa_ttm"], 40 / 400)
        self.assertAlmostEqual(stats["gross_margin_ttm"], 160 / 400)
        self.assertAlmostEqual(stats["fcf_margin_ttm"], (56 - 16) / 400)
        self.assertAlmostEqual(stats["interest_coverage_ttm"], 60 / 4)
        self.assertAlmostEqual(stats["accruals_ttm"], (40 - 56) / 400)
        self.assertAlmostEqual(stats["debt_to_equity"], 0.5)
        self.assertAlmostEqual(stats["revenue_growth_ttm_yoy"], 400 / 320 - 1)

    def test_prior_year_window_must_be_consecutive_and_adjacent(self):
        """전년 창에 구멍이 있거나 현재 TTM과 맞붙지 않으면 성장률을 만들지 않는다.

        4행이 모였다는 것만으로는 12개월이 아니고, 그러면 성장률이 조용히 다른 기간의
        비교가 된다(감사 RR2-03). 현재 TTM 창은 이미 같은 검사를 받는다.
        """
        rows = _eight_quarters()
        self.assertIn("revenue_growth_ttm_yoy", quality_statistics(rows))
        # 전년 창의 중간 분기(2024 Q4)를 두 해 전 분기로 바꾼다 — 4행은 유지되지만 연속이 아니다.
        with_hole = [row for row in rows if not (row["fiscal_year"] == 2024 and row["fiscal_period"] == "Q4")]
        with_hole.append(_quarter(2023, 4, revenue=80.0))
        stats = quality_statistics(with_hole)
        self.assertNotIn("revenue_growth_ttm_yoy", stats)
        # 현재 TTM 지표는 영향을 받지 않는다 — 그 창은 그대로 연속이다.
        self.assertIn("roe_ttm", stats)

    def test_order_of_rows_does_not_matter(self):
        rows = _eight_quarters()
        self.assertEqual(quality_statistics(rows), quality_statistics(list(reversed(rows))))

    def test_a_missing_quarter_value_leaves_the_ratio_empty_instead_of_three_quarter_sums(self):
        stats = quality_statistics(_eight_quarters(net_income=None))
        self.assertNotIn("roe_ttm", stats)
        self.assertIn("gross_margin_ttm", stats)

    def test_negative_equity_does_not_produce_roe(self):
        self.assertNotIn("roe_ttm", quality_statistics(_eight_quarters(common_equity=-5.0)))

    def test_gross_profit_falls_back_to_components_and_debt_sums_components(self):
        rows = _eight_quarters()
        for row in rows:
            row.pop("gross_profit")
            row["cost_of_goods_and_services_sold"] = 70.0 if row["revenue"] == 100.0 else 50.0
        rows[0].update(short_term_debt=10.0, long_term_debt=50.0)
        stats = quality_statistics(rows)
        self.assertAlmostEqual(stats["gross_margin_ttm"], 120 / 400)
        self.assertAlmostEqual(stats["debt_to_equity"], 60 / 200)

    def test_debt_to_equity_includes_operating_lease_liabilities(self):
        """카드(reporting)와 같은 정의를 써야 한다 — 예전엔 research만 운용리스를 빠뜨렸다(감사 RR2-09)."""
        rows = _eight_quarters()
        rows[0].update(
            short_term_debt=10.0, long_term_debt=50.0,
            operating_lease_current_debt_equivalent=5.0,
            operating_lease_non_current_debt_equivalent=15.0,
        )
        stats = quality_statistics(rows)
        self.assertAlmostEqual(stats["debt_to_equity"], (10 + 50 + 5 + 15) / 200)

    def test_fewer_than_four_quarters_produces_nothing(self):
        self.assertEqual(quality_statistics(_eight_quarters()[:3]), {})


class FactorFeatureTest(unittest.TestCase):
    def test_momentum_skips_the_most_recent_month(self):
        values = _momentum({"statistics": {"return_252d": 0.32, "return_120d": 0.10, "return_20d": 0.10,
                                           "max_drawdown_window": -0.2, "volatility_252d_annualized": 0.3}})
        self.assertAlmostEqual(values["momentum_12_1"], 1.32 / 1.10 - 1)
        self.assertAlmostEqual(values["momentum_6_1"], 0.0)

    def test_revision_breadth_is_bounded_and_needs_revisions(self):
        stats = estimate_statistics([{"revisions_up_30d": 3, "revisions_down_30d": 1}])
        self.assertAlmostEqual(stats["revision_breadth_30d"], 0.5)
        self.assertNotIn("revision_breadth_30d", estimate_statistics([{"revisions_up_30d": 0, "revisions_down_30d": 0}]))
        self.assertEqual(_revisions({"consensus_statistics": stats})["revision_breadth_30d"], 0.5)

    def test_eps_estimate_change_keeps_direction_for_negative_estimates(self):
        rows = [{"target_fiscal_year": 2026, "target_fiscal_period": "FY", "eps_avg": -0.5},
                {"target_fiscal_year": 2026, "target_fiscal_period": "FY", "eps_avg": -1.0}]
        self.assertAlmostEqual(estimate_statistics(rows)["eps_avg_change"], 0.5)

    def test_value_yields_keep_sign_and_distinguish_loss_from_missing(self):
        """적자는 "결측"이 아니라 음수 관측이어야 한다 — 결측으로 접으면 순위에서 빠져 유리해진다."""
        from datetime import datetime, timezone
        as_of = datetime(2026, 9, 14, tzinfo=timezone.utc)
        base = {"available_at": "2026-09-13T00:00:00+00:00"}
        profitable = _valuation(
            {**base, "pe_ttm": 20.0, "earnings_to_market_cap": 0.05, "fcf_to_market_cap": 0.04},
            as_of=as_of,
        )
        self.assertAlmostEqual(profitable["valuation_earnings_yield"], 0.05)
        self.assertAlmostEqual(profitable["valuation_fcf_yield"], 0.04)
        # 적자·현금소진: 비율(pe_ttm)은 정의되지 않지만 수익률은 음수로 남는다.
        loss_making = _valuation(
            {**base, "pe_ttm": None, "earnings_to_market_cap": -0.08, "fcf_to_market_cap": -0.02},
            as_of=as_of,
        )
        self.assertAlmostEqual(loss_making["valuation_earnings_yield"], -0.08)
        self.assertAlmostEqual(loss_making["valuation_fcf_yield"], -0.02)
        # 진짜 결측(미공시)은 여전히 None이다.
        undisclosed = _valuation({**base, "pe_ttm": None}, as_of=as_of)
        self.assertIsNone(undisclosed["valuation_earnings_yield"])
        self.assertIsNone(undisclosed["valuation_fcf_yield"])


if __name__ == "__main__":
    unittest.main()
