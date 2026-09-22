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
        self.fills = []
        self.intent_status = None
        self.reconciliation_runs = []
        self._next_reconciliation_id = 1

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
        return True

    def latest_broker_order_snapshot(self, client_order_id):
        matches = [row for row in self.snapshots if row["client_order_id"] == client_order_id]
        return max(matches, key=lambda row: row["observed_at"]) if matches else None

    def save_fill(self, row):
        self.fills.append(row)

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

    def begin_reconciliation_run(self, *, started_at=None):
        reconciliation_id = self._next_reconciliation_id
        self._next_reconciliation_id += 1
        self.reconciliation_runs.append({
            "reconciliation_id": reconciliation_id,
            "started_at": started_at,
            "status": "running",
            "finished_at": None,
            "payload": None,
        })
        return reconciliation_id

    def finish_reconciliation_run(self, reconciliation_id, *, status, payload, finished_at=None):
        run = next(item for item in self.reconciliation_runs if item["reconciliation_id"] == reconciliation_id)
        run["status"] = status
        run["finished_at"] = finished_at
        run["payload"] = payload


class FakeApi:
    def __init__(self, order=None, *, external=()):
        self.order = order
        self.external = tuple(external)

    def list_orders(self, **kwargs):
        return self.external, None, False

    def get_order(self, *, account_seq, order_id):
        return self.order


class ReconciliationWorkerTest(unittest.TestCase):
    def test_partial_fill_is_snapshotted_and_recorded_as_a_fill(self):
        """개별 체결 id는 없다(감사 EX2-10) — 누적 관측 두 개의 차이를 체결로 기록한다(감사 EX2-11)."""
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
        self.assertEqual(len(repo.fills), 1)
        fill = repo.fills[0]
        self.assertEqual(fill["client_order_id"], "client-1")
        self.assertEqual(fill["broker_order_id"], "broker-1")
        self.assertEqual(fill["quantity"], 1.0)
        self.assertEqual(fill["price"], 100.5)
        self.assertEqual(fill["commission"], 0.1)
        self.assertEqual(fill["tax"], 0.0)

    def test_run_once_records_a_reconciliation_run(self):
        """화면의 "대사 실행" 패널은 `reconciliation_runs`를 읽는다(감사 EX2-12) — run_once는 반드시 남긴다."""
        repo = FakeRepo()
        TossReconciliationWorker(
            repository=repo,
            api=FakeApi(remote(status="PARTIAL", filled="1")),
            account_seq=7,
        ).run_once(now=NOW)
        self.assertEqual(len(repo.reconciliation_runs), 1)
        run = repo.reconciliation_runs[0]
        self.assertEqual(run["status"], "ok")
        self.assertIsNotNone(run["finished_at"])
        self.assertEqual(run["payload"]["inspected"], 1)
        self.assertEqual(run["payload"]["updated"], 1)

    def test_run_once_records_a_failed_run_when_reconciliation_raises(self):
        repo = FakeRepo()
        worker = TossReconciliationWorker(
            repository=repo,
            api=FakeApi(remote(status="PARTIAL", filled="1", quantity="99")),
            account_seq=7,
        )
        with self.assertRaises(Exception):
            worker.run_once(now=NOW)
        self.assertEqual(len(repo.reconciliation_runs), 1)
        self.assertEqual(repo.reconciliation_runs[0]["status"], "failed")

    def test_a_second_partial_fill_records_only_the_new_quantity(self):
        """1주 체결 뒤 2주로 늘면 두 번째 체결 행은 증분 1주만 담는다 — 누적 2주를 다시 세지 않는다."""
        repo = FakeRepo()
        worker = TossReconciliationWorker(
            repository=repo, api=FakeApi(remote(status="PARTIAL", filled="1")), account_seq=7,
        )
        worker.run_once(now=NOW)
        worker.api = FakeApi(remote(status="FILLED", filled="2"))
        worker.run_once(now=NOW)
        self.assertEqual(len(repo.fills), 2)
        self.assertEqual(repo.fills[1]["quantity"], 1.0)
        self.assertEqual(repo.fills[1]["broker_fill_id"], "broker-1:2")

    def test_a_repeated_observation_with_no_new_quantity_does_not_duplicate_a_fill(self):
        repo = FakeRepo()
        worker = TossReconciliationWorker(
            repository=repo, api=FakeApi(remote(status="PARTIAL", filled="1")), account_seq=7,
        )
        worker.run_once(now=NOW)
        worker.run_once(now=NOW)
        self.assertEqual(len(repo.fills), 1)

    def test_cancellation_with_no_fill_quantity_does_not_invent_a_fill(self):
        repo = FakeRepo()
        TossReconciliationWorker(
            repository=repo, api=FakeApi(remote(status="CANCELED")), account_seq=7,
        ).run_once(now=NOW)
        self.assertEqual(repo.fills, [])

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

    def test_a_rejected_cancel_request_does_not_close_a_live_order(self):
        """취소가 거절된 주문은 브로커에 살아 있다 — 종결로 접으면 이후 체결이 대사되지 않는다."""
        self.assertEqual(classify_remote_order(remote(status="CANCEL_REJECTED")), "submitted")
        self.assertEqual(classify_remote_order(remote(status="cancel_rejected", filled="1")), "partially_filled")

    def test_plain_cancel_and_reject_remain_terminal(self):
        self.assertEqual(classify_remote_order(remote(status="CANCELED")), "cancelled")
        self.assertEqual(classify_remote_order(remote(status="REJECTED")), "rejected")


if __name__ == "__main__":
    unittest.main()
