"""토스 주문 상태를 immutable snapshot과 로컬 상태로 재동기화한다."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Protocol

from investment_agent.platform.serialization import canonical_json, parse_datetime
from investment_agent.execution.brokers.toss.client import from_toss_symbol
from investment_agent.execution.brokers.toss.orders import TossOrderApi, TossOrderSnapshot
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.orders.ledger import OrderAttemptEvent


class ReconciliationRepository(Protocol):
    def reconcilable_orders(self, *, account_seq: int) -> list[dict]: ...
    def order_attempt_events(self, attempt_id: str) -> list[OrderAttemptEvent]: ...
    def append_order_attempt_event(self, attempt_id: str, **kwargs): ...
    def update_order_execution(self, client_order_id: str, **kwargs) -> None: ...
    def save_broker_order_snapshot(self, row: dict) -> None: ...
    def intent_orders(self, intent_id: str) -> list[dict]: ...
    def update_intent_status(
        self,
        intent_id: str,
        status: str,
        failure_reason: str | None = None,
        *,
        expected_status: str | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class ReconciliationCardUpdate:
    """한 approval 카드에 되돌려 쓸 broker 관측 상태."""

    approval_id: str
    intent_id: str
    status: str


@dataclass(frozen=True)
class ReconciliationSummary:
    inspected: int
    updated: int
    unresolved_unknown: tuple[str, ...]
    external_open_order_ids: tuple[str, ...]
    completed_intents: tuple[str, ...]
    failed_intents: tuple[str, ...]
    card_updates: tuple[ReconciliationCardUpdate, ...]


def classify_remote_order(order: TossOrderSnapshot) -> str:
    """새 enum은 보존하되 누적 체결량과 명확한 종결 상태만 로컬 상태로 축약한다."""
    status = order.status.upper()
    if order.quantity > 0 and order.filled_quantity >= order.quantity:
        return "filled"
    if order.filled_quantity > 0:
        return "partially_filled"
    if "CANCEL" in status:
        return "cancelled"
    if "REJECT" in status:
        return "rejected"
    if "REPLAC" in status:
        return "replaced"
    return "submitted"


def _validate_identity(local: dict, remote: TossOrderSnapshot) -> None:
    symbol = from_toss_symbol(remote.symbol)
    if symbol != str(local["ticker"]).upper():
        raise ExecutionSafetyError("Toss reconciliation symbol mismatch")
    if remote.side.lower() != str(local["side"]).lower():
        raise ExecutionSafetyError("Toss reconciliation side mismatch")
    local_quantity = Decimal(str(local["quantity"]))
    if remote.quantity != local_quantity:
        raise ExecutionSafetyError("Toss reconciliation quantity mismatch")


def _snapshot_row(
    *,
    client_order_id: str,
    remote: TossOrderSnapshot,
    observed_at: datetime,
) -> dict:
    identity = {
        "client_order_id": client_order_id,
        "broker_order_id": remote.order_id,
        "broker_status": remote.status,
        "filled_quantity": str(remote.filled_quantity),
        "average_fill_price": (
            str(remote.average_filled_price)
            if remote.average_filled_price is not None else None
        ),
        "commission": str(remote.commission) if remote.commission is not None else None,
        "tax": str(remote.tax) if remote.tax is not None else None,
        "raw_snapshot": remote.raw,
    }
    return {
        "snapshot_hash": hashlib.sha256(
            canonical_json(identity).encode("utf-8")
        ).hexdigest(),
        **identity,
        "observed_at": parse_datetime(observed_at).isoformat(),
    }


class TossReconciliationWorker:
    """broker_order_id가 있는 주문만 자동 결합하고 나머지는 운영자 확인으로 남긴다."""

    def __init__(
        self,
        *,
        repository: ReconciliationRepository,
        api: TossOrderApi,
        account_seq: int,
        alert: Callable[[str, dict], None] | None = None,
    ) -> None:
        if account_seq <= 0:
            raise ValueError("account_seq must be positive")
        self.repository = repository
        self.api = api
        self.account_seq = account_seq
        self.alert = alert or (lambda event, details: None)

    def _open_remote_orders(self) -> tuple[TossOrderSnapshot, ...]:
        rows: list[TossOrderSnapshot] = []
        cursor: str | None = None
        for _ in range(20):
            page, cursor, has_next = self.api.list_orders(
                account_seq=self.account_seq,
                lifecycle="OPEN",
                cursor=cursor,
                limit=100,
            )
            rows.extend(page)
            if not has_next:
                return tuple(rows)
            if not cursor:
                raise ExecutionSafetyError("Toss order pagination omitted its next cursor")
        raise ExecutionSafetyError("Toss open order pagination exceeded the safety bound")

    def _event_status(
        self,
        *,
        attempt_id: str,
        local_status: str,
        remote_status: str,
        broker_order_id: str,
        raw_status: str,
        raw_response: dict,
        now: datetime,
    ) -> bool:
        events = self.repository.order_attempt_events(attempt_id)
        if not events:
            raise ExecutionSafetyError("order attempt has no immutable event history")
        last = events[-1].status
        changed = False
        if last == "outcome_unknown":
            value = self.repository.append_order_attempt_event(
                attempt_id,
                status="reconciling",
                broker_order_id=broker_order_id,
                raw_status=raw_status,
                raw_response=raw_response,
                occurred_at=now,
            )
            if value is None:
                raise ExecutionSafetyError("unknown outcome could not enter reconciliation")
            last = "reconciling"
            changed = True
        if last == "reconciling":
            reconciled = (
                "reconciled_rejected"
                if remote_status == "rejected" else "reconciled_submitted"
            )
            value = self.repository.append_order_attempt_event(
                attempt_id,
                status=reconciled,
                broker_order_id=broker_order_id,
                raw_status=raw_status,
                raw_response=raw_response,
                occurred_at=now,
            )
            if value is None:
                raise ExecutionSafetyError("reconciled outcome could not be recorded")
            last = reconciled
            changed = True
        target_event = {
            "partially_filled": "partially_filled",
            "filled": "filled",
            "cancelled": "cancelled",
            "rejected": "rejected",
            "replaced": "replacement_created",
        }.get(remote_status)
        if target_event and last != target_event:
            # reconciled_rejected 자체가 이미 종결 사건이다.
            if not (last == "reconciled_rejected" and target_event == "rejected"):
                value = self.repository.append_order_attempt_event(
                    attempt_id,
                    status=target_event,
                    broker_order_id=broker_order_id,
                    raw_status=raw_status,
                    raw_response=raw_response,
                    occurred_at=now,
                )
                if value is None:
                    raise ExecutionSafetyError("broker terminal state could not be recorded")
            changed = True
        return changed or remote_status != local_status

    def run_once(self, *, now: datetime | None = None) -> ReconciliationSummary:
        current = parse_datetime(now or datetime.now(timezone.utc))
        local = self.repository.reconcilable_orders(account_seq=self.account_seq)
        known_ids = {
            str(row["broker_order_id"])
            for row in local if row.get("broker_order_id")
        }
        remote_open = self._open_remote_orders()
        external = tuple(sorted(
            row.order_id for row in remote_open if row.order_id not in known_ids
        ))
        if external:
            self.alert("external_toss_open_orders", {"count": len(external)})

        unresolved: list[str] = []
        updated = 0
        touched_intents: set[str] = set()
        changed_intents: set[str] = set()
        for row in local:
            client_id = str(row["client_order_id"])
            attempt_id = str(row.get("attempt_id") or "")
            broker_id = str(row.get("broker_order_id") or "")
            if not attempt_id:
                raise ExecutionSafetyError("reconcilable order has no attempt_id")
            intent_id = str(row["intent_id"])
            touched_intents.add(intent_id)
            if not broker_id:
                events = self.repository.order_attempt_events(attempt_id)
                if events and events[-1].status == "outcome_unknown":
                    self.repository.append_order_attempt_event(
                        attempt_id,
                        status="reconciling",
                        raw_status="broker_order_id_missing",
                        raw_response={},
                        occurred_at=current,
                    )
                unresolved.append(client_id)
                changed_intents.add(intent_id)
                continue
            remote = self.api.get_order(
                account_seq=self.account_seq,
                order_id=broker_id,
            )
            if remote.order_id != broker_id:
                raise ExecutionSafetyError("Toss returned a different broker_order_id")
            _validate_identity(row, remote)
            local_status = str(row["status"])
            remote_status = classify_remote_order(remote)
            changed = self._event_status(
                attempt_id=attempt_id,
                local_status=local_status,
                remote_status=remote_status,
                broker_order_id=broker_id,
                raw_status=remote.status,
                raw_response=remote.raw,
                now=current,
            )
            self.repository.save_broker_order_snapshot(_snapshot_row(
                client_order_id=client_id,
                remote=remote,
                observed_at=current,
            ))
            self.repository.update_order_execution(
                client_id,
                status=remote_status,
                broker_order_id=broker_id,
                raw_broker_status=remote.status,
                raw_broker_response=remote.raw,
            )
            updated += int(changed)
            if changed:
                changed_intents.add(intent_id)

        completed: list[str] = []
        failed: list[str] = []
        card_updates: list[ReconciliationCardUpdate] = []
        for intent_id in sorted(touched_intents):
            orders = self.repository.intent_orders(intent_id)
            statuses = {str(row["status"]) for row in orders}
            approval_ids = {str(row.get("approval_id") or "") for row in orders}
            if "" in approval_ids or len(approval_ids) != 1:
                raise ExecutionSafetyError(
                    "intent orders do not have one exact approval_id"
                )
            if orders and statuses == {"filled"}:
                self.repository.update_intent_status(
                    intent_id,
                    "completed",
                    expected_status="executing",
                )
                completed.append(intent_id)
            elif statuses & {"cancelled", "rejected", "failed", "replaced"}:
                if not statuses & {
                    "planned", "submitted", "partially_filled", "outcome_unknown", "reconciling",
                }:
                    self.repository.update_intent_status(
                        intent_id,
                        "failed",
                        "broker_order_terminal_without_full_fill",
                        expected_status="executing",
                    )
                    failed.append(intent_id)
            if intent_id in changed_intents:
                if statuses & {"outcome_unknown", "reconciling"}:
                    card_status = "outcome_unknown"
                elif "partially_filled" in statuses:
                    card_status = "partially_filled"
                elif orders and statuses == {"filled"}:
                    card_status = "filled"
                elif statuses & {"rejected", "failed", "replaced"}:
                    card_status = "failed"
                elif "cancelled" in statuses:
                    card_status = "cancelled"
                else:
                    card_status = "submitted"
                card_updates.append(ReconciliationCardUpdate(
                    approval_id=next(iter(approval_ids)),
                    intent_id=intent_id,
                    status=card_status,
                ))
        if unresolved:
            self.alert("toss_order_outcome_unresolved", {"count": len(unresolved)})
        return ReconciliationSummary(
            inspected=len(local),
            updated=updated,
            unresolved_unknown=tuple(sorted(unresolved)),
            external_open_order_ids=external,
            completed_intents=tuple(completed),
            failed_intents=tuple(failed),
            card_updates=tuple(card_updates),
        )


__all__ = [
    "ReconciliationCardUpdate",
    "ReconciliationSummary",
    "TossReconciliationWorker",
    "classify_remote_order",
]
