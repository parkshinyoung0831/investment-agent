from __future__ import annotations

import unittest
from datetime import date, timedelta

from investment_agent.reporting.services.earnings import valuation_history


class EarningsValuationHistoryTest(unittest.TestCase):
    """역사적 밸류에이션 계산은 카드와 화면이 같은 분포를 주장해야 한다."""

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
