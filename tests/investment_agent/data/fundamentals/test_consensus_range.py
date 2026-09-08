"""추정 구간이 뒤집혀 오면 구간만 버리고 평균은 남긴다.

yfinance가 `low > high`인 구간을 준다(실측: eps_low 1.24 > eps_high 1.15).
저장소의 `estimates_range_check`가 그것을 거절하는데, upsert는 묶음으로 가므로
**그 한 행이 그 종목 묶음 전체를 실패시킨다** — 실제로 `refresh_expectations`가
그렇게 죽었다.

뒤집힌 구간은 어느 쪽이 맞는지 알 수 없다. 조용히 뒤집어 담으면 "애널리스트 전망
범위"가 우리가 지어낸 값이 되므로, 버리고 평균만 남긴다.
"""
from __future__ import annotations

import unittest

from investment_agent.data.fundamentals.domain.services.map_fiscal_periods import (
    _coherent_range,
)


class CoherentRangeTest(unittest.TestCase):
    def test_a_sane_range_passes_through(self) -> None:
        self.assertEqual({"eps_low": 1.0, "eps_high": 1.5}, _coherent_range("eps", 1.0, 1.5))

    def test_equal_bounds_are_a_valid_range(self) -> None:
        self.assertEqual({"eps_low": 1.2, "eps_high": 1.2}, _coherent_range("eps", 1.2, 1.2))

    def test_an_inverted_range_is_dropped(self) -> None:
        self.assertEqual({"eps_low": None, "eps_high": None},
                         _coherent_range("eps", 1.24, 1.15))

    def test_one_sided_bounds_survive(self) -> None:
        """한쪽만 있는 구간은 저장소가 받는다 — 버릴 이유가 없다."""
        self.assertEqual({"revenue_low": None, "revenue_high": 1.15},
                         _coherent_range("revenue", None, 1.15))

    def test_unreadable_values_are_dropped_not_raised(self) -> None:
        """원천 한 칸이 이상하다고 그 종목 전체를 잃지 않는다."""
        self.assertEqual({"eps_low": None, "eps_high": None},
                         _coherent_range("eps", "x", 1.15))


if __name__ == "__main__":
    unittest.main()
