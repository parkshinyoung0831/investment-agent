"""서류철 장기 구간 통계와 연도별 재무 추세 계약을 고정한다."""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from investment_agent.trading.contracts import EvidenceBundle, EvidenceItem
from investment_agent.trading.evidence.builder import DossierBuilder
from investment_agent.trading.evidence.history import (
    PRICE_WINDOWS,
    fundamental_trend,
    price_risk_profile,
)

_AS_OF = "2026-08-20T22:00:00+00:00"
_AVAILABLE = "2026-08-20T21:30:00+00:00"


def _daily(count: int, *, start: float = 100.0, step: float = 0.05,
           gap_days: int = 1, end: date | None = None) -> list[dict]:
    """최신순으로 오는 실제 조회 모양을 흉내낸다. gap_days로 주간 리샘플도 만든다."""
    last = end or date(2026, 8, 20)
    rows = []
    for index in range(count):
        day = last - timedelta(days=gap_days * (count - 1 - index))
        rows.append({"trade_date": day.isoformat(), "close": start + step * index})
    return list(reversed(rows))


def _sorted_prices(count: int) -> list[dict]:
    return _daily(count)


def _quarters(years: int, *, start_year: int = 2019, revenue: float = 100.0,
              growth: float = 0.10, partial_last: bool = False) -> list[dict]:
    rows = []
    for offset in range(years):
        year = start_year + offset
        annual = revenue * ((1.0 + growth) ** offset)
        periods = ("Q1", "Q2", "Q3", "Q4")
        if partial_last and offset == years - 1:
            periods = ("Q1", "Q2", "Q3")
        for period in periods:
            rows.append({
                "fiscal_year": year, "fiscal_period": period,
                "revenue": annual / 4.0,
                "net_income": annual / 40.0,
                "operating_income_loss": annual / 20.0,
            })
    return rows


class PriceRiskProfileTest(unittest.TestCase):
    def test_all_six_windows_are_always_reported(self):
        profile = price_risk_profile(_sorted_prices(300))
        labels = [window["label"] for window in profile["windows"]]
        self.assertEqual(labels, [label for label, _ in PRICE_WINDOWS])

    def test_short_history_reports_a_reason_not_a_number(self):
        """3년치가 없으면 추정하지 않고 왜 없는지 남긴다."""
        profile = price_risk_profile(_sorted_prices(300))
        by_label = {window["label"]: window for window in profile["windows"]}
        self.assertIn("total_return", by_label["1Y"])
        self.assertNotIn("total_return", by_label["7Y"])
        self.assertIn("need_", by_label["7Y"]["missing_reason"])

    def test_seven_year_window_fills_when_history_is_deep(self):
        profile = price_risk_profile(_sorted_prices(252 * 8))
        by_label = {window["label"]: window for window in profile["windows"]}
        self.assertIsNotNone(by_label["7Y"]["total_return"])
        self.assertIsNotNone(by_label["7Y"]["annualized_volatility"])

    def test_rising_series_puts_the_price_at_the_top_percentile(self):
        profile = price_risk_profile(_sorted_prices(600))
        self.assertAlmostEqual(profile["price_percentile_1y"], 1.0)

    def test_input_order_does_not_change_the_result(self):
        rows = _sorted_prices(400)
        self.assertEqual(
            price_risk_profile(rows)["latest_close"],
            price_risk_profile(list(reversed(rows)))["latest_close"],
        )

    def test_empty_history_returns_nothing_rather_than_zeros(self):
        self.assertEqual(price_risk_profile([]), {})

    def test_drawdown_is_negative_for_a_fallen_price(self):
        rows = _sorted_prices(300)
        # 조회 결과는 최신순이므로 rows[0]이 가장 최근 봉이다.
        rows[0] = {**rows[0], "close": 1.0}
        profile = price_risk_profile(rows)
        by_label = {window["label"]: window for window in profile["windows"]}
        self.assertLess(by_label["1Y"]["max_drawdown"], -0.5)


