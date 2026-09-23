"""Ablation 재현: 운영 System 엔진을 변형별로 돌리고, 운영 원장에 쓰지 않으며, 미래를 본 ML은 거부한다."""
from __future__ import annotations

import random
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from investment_agent.research.system_validation.ablation import (
    _coverage_reason,
    ReplayRepository,
    default_variants,
    ml_artifact_lookahead,
    run_ablation,
)
from investment_agent.research.features.factors import FactorScore
from investment_agent.trading.risk.stress import STRESS_PROXIES

START_DAY = date(2025, 1, 1)
NAMES = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")


def _history() -> dict[str, list[dict]]:
    rng = random.Random(11)
    market = [0.0004 + rng.gauss(0, 0.009) for _ in range(420)]
    history: dict[str, list[dict]] = {}
    for name in sorted({*NAMES, "SPY", *STRESS_PROXIES}):
        price, rows = 100.0, []
        for offset in range(420):
            day = START_DAY + timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            price *= 1 + 0.9 * market[offset] + rng.gauss(0, 0.011)
            rows.append({"trade_date": day.isoformat(), "open": price, "close": price, "volume": 5_000_000})
        history[name] = rows
    return history


class _Base:
    """운영 repository 흉내. 판단 기록 저장 메서드가 없으므로, 재현이 저장을 시도하면 바로 실패한다."""

    def __init__(self):
        self.history = _history()
        self.membership_calls = 0

    def market_prices(self, ticker, as_of_at, limit=260):
        rows = [row for row in self.history.get(ticker, []) if row["trade_date"] <= as_of_at.date().isoformat()]
        return rows[-limit:]

    def historical_sp500_membership(self, *, start_date, end_date):
        self.membership_calls += 1
        return [{"effective_date": start_date.isoformat(), "symbols": list(NAMES)}]

    def sp500_sector_map(self, tickers):
        return {ticker: ("tech" if ticker in {"AAA", "BBB", "CCC"} else "energy") for ticker in tickers}

    def macro_histories(self, series_ids, *, as_of_at, lookback_days=120):
        return {}

    def thesis_views(self, tickers, *, as_of_at, valid_days):
        return {}

    def rl_feature_snapshot_rows(self, *args, **kwargs):
        return []


def _cross_section(as_of_at: datetime):
    week = as_of_at.date() - timedelta(days=as_of_at.weekday())
    scores = {ticker: FactorScore(ticker, {"quality": 0.8, "momentum": 0.5, "value": 0.5}, value, True, None)
              for ticker, value in dict(AAA=0.95, BBB=0.9, CCC=0.85, DDD=0.4, EEE=0.3, FFF=0.2).items()}
    return week.isoformat(), scores


