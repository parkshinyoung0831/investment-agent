"""factor IC 연구: 순위 상관·기간 날짜·겹침 보정·가중치 제안·세대 분리."""
from __future__ import annotations

import unittest
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from investment_agent.research.commands import factor_research

from investment_agent.research.commands.factor_research import (
    IcSummary,
    MIN_CROSS_SECTION,
    forward_returns,
    group_snapshots,
    horizon_dates,
    overlap_factor,
    quantile_spread,
    research,
    spearman,
    suggest_category_weights,
    summarize,
)


def _weekdays(start: date, count: int) -> list[date]:
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


class SpearmanTest(unittest.TestCase):
    def test_perfect_and_inverse_order(self):
        values = {f"T{i}": float(i) for i in range(MIN_CROSS_SECTION)}
        self.assertAlmostEqual(spearman(values, {k: v * 3 for k, v in values.items()})[0], 1.0)
        self.assertAlmostEqual(spearman(values, {k: -v for k, v in values.items()})[0], -1.0)

    def test_too_few_names_gives_no_ic(self):
        values = {f"T{i}": float(i) for i in range(MIN_CROSS_SECTION - 1)}
        self.assertIsNone(spearman(values, values)[0])

    def test_constant_side_gives_no_ic(self):
        values = {f"T{i}": float(i) for i in range(MIN_CROSS_SECTION)}
        self.assertIsNone(spearman(values, {k: 1.0 for k in values})[0])


class ForwardWindowTest(unittest.TestCase):
    def test_start_is_the_last_session_on_or_before_as_of(self):
        calendar = _weekdays(date(2024, 1, 1), 30)
        saturday = date(2024, 1, 6)
        start, ends = horizon_dates(calendar, saturday, (1, 5, 100))
        self.assertEqual(start, date(2024, 1, 5))
        self.assertEqual(ends[1], date(2024, 1, 8))
        self.assertEqual(ends[5], date(2024, 1, 12))
        self.assertNotIn(100, ends)  # 달력 밖 기간은 만들지 않는다

    def test_missing_end_close_and_broken_ratio_are_excluded(self):
        returns, rejected = forward_returns({"A": 10.0, "B": 10.0, "C": 10.0}, {"A": 11.0, "C": 100.0})
        self.assertEqual(returns, {"A": 0.10000000000000009})
        self.assertEqual(rejected, 1)


class SummaryTest(unittest.TestCase):
    def test_overlap_shrinks_t(self):
        self.assertEqual(overlap_factor(20, 56), 1.0)
        self.assertGreater(overlap_factor(126, 56), 3.0)
        plain = summarize([0.05, 0.07, 0.06, 0.04], [], overlap_factor=1.0)
        overlapped = summarize([0.05, 0.07, 0.06, 0.04], [], overlap_factor=4.0)
        self.assertAlmostEqual(overlapped.t_stat_overlap_adjusted, plain.t_stat_overlap_adjusted / 2)

    def test_weights_are_suggested_only_for_significant_positive_categories(self):
        strong = IcSummary(0.06, 0.02, 6.0, 3.0, 0.9, 20, 0.02)
        weak = IcSummary(0.04, 0.10, 1.0, 0.5, 0.6, 20, 0.01)
        negative = IcSummary(-0.05, 0.02, -5.0, -2.5, 0.1, 20, -0.02)
        result = suggest_category_weights({"quality": strong, "value": weak, "momentum": negative})
        self.assertEqual(result["weights"]["quality"], 1.0)
        self.assertEqual(result["weights"]["value"], 0.0)
        self.assertEqual(result["weights"]["momentum"], 0.0)

    def test_nothing_significant_keeps_equal_weight(self):
        weak = IcSummary(0.04, 0.10, 1.0, 0.5, 0.6, 20, 0.01)
        result = suggest_category_weights({"quality": weak})
        self.assertEqual(result["basis"], "equal_weight_kept")

    def test_quantile_spread_is_top_minus_bottom(self):
        signal = {f"T{i}": float(i) for i in range(50)}
        returns = {f"T{i}": i / 100 for i in range(50)}
        # 상위 10종목(40~49) 평균 0.445 − 하위 10종목(0~9) 평균 0.045
        self.assertAlmostEqual(quantile_spread(signal, returns), 0.40)


