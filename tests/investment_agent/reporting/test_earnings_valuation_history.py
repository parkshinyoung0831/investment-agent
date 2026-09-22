from __future__ import annotations

import unittest
from datetime import date, timedelta

from investment_agent.reporting.services.earnings import valuation_history


class EarningsValuationHistoryTest(unittest.TestCase):
    """역사적 밸류에이션 계산은 카드와 화면이 같은 분포를 주장해야 한다."""

    def test_a_quarter_with_no_net_debt_leaves_ev_ebitda_missing_not_cheap(self) -> None:
        """EV 가산분(순부채)을 그 분기에 계산할 수 없으면 EV/EBITDA도 결측이다(감사 RR2-11).

        0으로 접으면 EV가 시가총액과 같아져 실제보다 싼 배수가 통계에 들어간다.
        """
        prices = [("2026-01-02", 100.0), ("2026-04-06", 100.0)]
        shares = [("2026-01-02", 10.0), ("2026-04-06", 10.0)]
        snaps = [
            {"available_date": "2026-01-02", "ev_ex_market_cap": None, "ebitda_ttm": 50.0},
            {"available_date": "2026-04-06", "ev_ex_market_cap": 200.0, "ebitda_ttm": 50.0},
        ]
        dates, series = valuation_history.daily_series(prices, shares, snaps)
        self.assertEqual([None, 24.0], series["ev_ebitda"])

    def test_window_stats_needs_a_current_value(self) -> None:
        today = date(2026, 9, 4)
        dates = [(today - timedelta(days=i)).isoformat() for i in range(400, 0, -1)]
        self.assertIsNone(valuation_history.window_stats(dates, [None] * 400, today))
        self.assertIsNone(valuation_history.window_stats([], [], today))
        # 마지막 값이 비면 '현재'가 없어 통계를 내지 않는다.
        self.assertIsNone(valuation_history.window_stats(dates, [1.0] * 399 + [None], today))

    def test_window_stats_reports_the_current_percentile_within_the_window(self) -> None:
        today = date(2026, 9, 4)
        dates = [(today - timedelta(days=i)).isoformat() for i in range(300, 0, -1)]
        vals: list[float | None] = [float(i) for i in range(1, 301)]
        stats = valuation_history.window_stats(dates, vals, today)
        assert stats is not None
        one_year = stats[1]
        self.assertEqual(300.0, one_year["current"])
        self.assertEqual(300, one_year["n"])
        self.assertEqual(100, one_year["percentile"])  # 현재값이 최고치
        self.assertAlmostEqual(150.5, one_year["median"])
        # 이력이 1년치뿐이면 더 긴 지평도 같은 표본을 본다 — 없는 과거를 만들지 않는다.
        self.assertEqual({1, 3, 5, 7}, set(stats))
        self.assertEqual([300] * 4, [stats[y]["n"] for y in (1, 3, 5, 7)])

    def test_windows_without_enough_points_are_dropped(self) -> None:
        today = date(2026, 9, 4)
        dates = [(today - timedelta(days=i)).isoformat() for i in (2, 1)]
        # 관측이 최소 개수에 못 미치면 그 지평은 통계를 내지 않는다.
        self.assertIsNone(valuation_history.window_stats(dates, [1.0, 2.0], today))

    def test_downsample_weekly_keeps_the_last_valid_point_of_each_bucket(self) -> None:
        dates = ["2026-08-01", "2026-08-02", "2026-08-09", "2026-08-10"]
        vals: list[float | None] = [1.0, 2.0, None, 4.0]
        self.assertEqual(
            [("2026-08-02", 2.0), ("2026-08-10", 4.0)],
            valuation_history.downsample_weekly(dates, vals),
        )
