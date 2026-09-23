"""단계 진단 — 목표의 SPY 대비 성과를 단계별로 정확히 나누고, 틀린 단계를 가려내는가."""
from __future__ import annotations

import math
import unittest

from investment_agent.trading.performance.stage_diagnosis import (
    PricePaths,
    diagnose,
    diagnose_target,
    non_overlapping,
    rank_ic,
    stage_trace,
    summarize,
)

DATES = [f"2026-01-{day:02d}" for day in range(1, 31)]


def _path(daily: float, *, dividend_on: str | None = None, dates=DATES) -> list[dict]:
    rows, close = [], 100.0
    for day in dates:
        rows.append({"trade_date": day, "close": close, "div_amount": 1.0 if day == dividend_on else 0.0})
        close *= 1.0 + daily
    return rows


def _prices(daily_by_symbol: dict[str, float], **overrides) -> PricePaths:
    paths = {symbol: _path(daily) for symbol, daily in daily_by_symbol.items()}
    paths.update(overrides)
    return PricePaths(lambda symbol: paths.get(symbol, []))


def _trace(securities: dict[str, dict], *, cash: float, approved: bool = True) -> dict:
    return {"is_approved": approved, "cash": {"approved": cash if approved else None}, "securities": securities}


def _security(alpha, weight, reason="FACTOR_BASE", prior=None):
    return {"prior": alpha if prior is None else prior, "ml": None, "ml_share": 0.0, "alpha": alpha,
            "reason": reason, "approved": weight}


class PricePathsTest(unittest.TestCase):
    def test_total_return_includes_dividends_and_needs_the_full_horizon(self):
        prices = PricePaths(lambda symbol: _path(0.0, dividend_on="2026-01-03"))
        total, start, end = prices.forward_return("X", after="2026-01-01", horizon=5)
        self.assertAlmostEqual(0.01, total)
        self.assertEqual(("2026-01-01", "2026-01-06"), (start, end))
        self.assertIsNone(prices.forward_return("X", after="2026-01-28", horizon=5))

    def test_a_decision_on_a_holiday_starts_from_the_last_close_before_it(self):
        dates = [day for day in DATES if day != "2026-01-05"]
        prices = PricePaths(lambda symbol: _path(0.0, dates=dates))
        self.assertEqual("2026-01-04", prices.forward_return("X", after="2026-01-05", horizon=1)[1])


class RankIcTest(unittest.TestCase):
    def test_perfect_reversed_and_too_few(self):
        values = [(float(index), float(index)) for index in range(10)]
        self.assertAlmostEqual(1.0, rank_ic(values))
        self.assertAlmostEqual(-1.0, rank_ic([(a, -b) for a, b in values]))
        self.assertIsNone(rank_ic(values[:5]))
        self.assertIsNone(rank_ic([(1.0, float(index)) for index in range(10)]))


class DecompositionTest(unittest.TestCase):
    def test_the_four_components_add_up_to_the_active_return(self):
        daily = {"SPY": 0.001, "A": 0.004, "B": -0.002, "C": 0.0015, "D": 0.0, "E": 0.003}
        weights = {"A": 0.30, "B": 0.10, "C": 0.20, "D": 0.0, "E": 0.0}
        securities = {symbol: _security(0.01 * index, weight) for index, (symbol, weight) in enumerate(weights.items())}
        row = diagnose_target(_trace(securities, cash=0.40), _prices(daily), decided_on="2026-01-01", horizon=10)
        benchmark = (1.001) ** 10 - 1
        direct = sum(weight * ((1 + daily[symbol]) ** 10 - 1 - benchmark) for symbol, weight in weights.items())
        direct -= 0.40 * benchmark
        self.assertAlmostEqual(direct, row["active_return"], places=12)
        self.assertAlmostEqual(row["active_return"], math.fsum(row["components"].values()), places=12)
        self.assertAlmostEqual(-0.40 * benchmark, row["components"]["exposure_effect"], places=12)

    def test_exposure_splits_into_required_and_discretionary_cash(self):
        """시장 위험 예산이 강제한 현금(하한)과 optimizer가 그 위에 남긴 현금을 나눈다."""
        trace = {**_trace({"A": _security(0.01, 0.6)}, cash=0.40), "min_cash_weight": 0.15}
        row = diagnose_target(trace, _prices({"SPY": 0.001, "A": 0.001}), decided_on="2026-01-01", horizon=10)
        benchmark = (1.001) ** 10 - 1
        self.assertAlmostEqual(-0.15 * benchmark, row["exposure_split"]["required_cash_effect"], places=12)
        self.assertAlmostEqual(-0.25 * benchmark, row["exposure_split"]["discretionary_cash_effect"], places=12)
        self.assertAlmostEqual(row["components"]["exposure_effect"], sum(row["exposure_split"].values()), places=12)

    def test_a_name_whose_path_ends_on_a_different_day_is_not_scored(self):
        """거래 정지로 H거래일째가 SPY와 다른 날이면 같은 기간이 아니다."""
        gappy = [day for day in DATES if day not in {"2026-01-03", "2026-01-04"}]
        prices = _prices({"SPY": 0.0, "A": 0.01}, B=_path(0.01, dates=gappy))
        row = diagnose_target(_trace({"A": _security(0.01, 0.5), "B": _security(0.02, 0.4)}, cash=0.1),
                              prices, decided_on="2026-01-01", horizon=5)
        self.assertEqual(1, row["scored_names"])
        self.assertAlmostEqual(0.4, row["unscored_weight"])

    def test_a_rejected_target_is_scored_for_information_but_not_for_money(self):
        daily = {"SPY": 0.0, **{f"S{index}": 0.001 * index for index in range(10)}}
        securities = {f"S{index}": _security(0.001 * index, None) for index in range(10)}
        row = diagnose_target(_trace(securities, cash=0.0, approved=False), _prices(daily),
                              decided_on="2026-01-01", horizon=5)
        self.assertNotIn("components", row)
        self.assertAlmostEqual(1.0, row["information"]["alpha_ic"])
        self.assertEqual(0.0, row["information"]["thesis_ic_delta"])