class AblationTest(unittest.TestCase):
    def test_variants_replay_the_production_engine_without_touching_the_ledger(self):
        base = _Base()
        variants = [variant for variant in default_variants() if variant.name in {"factor_only", "no_tail_risk"}]
        report = run_ablation(base, start=date(2025, 11, 1), end=date(2026, 1, 31), variants=variants,
                              cross_section=_cross_section)
        self.assertEqual(report["baseline"], "factor_only")
        self.assertGreater(report["sessions"], 40)
        by_name = {row["name"]: row for row in report["variants"]}
        self.assertEqual(set(by_name), {"factor_only", "no_tail_risk"})
        for row in by_name.values():
            self.assertEqual(row["status"], "completed")
            self.assertGreaterEqual(row["targets"], 1)
            self.assertGreater(row["summary"]["days"], 20)
            self.assertGreater(row["coverage"]["factor_snapshot_periods"], 1)
            self.assertGreater(row["coverage"]["risky_target_count"], 0)
            self.assertGreater(row["coverage"]["factor_category_periods"]["quality"], 1)
            self.assertIn("tail_risk_enabled_periods", row["coverage"])
            self.assertIn("tail_risk_bound_periods", row["coverage"])
            self.assertIn("market_risk_input_periods", row["coverage"])
        self.assertGreater(by_name["factor_only"]["coverage"]["tail_risk_enabled_periods"], 0)
        self.assertEqual(by_name["no_tail_risk"]["coverage"]["tail_risk_enabled_periods"], 0)
        self.assertEqual(by_name["factor_only"]["versus_baseline"]["total_return"], 0.0)
        self.assertFalse(by_name["no_tail_risk"]["system_policy"]["use_tail_risk"])
        self.assertFalse(by_name["no_tail_risk"]["alpha_policy"]["use_thesis"])
        self.assertEqual(
            by_name["factor_only"]["summary"]["start_date"],
            by_name["no_tail_risk"]["summary"]["start_date"],
        )
        self.assertGreater(base.membership_calls, 0)  # 종목은 판단 시각의 멤버십으로 정했다
        # 채택 판정과 단계 진단이 결과에 같이 나온다(재현 창이 짧아 긴 기간은 채점되지 않는다).
        row = by_name["no_tail_risk"]
        self.assertIn("tracking_error", row["summary"])
        self.assertIn("all_passed", row["adoption_checks"])
        diagnosis = row["stage_diagnosis"]
        self.assertGreater(diagnosis["traced_targets"], 0)
        self.assertEqual(0, diagnosis["untraced_targets"])
        self.assertGreater(diagnosis["horizons"]["5"]["targets"], 0)

    def test_ml_fit_on_data_after_the_replay_start_is_refused(self):
        early = {"artifact": {"train_period": ["2023-01-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00"],
                              "validation_period": ["2024-01-02T00:00:00+00:00", "2024-06-01T00:00:00+00:00"],
                              "oos_period": ["2024-06-02T00:00:00+00:00", "2024-12-01T00:00:00+00:00"]}}
        replay_start = datetime(2025, 12, 1, 21, tzinfo=UTC)
        self.assertIsNone(ml_artifact_lookahead(early, replay_start=replay_start))
        late = {"artifact": {**early["artifact"], "oos_period": ["2024-06-02T00:00:00+00:00", "2025-12-20T00:00:00+00:00"]}}
        self.assertIn("after the replay start", ml_artifact_lookahead(late, replay_start=replay_start))

        base = _Base()
        variants = [variant for variant in default_variants() if variant.name in {"factor_only", "factor_ml"}]
        report = run_ablation(base, start=date(2025, 12, 1), end=date(2026, 1, 15), variants=variants,
                              ml_artifact=late, cross_section=_cross_section)
        by_name = {row["name"]: row for row in report["variants"]}
        self.assertEqual(by_name["factor_ml"]["status"], "refused")
        self.assertEqual(by_name["factor_only"]["status"], "completed")

    def test_replay_repository_reads_members_at_the_decision_time_and_drops_ledger_writes(self):
        base = _Base()
        repository = ReplayRepository(base, feature_rows=lambda start, end: [])
        with self.assertRaises(RuntimeError):
            repository.current_tracked_tickers()
        repository.now = datetime(2025, 6, 2, 21, tzinfo=UTC)
        self.assertEqual(repository.current_tracked_tickers(), sorted(NAMES))
        self.assertIsNone(repository.save_portfolio_proposal({"proposal_id": "x"}))
        self.assertIsNone(repository.factor_cross_section(repository.now))

    def test_default_variants_cover_the_requested_comparisons(self):
        variants = default_variants()
        names = {variant.name for variant in variants}
        self.assertTrue({"factor_only", "factor_ml", "factor_ml_thesis", "no_tail_risk", "no_market_risk",
                         "cvar_5", "cvar_12"} <= names)
        risk_variants = [variant for variant in variants if variant.name in {"no_tail_risk", "no_market_risk", "cvar_5", "cvar_12"}]
        self.assertTrue(all(not variant.alpha.use_ml and not variant.alpha.use_thesis for variant in risk_variants))

    def test_missing_ml_and_thesis_inputs_are_not_reported_as_completed(self):
        defaults = default_variants()
        factor_ml = next(variant for variant in defaults if variant.name == "factor_ml")
        factor_thesis = replace(
            next(variant for variant in defaults if variant.name == "factor_ml_thesis"),
            alpha=replace(factor_ml.alpha, use_ml=False, use_thesis=True),
        )
        report = run_ablation(
            _Base(), start=date(2025, 11, 1), end=date(2026, 1, 31),
            variants=(factor_ml, factor_thesis), cross_section=_cross_section,
        )
        by_name = {row["name"]: row for row in report["variants"]}
        self.assertEqual(by_name["factor_ml"]["status"], "insufficient_coverage")
        self.assertEqual(by_name["factor_ml"]["reason"], "ml_forecast_never_applied")
        self.assertEqual(by_name["factor_ml_thesis"]["status"], "insufficient_coverage")
        self.assertEqual(by_name["factor_ml_thesis"]["reason"], "thesis_view_never_observed")


