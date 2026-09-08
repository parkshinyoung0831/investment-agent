"""TCARecorder 단위 테스트."""
from __future__ import annotations

import unittest

from investment_agent.execution.orders.tca_recorder import TCARecorder


class TCARecorderTests(unittest.TestCase):
    def test_record_fill_computes_slippage_bps(self) -> None:
        # 매수 시: 의도 $100.0 -> 체결 $100.10 (+10 bps 슬리피지 비용 발생)
        report = TCARecorder.record_fill(
            ticker="NVDA",
            side="buy",
            decision_price=100.0,
            fill_price=100.10,
            quantity=50.0,
            arrival_price=100.05,
            bid=100.0,
            ask=100.10,
            fees=1.0,
        )
        self.assertEqual(report.ticker, "NVDA")
        self.assertAlmostEqual(report.fill_price, 100.10)
        self.assertEqual(report.metadata["slippage_bps"], 10.0)
        self.assertEqual(report.metadata["cost_quality"], "acceptable")

    def test_favorable_sell_slippage(self) -> None:
        # 매도 시: 의도 $200.0 -> 체결 $200.20 (-10 bps 유리한 체결)
        report = TCARecorder.record_fill(
            ticker="TSLA",
            side="sell",
            decision_price=200.0,
            fill_price=200.20,
            quantity=10.0,
        )
        self.assertLess(report.metadata["slippage_bps"], 0.0)
        self.assertEqual(report.metadata["cost_quality"], "favorable")


if __name__ == "__main__":
    unittest.main()
