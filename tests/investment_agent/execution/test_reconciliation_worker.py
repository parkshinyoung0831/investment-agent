from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from investment_agent.execution.brokers.toss.orders import TossOrderSnapshot
from investment_agent.execution.orders.ledger import OrderAttemptEvent
from investment_agent.execution.reconciliation.worker import (
    TossReconciliationWorker,
    classify_remote_order,
)

NOW = datetime(2026, 8, 24, 15, 5, tzinfo=timezone.utc)


def remote(*, status="PENDING", filled="0", quantity="2", order_id="broker-1"):
    value = {
        "orderId": order_id,
        "symbol": "AAPL",
        "side": "BUY",
        "orderType": "LIMIT",
        "timeInForce": "DAY",
        "status": status,
        "price": "101",
        "quantity": quantity,
        "currency": "USD",
        "orderedAt": "2026-08-24T11:00:00-04:00",
        "execution": {
            "filledQuantity": filled,
            "averageFilledPrice": "100.5" if Decimal(filled) > 0 else None,
            "commission": "0.1" if Decimal(filled) > 0 else None,
            "tax": "0",
        },
    }
    return TossOrderSnapshot.from_api(value)


def event(status: str) -> OrderAttemptEvent:
    return OrderAttemptEvent(
        event_id=1,
        attempt_id="attempt_" + "a" * 32,
        status=status,
        broker_order_id="broker-1" if status != "outcome_unknown" else None,
        raw_status=None,
        raw_response={},
        occurred_at=NOW.isoformat(),
    )


class FakeRepo:
    def __init__(self, *, unknown=False):
        self.row = {
            "client_order_id": "client-1",
            "attempt_id": "attempt_" + "a" * 32,
            "intent_id": "intent-1",
            "approval_id": "approval_" + "b" * 32,
            "broker_order_id": None if unknown else "broker-1",
            "ticker": "AAPL",
            "side": "buy",
            "quantity": 2,
            "status": "outcome_unknown" if unknown else "submitted",
        }
        self.events = [event("outcome_unknown" if unknown else "submitted")]
        self.snapshots = []
        self.intent_status = None

    def reconcilable_orders(self, *, account_seq):
        return [dict(self.row)]

    def order_attempt_events(self, attempt_id):
        return list(self.events)

    def append_order_attempt_event(self, attempt_id, **kwargs):
        item = OrderAttemptEvent(
            event_id=len(self.events) + 1,
            attempt_id=attempt_id,
            status=kwargs["status"],
            broker_order_id=kwargs.get("broker_order_id"),
            raw_status=kwargs.get("raw_status"),
            raw_response=kwargs.get("raw_response") or {},
            occurred_at=kwargs["occurred_at"].isoformat(),
        )
        self.events.append(item)
        return item

    def save_broker_order_snapshot(self, row):
        self.snapshots.append(row)

    def update_order_execution(self, client_order_id, **kwargs):
        self.row.update(kwargs)

    def intent_orders(self, intent_id):
        return [dict(self.row)]

    def update_intent_status(
        self,
        intent_id,
        status,
        failure_reason=None,
        *,
        expected_status=None,
    ):
        self.intent_status = status


class FakeApi:
    def __init__(self, order=None, *, external=()):
        self.order = order
        self.external = tuple(external)

    def list_orders(self, **kwargs):
        return self.external, None, False

    def get_order(self, *, account_seq, order_id):
        return self.order


class ReconciliationWorkerTest(unittest.TestCase):
    def test_partial_fill_is_snapshotted_without_inventing_fill_ids(self):
        repo = FakeRepo()
        result = TossReconciliationWorker(
            repository=repo,
            api=FakeApi(remote(status="PARTIAL", filled="1")),
            account_seq=7,
        ).run_once(now=NOW)
        self.assertEqual(result.updated, 1)
        self.assertEqual(repo.row["status"], "partially_filled")
        self.assertEqual(repo.events[-1].status, "partially_filled")
        self.assertEqual(len(repo.snapshots), 1)
        self.assertEqual(repo.snapshots[0]["filled_quantity"], "1")
        self.assertEqual(result.card_updates[0].status, "partially_filled")
        self.assertEqual(
            result.card_updates[0].approval_id,
            "approval_" + "b" * 32,
        )

    def test_full_fill_completes_intent(self):
        repo = FakeRepo()
        result = TossReconciliationWorker(
            repository=repo,
            api=FakeApi(remote(status="FILLED", filled="2")),
            account_seq=7,
        ).run_once(now=NOW)
        self.assertEqual(result.completed_intents, ("intent-1",))
        self.assertEqual(repo.intent_status, "completed")
        self.assertEqual(result.card_updates[0].status, "filled")

    def test_cancelled_order_updates_the_exact_card_as_cancelled(self):
        repo = FakeRepo()
        result = TossReconciliationWorker(
            repository=repo,
            api=FakeApi(remote(status="CANCELED")),
            account_seq=7,
        ).run_once(now=NOW)
        self.assertEqual(result.failed_intents, ("intent-1",))
        self.assertEqual(repo.intent_status, "failed")
        self.assertEqual(result.card_updates[0].status, "cancelled")

    def test_rejected_order_updates_the_exact_card_as_failed(self):
        repo = FakeRepo()
        result = TossReconciliationWorker(
            repository=repo,
            api=FakeApi(remote(status="REJECTED")),
            account_seq=7,
        ).run_once(now=NOW)
        self.assertEqual(result.failed_intents, ("intent-1",))
        self.assertEqual(result.card_updates[0].status, "failed")

    def test_unknown_without_broker_id_is_never_guessed_or_resent(self):
        repo = FakeRepo(unknown=True)
        alerts = []
        result = TossReconciliationWorker(
            repository=repo,
            api=FakeApi(),
            account_seq=7,
            alert=lambda event_name, details: alerts.append((event_name, details)),
        ).run_once(now=NOW)
        self.assertEqual(result.unresolved_unknown, ("client-1",))
        self.assertEqual(repo.events[-1].status, "reconciling")
        self.assertEqual(len(repo.snapshots), 0)
        self.assertEqual(alerts[-1][0], "toss_order_outcome_unresolved")
        self.assertEqual(result.card_updates[0].status, "outcome_unknown")

    def test_external_open_order_is_alerted_not_adopted(self):
        repo = FakeRepo()
        external = remote(order_id="outside-order")
        alerts = []
        result = TossReconciliationWorker(
            repository=repo,
            api=FakeApi(remote(), external=(external,)),
            account_seq=7,
            alert=lambda event_name, details: alerts.append((event_name, details)),
        ).run_once(now=NOW)
        self.assertEqual(result.external_open_order_ids, ("outside-order",))
        self.assertEqual(alerts[0], ("external_toss_open_orders", {"count": 1}))

    def test_unknown_broker_enum_remains_submitted(self):
        self.assertEqual(classify_remote_order(remote(status="FUTURE_STATE")), "submitted")


if __name__ == "__main__":
    unittest.main()