class SamplingFrequencyTest(unittest.TestCase):
    """주간 데이터를 일별로 취급해 sqrt(252)를 곱하면 변동성이 2배 부풀려진다."""

    def test_weekly_series_reports_no_annualized_volatility(self):
        profile = price_risk_profile(_daily(300, gap_days=7))
        window = next(w for w in profile["windows"] if w["label"] == "1Y")
        self.assertNotIn("annualized_volatility", window)
        self.assertIn("of_gaps_are_daily", window["annualized_volatility_missing_reason"])

    def test_weekly_series_still_reports_return_and_drawdown(self):
        """수익률과 낙폭은 표본 간격과 무관하게 의미가 있다."""
        profile = price_risk_profile(_daily(300, gap_days=7))
        window = next(w for w in profile["windows"] if w["label"] == "1Y")
        self.assertIsNotNone(window["total_return"])
        self.assertIsNotNone(window["max_drawdown"])
        self.assertEqual(window["median_gap_days"], 7.0)

    def test_daily_series_keeps_its_volatility(self):
        profile = price_risk_profile(_daily(300, gap_days=1))
        window = next(w for w in profile["windows"] if w["label"] == "1Y")
        self.assertIsNotNone(window["annualized_volatility"])
        self.assertNotIn("annualized_volatility_missing_reason", window)

    def test_partially_weekly_window_is_also_refused(self):
        """창의 절반이 주간이면 중앙값은 1일이라 통과한다 — 비율로 봐야 잡힌다."""
        weekly = _daily(150, gap_days=7, end=date(2023, 8, 20))
        daily = _daily(160, gap_days=1, end=date(2026, 8, 20))
        profile = price_risk_profile(weekly + daily)
        window = next(w for w in profile["windows"] if w["label"] == "1Y")
        self.assertLess(window["daily_gap_ratio"], 0.90)
        self.assertNotIn("annualized_volatility", window)

    def test_daily_gap_ratio_is_reported_for_every_window(self):
        profile = price_risk_profile(_daily(300, gap_days=1))
        window = next(w for w in profile["windows"] if w["label"] == "1Y")
        self.assertAlmostEqual(window["daily_gap_ratio"], 1.0)

    def test_longest_daily_window_names_the_trustworthy_horizon(self):
        profile = price_risk_profile(_daily(300, gap_days=1))
        self.assertEqual(profile["longest_daily_window"], "1Y")

    def test_percentile_survives_a_sparse_series(self):
        """분위는 간격과 무관하므로 주간 데이터에서도 만든다."""
        profile = price_risk_profile(_daily(300, gap_days=7))
        self.assertIsNotNone(profile["price_percentile_1y"])

    def test_profile_reports_the_actual_date_range(self):
        profile = price_risk_profile(_daily(10, gap_days=1))
        self.assertEqual(profile["latest_trade_date"], "2026-08-20")
        self.assertEqual(profile["earliest_trade_date"], "2026-08-11")