class ResearchTest(unittest.TestCase):
    def test_predictive_momentum_gets_positive_ic_and_reversed_value_negative(self):
        calendar = _weekdays(date(2024, 1, 1), 200)
        as_of_dates = [calendar[0], calendar[40], calendar[80]]
        names = [f"T{i:02d}" for i in range(60)]
        snapshots = {}
        for day in as_of_dates:
            snapshots[day] = {
                name: {"momentum_12_1": i / 60, "momentum_6_1": i / 120,
                       "valuation_earnings_yield": i / 600, "valuation_fcf_yield": i / 600,
                       "quality_roe_ttm": 0.2, "quality_roa_ttm": 0.1, "quality_gross_margin_ttm": 0.4}
                for i, name in enumerate(names)
            }
        start_by_day = {day: {name: 100.0 for name in names} for day in calendar}

        def closes_on(tickers, day):
            index = calendar.index(day)
            # 판단 뒤로 갈수록 번호가 큰 종목(모멘텀·이익수익률 높음)이 더 오른다.
            return {name: 100.0 * (1 + 0.001 * i * min(index, 150) / 10) for i, name in enumerate(names)
                    if name in tickers} if index else start_by_day[day]

        report = research(snapshots_by_date=snapshots, calendar=calendar, closes_on=closes_on, horizons=(20,))
        momentum = report["summary"]["category:momentum"]["20"]
        self.assertGreater(momentum["mean_ic"], 0.9)
        self.assertEqual(report["best_horizon_by_signal"]["category:momentum"], "20")
        self.assertEqual(report["n_dates"], 3)
        self.assertTrue(all(row["status"] == "measured" for row in report["per_date"]))

    def test_dates_without_forward_prices_are_reported_not_scored(self):
        calendar = _weekdays(date(2024, 1, 1), 10)
        snapshots = {calendar[-1]: {"A": {"momentum_12_1": 0.1, "momentum_6_1": 0.1}}}
        report = research(snapshots_by_date=snapshots, calendar=calendar, closes_on=lambda t, d: {}, horizons=(20,))
        self.assertEqual(report["per_date"][0]["status"], "no_forward_window")
        self.assertEqual(report["summary"], {})


class SignalDirectionTest(unittest.TestCase):
    def test_lower_is_better_factors_are_flipped_so_positive_ic_means_useful(self):
        from investment_agent.research.commands.factor_research import signal_values
        from investment_agent.research.features.factors import FactorModel
        signals = signal_values({"A": {"quality_accruals_ttm": 0.2}, "B": {"quality_accruals_ttm": -0.1}},
                                groups=None, model=FactorModel())
        self.assertEqual(signals["factor:quality_accruals_ttm"], {"A": -0.2, "B": 0.1})


class GroupSnapshotsTest(unittest.TestCase):
    def test_unavailable_rows_are_dropped(self):
        rows = [
            {"as_of_at": "2024-01-05T23:30:00+00:00", "ticker": "aapl", "features": {"x": 1}},
            {"as_of_at": "2024-01-05T23:30:00+00:00", "ticker": "GOOG", "features": {},
             "is_available": False},
        ]
        self.assertEqual(group_snapshots(rows), {date(2024, 1, 5): {"AAPL": {"x": 1}}})


class FactorResearchMainDataOwnerTest(unittest.TestCase):
    def test_cli_composes_market_and_universe_owner_reads(self):
        rows = [{
            "as_of_at": "2024-01-05T23:30:00+00:00",
            "ticker": "AAPL",
            "features": {"momentum_12_1": 0.1},
            "provenance": {"source_kind": "historical_replay"},
        }]
        report = {"n_dates": 1, "best_horizon_by_signal": {}, "summary": {}, "per_date": []}
        with tempfile.TemporaryDirectory() as temp:
            with (
                patch("investment_agent.research.storage.repository.ResearchStore") as store_type,
                patch.object(
                    factor_research.market_data,
                    "trading_dates",
                    return_value=[date(2024, 1, 5)],
                ) as dates,
                patch.object(factor_research.market_data, "closes_on_date") as closes,
                patch.object(
                    factor_research.universe_data,
                    "select_sp500_sector_map",
                    return_value={"AAPL": "Manufacturing"},
                ) as sectors,
                patch.object(factor_research, "research", return_value=report) as calculate,
            ):
                store_type.return_value.records.return_value = rows

                exit_code = factor_research.main(["--output-dir", temp])
                self.assertTrue((Path(temp) / "latest.json").exists())

        self.assertEqual(0, exit_code)
        dates.assert_called_once()
        sectors.assert_called_once_with(["AAPL"])
        kwargs = calculate.call_args.kwargs
        self.assertIs(closes, kwargs["closes_on"])
        self.assertEqual({"AAPL": "Manufacturing"}, kwargs["groups"])


if __name__ == "__main__":
    unittest.main()