class ThesisIncrementTest(unittest.TestCase):
    def test_a_quality_clamp_before_the_thesis_is_not_counted_as_the_thesis_effect(self):
        """품질 탈락으로 0에 묶인 값은 논지 전 단계의 결과다. 논지가 없으면 논지 증분은 0이어야 한다."""
        daily = {"SPY": 0.0, **{f"S{index}": 0.001 * index for index in range(10)}}
        securities = {f"S{index}": {**_security(0.001 * index, 0.05), "pre_thesis": 0.001 * index}
                      for index in range(10)}
        securities["S9"].update(alpha=0.0, pre_thesis=0.0, reason="FACTOR_BREAKDOWN")
        row = diagnose_target(_trace(securities, cash=0.5), _prices(daily), decided_on="2026-01-01", horizon=5)
        self.assertEqual(0.0, row["information"]["thesis_ic_delta"])
        self.assertLess(row["information"]["alpha_ic"], row["information"]["factor_ic"])


class GateVerdictTest(unittest.TestCase):
    def test_a_gate_that_keeps_blocking_winners_is_judged_as_hurting(self):
        """검증 전 편입 차단에 걸린 종목이 매번 후보 평균보다 더 벌었다면 그 차단은 기회를 버린 것이다."""
        dates = [f"2026-{month:02d}-{day:02d}" for month in range(1, 13) for day in range(1, 29)]
        daily = {"SPY": 0.0005, "WIN": 0.003, **{f"S{index}": 0.0002 * index for index in range(9)}}
        paths = {symbol: _path(value, dates=dates) for symbol, value in daily.items()}
        close = 100.0
        for index, row in enumerate(paths["WIN"]):
            # 구간마다 초과수익이 달라야 t가 정의된다(평균은 여전히 후보 평균보다 크다).
            row["close"] = close
            close *= 1.0 + 0.003 + 0.004 * math.sin(index)
        prices = PricePaths(lambda symbol: paths[symbol])
        securities = {f"S{index}": _security(0.001 * index, 0.05) for index in range(9)}
        securities["WIN"] = _security(0.0, 0.0, reason="UNVERIFIED_ENTRY_BLOCKED", prior=0.02)
        targets = [(dates[index], _trace(securities, cash=0.55)) for index in range(0, 300, 10)]
        summary = diagnose(targets, prices, horizons=(10,))["horizons"]["10"]
        gate = summary["gates"]["UNVERIFIED_ENTRY_BLOCKED"]
        self.assertEqual("hurt", gate["verdict"])
        self.assertEqual(30, gate["names_blocked"])
        self.assertEqual("exposure_effect", summary["largest_drag"]["component"])

    def test_overlapping_targets_are_not_counted_as_independent(self):
        rows = [{"start_date": DATES[index], "end_date": DATES[index + 5]} for index in range(20)]
        kept = non_overlapping(rows)
        self.assertEqual([DATES[0], DATES[5], DATES[10], DATES[15]], [row["start_date"] for row in kept])

    def test_too_few_independent_targets_is_not_a_verdict(self):
        rows = [{"start_date": DATES[index * 5], "end_date": DATES[index * 5 + 5], "is_approved": True,
                 "information": {"factor_ic": 0.5}, "gates": {},
                 "components": {name: -0.01 for name in ("universe_effect", "selection_effect", "sizing_effect",
                                                          "exposure_effect")}, "active_return": -0.04}
                for index in range(4)]
        self.assertEqual("insufficient", summarize(rows)["components"]["selection_effect"]["verdict"])


class StageTraceTest(unittest.TestCase):
    def test_trace_keeps_every_stage_value_and_marks_redundant_blocks(self):
        trace = stage_trace(
            alpha_detail={"A": {"factor_prior": 0.01, "ml_expected_excess_return": None, "ml_share": 0.0,
                                "expected_excess_return": 0.012, "confidence": 1.0, "thesis_state": "positive"},
                          "B": {"factor_prior": 0.005, "expected_excess_return": 0.005}},
            alpha_reasons={"A": "THESIS_CONFIRMED_TILT", "B": "FACTOR_BASE", "H": "NO_FACTOR_INPUT_HELD_FIXED"},
            current_weights={"CASH": 0.6, "A": 0.1, "H": 0.3}, proposed_weights={"CASH": 0.4, "A": 0.3, "H": 0.3},
            approved_weights={"CASH": 0.4, "A": 0.3, "H": 0.3}, is_approved=True, market_regime="NORMAL",
            min_cash_weight=0.05, redundant_blocked=("B",),
        )
        self.assertEqual({"A", "B", "H"}, set(trace["securities"]))
        self.assertEqual(0.012, trace["securities"]["A"]["alpha"])
        self.assertEqual("REDUNDANT_BLOCKED", trace["securities"]["B"]["reason"])
        self.assertIsNone(trace["securities"]["H"]["prior"])
        self.assertEqual({"before": 0.6, "proposed": 0.4, "approved": 0.4}, trace["cash"])


if __name__ == "__main__":
    unittest.main()
