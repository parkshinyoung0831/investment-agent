"""TWAPOrderSlicer 단위 테스트."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from investment_agent.execution.orders.twap import TWAPOrderSlicer, TWAPSlice


class TWAPTests(unittest.TestCase):
    def test_slice_order_conserves_total_quantity(self) -> None:
        slicer = TWAPOrderSlicer(default_slices=4, default_duration_minutes=60)
        start = datetime(2026, 9, 3, 14, 30, tzinfo=timezone.utc)
        slices = slicer.slice_order(
            ticker="AAPL",
            side="buy",
            total_quantity=100.0,
            start_time=start,
            num_slices=4,
            duration_minutes=60,
        )

        self.assertEqual(len(slices), 4)
        total_sliced = sum(s.quantity for s in slices)
        self.assertAlmostEqual(total_sliced, 100.0, places=4)
        self.assertEqual(slices[0].scheduled_at, start)
        self.assertEqual(slices[1].scheduled_at, start + datetime.resolution * 0 + (datetime(2026, 9, 3, 14, 50, tzinfo=timezone.utc) - start))

    def test_small_order_does_not_over_slice(self) -> None:
        slicer = TWAPOrderSlicer(min_slice_quantity=5.0)
        start = datetime(2026, 9, 3, 14, 30, tzinfo=timezone.utc)
        slices = slicer.slice_order(
            ticker="MSFT",
            side="sell",
            total_quantity=8.0,  # 8개는 min 5개이므로 1개 슬라이스만 나와야 함
            start_time=start,
            num_slices=4,
        )
        self.assertEqual(len(slices), 1)
        self.assertEqual(slices[0].quantity, 8.0)


if __name__ == "__main__":
    unittest.main()
