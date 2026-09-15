"""보유수량 대사: 우리 체결로 설명되지 않는 변화와 외부 미체결은 신규 주문을 막는다."""
from __future__ import annotations

import unittest

from investment_agent.execution.reconciliation.positions import (
    OrderFill,
    PositionBaseline,
    reconcile_positions,
)
from investment_agent.execution.reconciliation.worker import TossReconciliationWorker
from tests.investment_agent.execution.test_reconciliation_worker import NOW, FakeApi, FakeRepo, remote

T0 = "2026-08-24T15:00:00+00:00"


class ReconcilePositionsTest(unittest.TestCase):
    def test_first_observation_becomes_the_baseline_without_mismatch(self):
        result = reconcile_positions(None, broker_positions={"AAPL": 3}, order_fills={}, observed_at=T0)
        self.assertTrue(result.is_first_observation)
        self.assertEqual(result.next_baseline.positions, {"AAPL": 3.0})

    def test_our_own_fill_explains_the_change(self):
        baseline = PositionBaseline(T0, {"AAPL": 3.0}, {"c1": 0.0})
        result = reconcile_positions(baseline, broker_positions={"AAPL": 5}, observed_at=T0,
                                     order_fills={"c1": OrderFill("AAPL", "buy", 2.0)})
        self.assertEqual(result.mismatches, ())

    def test_sell_fill_reduces_expected_quantity(self):
        baseline = PositionBaseline(T0, {"AAPL": 3.0}, {})
        result = reconcile_positions(baseline, broker_positions={"AAPL": 1}, observed_at=T0,
                                     order_fills={"c1": OrderFill("AAPL", "sell", 2.0)})
        self.assertEqual(result.mismatches, ())

    def test_manual_app_trade_is_an_unexplained_change(self):
        baseline = PositionBaseline(T0, {"AAPL": 3.0}, {})
        result = reconcile_positions(baseline, broker_positions={"AAPL": 3, "MSFT": 1}, order_fills={}, observed_at=T0)
        self.assertEqual([item.ticker for item in result.mismatches], ["MSFT"])
        self.assertEqual(result.next_baseline.positions, {"AAPL": 3.0, "MSFT": 1.0})

    def test_fill_counted_once_even_after_the_order_leaves_the_lookup_window(self):
        baseline = PositionBaseline(T0, {"AAPL": 5.0}, {"c1": 2.0})
        first = reconcile_positions(baseline, broker_positions={"AAPL": 5}, order_fills={}, observed_at=T0)
        self.assertEqual(first.mismatches, ())
        again = reconcile_positions(first.next_baseline, broker_positions={"AAPL": 5}, observed_at=T0,
                                    order_fills={"c1": OrderFill("AAPL", "buy", 2.0)})
        self.assertEqual(again.mismatches, ())

    def test_decreasing_cumulative_fill_is_rejected(self):
        baseline = PositionBaseline(T0, {"AAPL": 5.0}, {"c1": 2.0})
        with self.assertRaises(ValueError):
            reconcile_positions(baseline, broker_positions={"AAPL": 4}, observed_at=T0,
                                order_fills={"c1": OrderFill("AAPL", "buy", 1.0)})


class _BaselineRepo(FakeRepo):
    def __init__(self, baseline=None, **kwargs):
        super().__init__(**kwargs)
        self.baseline = baseline

    def load_position_baseline(self, *, account_seq):
        return self.baseline

    def save_position_baseline(self, *, account_seq, baseline):
        self.baseline = baseline


class WorkerPositionTest(unittest.TestCase):
    def _worker(self, repo, api, positions):
        breaches = []
        worker = TossReconciliationWorker(
            repository=repo, api=api, account_seq=7,
            positions_provider=lambda: positions, baseline_store=repo,
            on_breach=lambda event, details: breaches.append(event),
        )
        return worker, breaches

    def test_filled_order_matching_the_new_holding_is_ok(self):
        repo = _BaselineRepo(PositionBaseline(T0, {}, {"client-1": 0.0}).to_dict())
        worker, breaches = self._worker(repo, FakeApi(remote(status="FILLED", filled="2")), {"AAPL": 2})
        result = worker.run_once(now=NOW)
        self.assertEqual(result.position_check, "ok")
        self.assertEqual(breaches, [])

    def test_holding_not_explained_by_fills_locks_down(self):
        repo = _BaselineRepo(PositionBaseline(T0, {}, {"client-1": 0.0}).to_dict())
        worker, breaches = self._worker(repo, FakeApi(remote(status="FILLED", filled="2")), {"AAPL": 7})
        result = worker.run_once(now=NOW)
        self.assertEqual(result.position_check, "mismatch")
        self.assertEqual(breaches, ["unexplained_position_change"])

    def test_external_open_order_locks_down(self):
        repo = _BaselineRepo(PositionBaseline(T0, {}, {}).to_dict())
        api = FakeApi(remote(), external=(remote(order_id="app-order"),))
        worker, breaches = self._worker(repo, api, {})
        worker.run_once(now=NOW)
        self.assertIn("external_toss_open_orders", breaches)

    def test_unknown_outcome_defers_without_moving_the_baseline(self):
        original = PositionBaseline(T0, {}, {}).to_dict()
        repo = _BaselineRepo(original, unknown=True)
        worker, breaches = self._worker(repo, FakeApi(), {"AAPL": 2})
        result = worker.run_once(now=NOW)
        self.assertEqual(result.position_check, "deferred")
        self.assertEqual(repo.baseline, original)
        self.assertEqual(breaches, [])

    def test_provider_and_store_must_be_configured_together(self):
        with self.assertRaises(ValueError):
            TossReconciliationWorker(repository=FakeRepo(), api=FakeApi(), account_seq=7,
                                     positions_provider=lambda: {})


if __name__ == "__main__":
    unittest.main()