class CoverageHonestyTest(unittest.TestCase):
    """위험 정책을 바꾼 변형은 위험자산을 한 번도 담지 못했으면 completed가 아니다."""

    def _row(self, *, risky: int) -> dict:
        return {
            "targets": [{"as_of": "2025-06-02T00:00:00+00:00"}],
            "coverage": {
                "factor_snapshot_periods": 3,
                "ml_forecasts_applied": 0,
                "thesis_views_seen": 0,
                "risky_target_count": risky,
            },
        }

    def _cvar_variant(self, limit: float):
        """--cvar-limits 로 요청한 임의 한도의 변형. 이름은 기본값 목록에 없다."""
        variants = default_variants(cvar_limits=(limit,))
        return next(variant for variant in variants
                    if variant.system.max_cvar_95_5d == limit
                    and variant.name.startswith("cvar_"))

    def test_a_cvar_variant_outside_the_default_limits_is_still_checked(self):
        """이름 목록으로 판정하면 cvar_20 은 검사를 건너뛰어 조용히 completed 가 된다."""
        variant = self._cvar_variant(0.20)
        self.assertNotIn(variant.name, {"cvar_5", "cvar_12"})
        self.assertEqual(
            _coverage_reason(self._row(risky=0), variant),
            "risk_policy_never_exercised",
        )

    def test_the_default_cvar_variants_are_still_checked(self):
        variant = self._cvar_variant(0.05)
        self.assertEqual(
            _coverage_reason(self._row(risky=0), variant),
            "risk_policy_never_exercised",
        )

    def test_a_variant_that_did_hold_risky_assets_is_not_flagged(self):
        self.assertIsNone(_coverage_reason(self._row(risky=4), self._cvar_variant(0.20)))

    def test_the_operating_variant_is_not_treated_as_a_risk_variant(self):
        """운영 구성은 위험 정책을 바꾸지 않았으므로 이 사유로 걸리지 않는다."""
        operating = next(variant for variant in default_variants()
                         if variant.name == "factor_only")
        self.assertIsNone(_coverage_reason(self._row(risky=0), operating))

if __name__ == "__main__":
    unittest.main()


class RebasedCommonWindowTest(unittest.TestCase):
    """공통 구간을 다시 100으로 맞추지 않으면 같은 날짜를 보는데 SPY 수익률이 변형마다 달라진다."""

    def test_variants_starting_on_different_days_share_one_benchmark_return(self):
        from investment_agent.research.system_validation.ablation import _rebased
        from investment_agent.trading.system.accounting import DailyMark, performance_summary

        def mark(day, nav, bench):
            return DailyMark(day, nav, 0.0, {"CASH": 1.0}, {}, bench, bench)

        early = [mark("2025-01-02", 110.0, 120.0), mark("2025-01-03", 121.0, 132.0)]   # 앞서 시작한 원장
        late = [mark("2025-01-02", 100.0, 100.0), mark("2025-01-03", 105.0, 110.0)]    # 늦게 시작한 원장
        first = performance_summary(_rebased(early))
        second = performance_summary(_rebased(late))
        self.assertAlmostEqual(first["benchmark_return"], second["benchmark_return"])
        self.assertAlmostEqual(0.10, first["benchmark_return"])
        self.assertAlmostEqual(0.10, first["total_return"])


class NavReconciliationTest(unittest.TestCase):
    """원장 NAV를 가격표로 따로 계산해 대조한다 — 분할 이중 반영 같은 회계 결함이 +553%를 만들었다."""

    @staticmethod
    def _mark(day, nav, daily_return, weights, closes):
        from investment_agent.trading.system.accounting import DailyMark

        return DailyMark(day, nav, daily_return, weights, closes, 100.0, 100.0)

    def test_a_split_double_count_is_flagged(self):
        from investment_agent.research.system_validation.ablation import unexplained_nav_days

        history = [
            self._mark("2022-07-15", 100.0, 0.0, {"GOOGL": 0.05, "CASH": 0.95}, {"GOOGL": 111.78}),
            self._mark("2022-07-18", 192.0, 0.92, {"GOOGL": 0.5, "CASH": 0.5}, {"GOOGL": 109.03}),
        ]
        self.assertEqual(["2022-07-18"], [row["trade_date"] for row in unexplained_nav_days(history)])

    def test_price_moves_explain_a_normal_day(self):
        from investment_agent.research.system_validation.ablation import unexplained_nav_days

        history = [
            self._mark("d1", 100.0, 0.0, {"AAA": 0.5, "CASH": 0.5}, {"AAA": 100.0}),
            self._mark("d2", 105.0, 0.05, {"AAA": 0.52, "CASH": 0.48}, {"AAA": 110.0}),
        ]
        self.assertEqual([], unexplained_nav_days(history))