class FundamentalTrendTest(unittest.TestCase):
    def test_annual_points_sum_four_quarters(self):
        trend = fundamental_trend(_quarters(3))
        first = trend["years"][0]
        self.assertEqual(first["quarters"], 4)
        self.assertAlmostEqual(first["revenue"], 100.0)

    def test_cagr_matches_the_configured_growth(self):
        trend = fundamental_trend(_quarters(6, growth=0.10))
        self.assertAlmostEqual(trend["revenue_cagr"], 0.10, places=6)
        self.assertEqual(trend["cagr_span_years"], 5)

    def test_partial_year_is_excluded_from_growth(self):
        """3분기만 있는 해를 온전한 해와 비교하면 성장률이 낮게 나온다."""
        trend = fundamental_trend(_quarters(5, partial_last=True))
        self.assertEqual(trend["partial_years"], [2023])
        self.assertEqual(trend["complete_years"], 4)
        self.assertAlmostEqual(trend["revenue_cagr"], 0.10, places=6)

    def test_negative_start_produces_no_cagr(self):
        rows = _quarters(3)
        for row in rows[:4]:
            row["net_income"] = -10.0
        trend = fundamental_trend(rows)
        self.assertIsNone(trend["net_income_cagr"])
        self.assertIsNotNone(trend["revenue_cagr"])

    def test_margin_change_is_reported(self):
        trend = fundamental_trend(_quarters(4))
        self.assertIn("operating_margin_change", trend)
        # 분기 영업이익 annual/20 x 4분기 = annual/5 → 마진 0.20
        self.assertAlmostEqual(trend["operating_margin_last"], 0.20, places=6)

    def test_one_year_only_reports_a_reason(self):
        trend = fundamental_trend(_quarters(1))
        self.assertNotIn("revenue_cagr", trend)
        self.assertIn("need_2_complete_years", trend["missing_reason"])

    def test_window_is_capped_to_max_years(self):
        trend = fundamental_trend(_quarters(12), max_years=7)
        self.assertEqual(len(trend["years"]), 7)


class BuilderWiringTest(unittest.TestCase):
    def _bundle(self) -> EvidenceBundle:
        return EvidenceBundle(
            ticker="AAA", as_of_at=_AS_OF, source_kind="live_shadow",
            evidence=(
                EvidenceItem(
                    evidence_id="EV-market-1", domain="market", source="market.prices_daily",
                    observed_at="2026-08-20", available_at=_AVAILABLE, timing_status="known",
                    payload={"statistics": {
                        "latest_close": 130.0, "observations": 260, "return_252d": 0.30,
                        "volatility_20d_annualized": 0.24, "max_drawdown_window": -0.12,
                    }},
                ),
                EvidenceItem(
                    evidence_id="EV-fund-1", domain="fundamentals", source="sec",
                    observed_at="2026-07-25", available_at=_AVAILABLE, timing_status="known",
                    payload={
                        "statistics": {"net_margin": 0.1},
                        "filings": [{"period_end": "2026-06-30", "filed_at": "2026-07-25"}],
                    },
                ),
            ),
        )

    def test_long_horizon_is_attached_when_history_is_supplied(self):
        dossier = DossierBuilder().build(
            self._bundle(),
            price_history=_sorted_prices(252 * 8),
            filing_history=_quarters(7),
        )
        price = dossier.section("price_risk").payload
        self.assertIn("long_horizon", price)
        self.assertEqual(len(price["long_horizon"]["windows"]), len(PRICE_WINDOWS))
        fundamentals = dossier.section("fundamentals").payload
        self.assertIn("long_horizon", fundamentals)
        self.assertIn("revenue_cagr", fundamentals["long_horizon"])

    def test_bundle_only_still_produces_a_valid_dossier(self):
        """장기 조회가 없어도 서류철은 만들어진다 — 섹션만 얕아진다."""
        dossier = DossierBuilder().build(self._bundle())
        price = dossier.section("price_risk").payload
        self.assertNotIn("long_horizon", price)
        self.assertTrue(dossier.section("price_risk").is_known)

    def test_short_window_statistics_use_the_real_keys(self):
        """price_statistics의 실제 키와 어긋나면 값이 조용히 사라진다."""
        payload = DossierBuilder().build(self._bundle()).section("price_risk").payload
        self.assertEqual(payload["volatility"], 0.24)
        self.assertEqual(payload["max_drawdown"], -0.12)

    def test_history_sizes_are_recorded_in_provenance(self):
        dossier = DossierBuilder().build(
            self._bundle(), price_history=_sorted_prices(500), filing_history=_quarters(3),
        )
        self.assertEqual(dossier.provenance["price_history_bars"], 500)
        self.assertEqual(dossier.provenance["filing_history_rows"], 12)


if __name__ == "__main__":
    unittest.main()
