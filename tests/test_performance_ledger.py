"""체결·현금흐름 성과 계약의 오프라인 검증."""
import unittest

from investment_agent.trading.performance.ledger import account_fills, nav_returns


def fill(identity, side, quantity, price, day, **extra):
    return dict(fill_id=identity, ticker="AAPL", side=side, quantity=quantity,
                price=price, commission=0, tax=0, currency="USD",
                filled_at=f"2026-09-{day:02d}T16:00:00+00:00", **extra)


class FillAccountingTests(unittest.TestCase):
    def test_fifo_partial_fills_retry_and_fees(self):
        buy = fill("b", "buy", 10, 100, 1)
        buy["commission"] = 2
        sell = fill("s", "sell", 4, 110, 3)
        sell["commission"] = 1
        result = account_fills([buy, buy, fill("b2", "buy", 2, 105, 2), sell], marks={"AAPL": 120})
        self.assertAlmostEqual(result["realized_pnl"], 38.2)
        self.assertAlmostEqual(result["unrealized_pnl"], 148.8)
        self.assertEqual(result["fill_count"], 3)
        self.assertEqual(result["positions"][0]["quantity"], 8)

    def test_unknown_opening_basis_and_missing_fees_are_not_zero(self):
        sold = account_fills([fill("s", "sell", 3, 100, 2)])
        self.assertIsNone(sold["realized_pnl"])
        self.assertEqual(sold["realizations"][0]["unknown_quantity"], 3)
        buy = fill("b", "buy", 2, 100, 1)
        buy["commission"] = None
        result = account_fills([buy, fill("s", "sell", 2, 110, 2)])
        self.assertIsNone(result["realized_pnl"])
        self.assertEqual(result["realizations"][0]["gross_pnl"], 20)

    def test_opening_inventory_precedes_known_buys(self):
        result = account_fills([fill("b", "buy", 2, 90, 1), fill("s", "sell", 2, 110, 2)],
                               opening_positions=[dict(ticker="AAPL", quantity=3)])
        self.assertIsNone(result["realized_pnl"])
        self.assertEqual(result["positions"][0]["quantity"], 3)
        self.assertIsNone(result["unrealized_pnl"])

    def test_split_preserves_basis_dividend_is_separate_income(self):
        result = account_fills([fill("b", "buy", 2, 100, 1), fill("s", "sell", 2, 60, 3)],
            events=[dict(event_id="split", kind="split", ticker="AAPL", ratio=2,
                         occurred_at="2026-09-02T00:00:00+00:00"),
                    dict(event_id="div", kind="dividend", amount=3, currency="USD",
                         occurred_at="2026-09-04T00:00:00+00:00")], marks={"AAPL": 60})
        self.assertEqual(result["realized_pnl"], 20)
        self.assertEqual(result["unrealized_pnl"], 20)
        self.assertEqual(result["dividend_income"], 3)

    def test_conflicting_duplicate_and_mixed_currency_fail(self):
        a = fill("b", "buy", 2, 100, 1)
        with self.assertRaises(ValueError):
            account_fills([a, dict(a, quantity=3)])
        with self.assertRaises(ValueError):
            account_fills([dict(a, currency="KRW")])


class NavTests(unittest.TestCase):
    def snapshots(self):
        return [dict(captured_at="2026-09-01T00:00:00+00:00", equity=100, currency="USD"),
                dict(captured_at="2026-09-02T00:00:00+00:00", equity=165, currency="USD")]

    def test_endpoint_deposit_and_withdrawal(self):
        flows = [dict(event_id="deposit", kind="deposit", amount=50, currency="USD",
                      occurred_at=self.snapshots()[1]["captured_at"])]
        result = nav_returns(self.snapshots(), flows, is_cashflow_history_complete=True)
        self.assertAlmostEqual(result["cumulative_return"], .15)
        self.assertAlmostEqual(result["latest_period_return"], .15)

    def test_missing_cashflows_currency_and_intraday_valuation_are_unknown(self):
        self.assertIsNone(nav_returns(self.snapshots(), []) ["latest_period_return"])
        snapshots = self.snapshots()
        snapshots[0].pop("currency")
        self.assertIsNone(nav_returns(snapshots, [], is_cashflow_history_complete=True)["latest_period_return"])
        flows = [dict(event_id="d", kind="deposit", amount=50, currency="USD",
                      occurred_at="2026-09-01T12:00:00+00:00")]
        self.assertIsNone(nav_returns(self.snapshots(), flows, is_cashflow_history_complete=True)["latest_period_return"])

    def test_exact_subperiod_twr_and_no_future_flow(self):
        flows = [dict(event_id="d", kind="deposit", amount=50, currency="USD", nav_before=110, nav_after=160,
                      occurred_at="2026-09-01T12:00:00+00:00")]
        result = nav_returns(self.snapshots(), flows, is_cashflow_history_complete=True)
        self.assertAlmostEqual(result["cumulative_return"], 1.1 * 165 / 160 - 1)

    def test_same_endpoint_flows_are_net_adjusted_once(self):
        flows = [dict(event_id="d", kind="deposit", amount=60, currency="USD", occurred_at=self.snapshots()[1]["captured_at"]),
                 dict(event_id="w", kind="withdrawal", amount=10, currency="USD", occurred_at=self.snapshots()[1]["captured_at"])]
        self.assertAlmostEqual(nav_returns(self.snapshots(), flows, is_cashflow_history_complete=True)["latest_period_return"], .15)


if __name__ == "__main__":
    unittest.main()


class LatestPeriodNamingTest(unittest.TestCase):
    """키 이름이 값의 의미를 말해야 한다 — 스냅샷 간 수익률을 `daily_return`으로
    적으면 다음 소비자가 달력 하루로 읽고 그때 조용히 틀린다(감사 TR2-11)."""

    def test_latest_period_carries_its_own_window(self):
        from datetime import datetime, timedelta, timezone

        base = datetime(2026, 9, 18, 13, tzinfo=timezone.utc)
        snapshots = [
            {"captured_at": (base + timedelta(hours=offset)).isoformat(), "equity": equity, "currency": "USD"}
            for offset, equity in ((0, "100"), (3, "110"), (72, "121"))
        ]
        result = nav_returns(snapshots, [], is_cashflow_history_complete=True)
        self.assertNotIn("daily_return", result)
        self.assertAlmostEqual(result["latest_period_return"], 0.1)
        # 마지막 구간은 3시간이 아니라 69시간(주말 건너뜀)이고, 그 사실이 payload에 있다.
        self.assertEqual(result["latest_period_start_at"], snapshots[1]["captured_at"])
        self.assertEqual(result["latest_period_end_at"], snapshots[2]["captured_at"])
        self.assertEqual(result["return_method"], "time_weighted_subperiods")