class AdoptionChecksTest(unittest.TestCase):
    """설계 §9.2의 기준이 숫자로 판정되고, 값이 없으면 통과로 치지 않는다."""

    def _summary(self, **overrides):
        summary = {"excess_return": 0.10, "information_ratio": 0.5, "tracking_error": 0.06,
                   "max_rebalance_turnover": 0.25,
                   "stress": {"2022_bear": {"max_drawdown": 0.20, "benchmark_max_drawdown": 0.25,
                                            "cvar_95_5d": 0.05, "benchmark_cvar_95_5d": 0.06}}}
        summary.update(overrides)
        return summary

    def test_a_challenger_meeting_every_criterion_passes(self):
        from investment_agent.research.system_validation.ablation import adoption_checks

        checks = adoption_checks(self._summary(), self._summary(excess_return=0.0, information_ratio=0.1))
        self.assertTrue(checks["all_passed"], checks)

    def test_each_criterion_can_fail_on_its_own(self):
        from investment_agent.research.system_validation.ablation import adoption_checks

        champion = self._summary(excess_return=0.0, information_ratio=0.1)
        cases = {
            "excess_return_not_worse": self._summary(excess_return=-0.01),
            "tracking_error_within_target": self._summary(tracking_error=0.10),
            "drawdown_2022_not_worse_than_spy": self._summary(stress={"2022_bear": {
                "max_drawdown": 0.30, "benchmark_max_drawdown": 0.25, "cvar_95_5d": 0.05,
                "benchmark_cvar_95_5d": 0.06}}),
            "rebalance_turnover_within_limit": self._summary(max_rebalance_turnover=0.30),
        }
        for name, summary in cases.items():
            checks = adoption_checks(summary, champion)
            self.assertFalse(checks[name], name)
            self.assertFalse(checks["all_passed"], name)

    def test_a_missing_value_is_not_a_pass(self):
        from investment_agent.research.system_validation.ablation import adoption_checks

        checks = adoption_checks(self._summary(stress={}), self._summary())
        self.assertIsNone(checks["drawdown_2022_not_worse_than_spy"])
        self.assertFalse(checks["all_passed"])


class ActiveRiskSummaryTest(unittest.TestCase):
    def _rows(self, portfolio, benchmark, *, start=date(2021, 12, 1)):
        rows, nav, bench = [], 100.0, 100.0
        for index, (p, b) in enumerate(zip(portfolio, benchmark)):
            nav, bench = nav * (1 + p), bench * (1 + b)
            rows.append({"trade_date": (start + timedelta(days=index)).isoformat(), "nav": nav,
                         "benchmark_nav": bench, "daily_return": p, "turnover": 0.5 if index == 0 else 0.1,
                         "cost": 0.0, "weights": {"CASH": 0.1}})
        return rows

    def test_identical_paths_have_zero_tracking_error_and_equal_stress(self):
        from investment_agent.trading.system.accounting import active_risk_summary

        rng = random.Random(3)
        path = [rng.gauss(0, 0.01) for _ in range(200)]
        summary = active_risk_summary(self._rows(path, path))
        self.assertAlmostEqual(0.0, summary["tracking_error"], places=12)
        self.assertIsNone(summary["information_ratio"])
        stress = summary["stress"]["2022_bear"]
        self.assertAlmostEqual(stress["max_drawdown"], stress["benchmark_max_drawdown"])
        self.assertEqual({"2021", "2022"}, set(summary["yearly"]))
        self.assertAlmostEqual(0.1, summary["max_rebalance_turnover"])  # 첫 편입(0.5)은 빼고 본다

    def test_a_half_invested_portfolio_halves_the_drawdown(self):
        from investment_agent.trading.system.accounting import active_risk_summary

        bench = [-0.01] * 60 + [0.005] * 60
        summary = active_risk_summary(self._rows([value / 2 for value in bench], bench, start=date(2022, 1, 3)))
        stress = summary["stress"]["2022_bear"]
        self.assertLess(stress["max_drawdown"], stress["benchmark_max_drawdown"])
        self.assertLess(stress["cvar_95_5d"], stress["benchmark_cvar_95_5d"])

