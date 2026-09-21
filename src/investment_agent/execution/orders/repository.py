"""Execution lifecycle owner persistence methods."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from investment_agent.execution.db import RECORD_SYSTEM_TARGET_EXECUTION, T_PORTFOLIO_PROPOSALS, _approval, _intent, _order_attempt, _same_planned_value, funding_followup_allowed
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.orders.intents import ExecutionIntent
from investment_agent.execution.orders.ledger import OrderAttempt, OrderAttemptEvent, OrderAttemptReservation
from investment_agent.execution.orders.toss_manual import TossManualHandoff
from investment_agent.platform.db.sqlite import runtime_connection
from investment_agent.platform.serialization import parse_datetime


class OrderRepository:
    def save_intent(self, row: dict) -> None:
        payload = _intent(dict(row)).as_row()
        now = datetime.now(timezone.utc).isoformat()
        with runtime_connection() as connection:
            old = connection.execute("SELECT payload_json FROM intents WHERE intent_id=?", (payload["intent_id"],)).fetchone()
            if old:
                saved = _intent(self._decode(old[0])).as_row()
                if any(saved[key] != value for key, value in payload.items() if key != "status"):
                    raise ExecutionSafetyError("intent identity conflicts with stored intent")
                return
            if payload['execution_mode'] == 'live':
                proposal = self._decision_row(connection, T_PORTFOLIO_PROPOSALS, 'proposal_id', payload['proposal_id'])
                target_id = (proposal or {}).get('metadata', {}).get('system_target_id')
                if target_id:
                    claim = self._record(connection, RECORD_SYSTEM_TARGET_EXECUTION, str(target_id))
                    followup = funding_followup_allowed(connection, claim)
                    if claim and not followup:
                        previous = connection.execute(
                            "SELECT i.status,i.expires_at,a.status,"
                            "EXISTS(SELECT 1 FROM order_attempts o WHERE o.intent_id=i.intent_id AND o.state != 'failed'),"
                            "EXISTS(SELECT 1 FROM orders o WHERE o.intent_id=i.intent_id) "
                            "FROM intents i LEFT JOIN approvals a ON a.intent_id=i.intent_id WHERE i.intent_id=?",
                            (claim['intent_id'],)).fetchone()
                        if previous and (previous[3] or previous[4] or previous[0] in ('executing','completed') or previous[2] == 'consumed'
                            or (previous[0] in ('approved','claimed') and previous[2] not in ('rejected','expired') and parse_datetime(previous[1]) > parse_datetime(now))):
                            raise ExecutionSafetyError('System target already has an active execution')
                    record = {'intent_id': payload['intent_id']}
                    if followup:
                        record.update(
                            funding_followups=int(claim.get('funding_followups') or 0) + 1,
                            previous_intent_ids=[*claim.get('previous_intent_ids', ()), claim['intent_id']],
                        )
                    self._save_record(connection, RECORD_SYSTEM_TARGET_EXECUTION, str(target_id), record)
            connection.execute(
                "INSERT INTO intents(intent_id,proposal_id,risk_decision_id,execution_mode,status,not_before,expires_at,payload_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(intent_id) DO NOTHING",
                (payload["intent_id"], payload["proposal_id"], payload["risk_decision_id"],
                 payload["execution_mode"], payload["status"], payload["not_before"],
                 payload["expires_at"], self._encode(payload), now, now),
            )
            if payload["execution_mode"] == "live":
                self._supersede_pending_live_intents(connection, new_intent_id=payload["intent_id"], now=now)
    def _supersede_pending_live_intents(cls, connection, *, new_intent_id: str, now: str) -> list[str]:
        """새 live 판단이 생기면, 아직 주문이 하나도 나가지 않은 이전 승인 대기 intent를 닫는다.

        만료와 다르다 — 시간이 지나서가 아니라 더 새로운 판단이 대체했기 때문이다. 옛 카드를
        뒤늦게 승인해도 worker가 승인을 소비하기 전에 멈추도록 `cancelled`로 두고, 무엇이
        대체했는지 `superseded_by`에 남긴다. 주문이 이미 나간 intent는 건드리지 않는다 —
        미체결 주문 취소는 운영자 승인이 필요한 별도 동작이고, 미체결이 있는 동안에는 새
        포트폴리오 구성 자체가 막힌다.
        """
        rows = connection.execute(
            "SELECT i.intent_id,i.payload_json FROM intents i WHERE i.execution_mode='live' "
            "AND i.status='approved' AND i.intent_id != ? "
            "AND NOT EXISTS(SELECT 1 FROM orders o WHERE o.intent_id=i.intent_id) "
            "AND NOT EXISTS(SELECT 1 FROM order_attempts a WHERE a.intent_id=i.intent_id)",
            (new_intent_id,),
        ).fetchall()
        superseded: list[str] = []
        for intent_id, raw in rows:
            payload = cls._decode(raw)
            payload.update(
                status="cancelled",
                failure_reason=f"superseded_by:{new_intent_id}",
                superseded_by=new_intent_id,
                superseded_at=now,
            )
            connection.execute(
                "UPDATE intents SET status='cancelled',payload_json=?,updated_at=? WHERE intent_id=? AND status='approved'",
                (cls._encode(payload), now, intent_id),
            )
            superseded.append(str(intent_id))
        return superseded
    def save_handoff(self, handoff: TossManualHandoff) -> None:
        handoff.validate_manifest()
        payload = handoff.to_dict()
        if "account_seq" in payload:
            raise ExecutionSafetyError("Toss handoff payload must not expose account_seq")
        with runtime_connection() as connection:
            connection.execute(
                "INSERT INTO order_manifests(manifest_hash,intent_id,account_seq,payload_json,captured_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(manifest_hash) DO NOTHING",
                (handoff.manifest_hash, handoff.intent_id, handoff.account_seq,
                 self._encode(payload), handoff.snapshot.captured_at),
            )
    def load_handoff(self, manifest_hash: str) -> TossManualHandoff | None:
        with runtime_connection(read_only=True) as connection:
            row = connection.execute(
                "SELECT account_seq,payload_json FROM order_manifests WHERE manifest_hash = ?", (manifest_hash,)
            ).fetchone()
        if row is None:
            return None
        payload = self._decode(row[1])
        if str(payload.get("manifest_hash") or "") != manifest_hash:
            raise ExecutionSafetyError("stored Toss handoff hash is inconsistent")
        return TossManualHandoff.from_private_dict(payload, account_seq=int(row[0]))
    def reserve_order_attempt(self, attempt: OrderAttempt) -> OrderAttemptReservation | None:
        payload = attempt.as_row()
        with runtime_connection() as connection:
            old = connection.execute("SELECT payload_json FROM order_attempts WHERE attempt_id=? OR client_order_id=?", (attempt.attempt_id, attempt.client_order_id)).fetchone()
            if old:
                existing = _order_attempt(self._decode(old[0]))
                matches = all(value == existing.as_row()[key] for key, value in payload.items() if key != "reserved_at")
                return OrderAttemptReservation(attempt=existing, reserved_new=False) if matches else None
            approval = connection.execute("SELECT status,payload_json FROM approvals WHERE approval_id=?", (attempt.approval_id,)).fetchone()
            if approval is None or approval[0] != "consumed":
                return None
            approved = _approval(self._decode(approval[1]))
            if (
                approved.execution_mode != "live"
                or approved.intent_id != attempt.intent_id
                or approved.manifest_hash != attempt.manifest_hash
                or approved.account_seq != attempt.account_seq
                or attempt.client_order_id not in approved.allowed_client_order_ids
            ):
                return None
            connection.execute("INSERT INTO order_attempts(attempt_id,client_order_id,intent_id,approval_id,state,payload_json,reserved_at) VALUES(?,?,?,?,?,?,?)", (attempt.attempt_id, attempt.client_order_id, attempt.intent_id, attempt.approval_id, "reserved", self._encode(payload), attempt.reserved_at.isoformat()))
        return OrderAttemptReservation(attempt=attempt, reserved_new=True)
    def append_order_attempt_event(self, attempt_id: str, *, status: str, broker_order_id: str | None = None, raw_status: str | None = None, raw_response: dict | None = None, occurred_at: datetime | None = None) -> OrderAttemptEvent | None:
        moment = occurred_at or datetime.now(timezone.utc)
        event = OrderAttemptEvent(event_id=1, attempt_id=attempt_id, status=status, broker_order_id=broker_order_id, raw_status=raw_status, raw_response=dict(raw_response or {}), occurred_at=moment)
        transitions = {
            "reserved": {"submitting", "failed"},
            "submitting": {"submitted", "rejected", "outcome_unknown", "failed"},
            "outcome_unknown": {"reconciling"},
            "reconciling": {"reconciled_submitted", "reconciled_rejected", "outcome_unknown", "failed"},
            "submitted": {"partially_filled", "filled", "cancelled", "rejected", "replacement_created"},
            "reconciled_submitted": {"partially_filled", "filled", "cancelled", "rejected", "replacement_created"},
            "partially_filled": {"filled", "cancelled", "rejected", "replacement_created"},
        }
        with runtime_connection() as connection:
            if connection.execute("SELECT 1 FROM order_attempts WHERE attempt_id=?", (attempt_id,)).fetchone() is None:
                return None
            previous = connection.execute("SELECT event_type,occurred_at FROM order_events WHERE attempt_id=? ORDER BY event_id DESC LIMIT 1", (attempt_id,)).fetchone()
            current = previous[0] if previous else "reserved"
            if status not in transitions.get(current, set()) or (previous and event.occurred_at < parse_datetime(previous[1])):
                return None
            detail = {"broker_order_id": broker_order_id, "raw_status": raw_status}
            if raw_response:
                detail.update(self._raw_artifact(raw_response))
            cursor = connection.execute("INSERT INTO order_events(attempt_id,occurred_at,event_type,detail_json) VALUES(?,?,?,?)", (attempt_id, event.occurred_at.isoformat(), status, self._encode(detail)))
        return OrderAttemptEvent(**{**event.__dict__, "event_id": int(cursor.lastrowid)})
    def order_attempt_events(self, attempt_id: str) -> list[OrderAttemptEvent]:
        with runtime_connection(read_only=True) as connection:
            rows = connection.execute("SELECT event_id,occurred_at,event_type,detail_json FROM order_events WHERE attempt_id=? ORDER BY occurred_at,event_id", (attempt_id,)).fetchall()
        return [OrderAttemptEvent(event_id=int(row[0]), attempt_id=attempt_id, status=row[2], broker_order_id=self._decode(row[3]).get("broker_order_id"), raw_status=self._decode(row[3]).get("raw_status"), raw_response={}, occurred_at=parse_datetime(row[1])) for row in rows]
    def load_intent(self, intent_id: str) -> ExecutionIntent | None:
        with runtime_connection(read_only=True) as connection:
            row = connection.execute("SELECT payload_json FROM intents WHERE intent_id=?", (intent_id,)).fetchone()
        return _intent(self._decode(row[0])) if row else None
    def claim_intent(self, intent_id: str) -> ExecutionIntent | None:
        with runtime_connection() as connection:
            row = connection.execute("SELECT payload_json FROM intents WHERE intent_id=? AND status='approved'", (intent_id,)).fetchone()
            if row is None:
                return None
            payload = self._decode(row[0])
            intent = _intent(payload)
            now = datetime.now(timezone.utc)
            if not intent.not_before <= now < intent.expires_at:
                return None
            payload.update(status="claimed", claimed_at=datetime.now(timezone.utc).isoformat())
            connection.execute("UPDATE intents SET status='claimed',payload_json=?,updated_at=? WHERE intent_id=? AND status='approved'", (self._encode(payload), datetime.now(timezone.utc).isoformat(), intent_id))
        return _intent(payload)
    def update_intent_status(self, intent_id: str, status: str, failure_reason: str | None = None, *, expected_status: str | None = None) -> None:
        with runtime_connection() as connection:
            row = connection.execute("SELECT status,payload_json FROM intents WHERE intent_id=?", (intent_id,)).fetchone()
            if row is None or (expected_status is not None and row[0] != expected_status):
                return
            payload = self._decode(row[1])
            payload.update(status=status, failure_reason=failure_reason)
            if status == "completed":
                payload["completed_at"] = datetime.now(timezone.utc).isoformat()
            connection.execute("UPDATE intents SET status=?,payload_json=?,updated_at=? WHERE intent_id=?", (status, self._encode(payload), datetime.now(timezone.utc).isoformat(), intent_id))
    def create_planned_order(self, row: dict) -> None:
        payload = dict(row)
        required = ("client_order_id", "intent_id", "account_seq", "status")
        if any(payload.get(name) in (None, "") for name in required):
            raise ExecutionSafetyError("planned order is incomplete")
        payload = self._with_security_identity(payload)
        if payload["status"] != "planned":
            raise ExecutionSafetyError("new order must be planned")
        now = datetime.now(timezone.utc).isoformat()
        with runtime_connection() as connection:
            old = connection.execute("SELECT payload_json FROM orders WHERE client_order_id=?", (payload["client_order_id"],)).fetchone()
            if old:
                saved = self._decode(old[0])
                if any(not _same_planned_value(key, saved.get(key), payload.get(key)) for key in ("intent_id", "approval_id", "account_seq", "broker_order_id", "ticker", "security_id", "side", "quantity", "reference_price", "notional", "status")):
                    raise ExecutionSafetyError("planned order conflicts with an existing order")
                return
            connection.execute("INSERT INTO orders(client_order_id,broker_order_id,intent_id,status,account_seq,submitted_at,updated_at,payload_json) VALUES(?,?,?,?,?,?,?,?)", (payload["client_order_id"], payload.get("broker_order_id"), payload["intent_id"], payload["status"], int(payload["account_seq"]), payload.get("submitted_at"), now, self._encode(payload)))
    def attach_order_attempt(self, client_order_id: str, attempt_id: str) -> None:
        with runtime_connection() as connection:
            row = connection.execute("SELECT status,payload_json FROM orders WHERE client_order_id=?", (client_order_id,)).fetchone()
            if row is None or row[0] != "planned":
                raise ExecutionSafetyError("reserved attempt could not be attached to planned order")
            payload = self._decode(row[1])
            attempt_row = connection.execute("SELECT payload_json FROM order_attempts WHERE attempt_id=? AND client_order_id=?", (attempt_id, client_order_id)).fetchone()
            if attempt_row is None:
                raise ExecutionSafetyError("reserved attempt does not belong to order")
            attempt = self._decode(attempt_row[0])
            if any(attempt.get(key) != payload.get(key) for key in ("intent_id", "approval_id", "account_seq")):
                raise ExecutionSafetyError("reserved attempt identity does not match order")
            if payload.get("attempt_id") is not None:
                raise ExecutionSafetyError("reserved attempt could not be attached to planned order")
            payload["attempt_id"] = attempt_id
            connection.execute("UPDATE orders SET payload_json=?,updated_at=? WHERE client_order_id=?", (self._encode(payload), datetime.now(timezone.utc).isoformat(), client_order_id))
    def update_order_status(self, client_order_id: str, *, status: str, broker_order_id: str | None) -> None:
        self.update_order_execution(client_order_id, status=status, broker_order_id=broker_order_id)
    def update_order_execution(self, client_order_id: str, *, status: str, broker_order_id: str | None, raw_broker_status: str | None = None, raw_broker_response: dict | None = None, submitted_at: datetime | None = None) -> None:
        if submitted_at is not None and submitted_at.tzinfo is None:
            raise ExecutionSafetyError("submitted_at must include a timezone")
        transitions = {
            "planned": {"submitted", "outcome_unknown", "rejected", "failed", "cancelled"},
            "submitted": {"partially_filled", "filled", "cancelled", "rejected", "outcome_unknown", "reconciling"},
            "partially_filled": {"filled", "cancelled", "outcome_unknown", "reconciling"},
            "outcome_unknown": {"submitted", "partially_filled", "filled", "cancelled", "rejected", "failed", "reconciling"},
            "reconciling": {"submitted", "partially_filled", "filled", "cancelled", "rejected", "failed", "outcome_unknown"},
        }
        terminal = {"filled", "cancelled", "rejected", "failed"}
        with runtime_connection() as connection:
            row = connection.execute("SELECT status,broker_order_id,payload_json FROM orders WHERE client_order_id=?", (client_order_id,)).fetchone()
            if row is None:
                raise ExecutionSafetyError("live order execution state could not be updated")
            current_status, saved_broker_order_id = str(row[0]), row[1]
            if status != current_status and status not in transitions.get(current_status, set()):
                raise ExecutionSafetyError("invalid order execution transition")
            if current_status in terminal and status != current_status:
                raise ExecutionSafetyError("terminal order execution state is immutable")
            if saved_broker_order_id is not None and broker_order_id != saved_broker_order_id:
                raise ExecutionSafetyError("broker order identity is immutable")
            payload = self._decode(row[2])
            payload.update(status=status, broker_order_id=broker_order_id, raw_broker_status=raw_broker_status)
            if raw_broker_response:
                payload.update(self._raw_artifact(raw_broker_response))
            if submitted_at is not None:
                payload["submitted_at"] = submitted_at.astimezone(timezone.utc).isoformat()
            connection.execute("UPDATE orders SET broker_order_id=?,status=?,submitted_at=?,updated_at=?,payload_json=? WHERE client_order_id=?", (broker_order_id, status, payload.get("submitted_at"), datetime.now(timezone.utc).isoformat(), self._encode(payload), client_order_id))
    def unresolved_orders(self, *, account_seq: int) -> list[dict]:
        """브로커 결과가 아직 확정되지 않은 주문. 하나라도 있으면 새 실주문을 막는다."""
        with runtime_connection(read_only=True) as connection:
            rows = connection.execute("SELECT payload_json FROM orders WHERE account_seq=? AND status IN ('planned','submitted','partially_filled','outcome_unknown','reconciling') ORDER BY updated_at,client_order_id", (account_seq,)).fetchall()
        return [self._decode(row[0]) for row in rows]
    def reconcilable_orders(self, *, account_seq: int) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        with runtime_connection(read_only=True) as connection:
            rows = connection.execute("SELECT payload_json FROM orders WHERE account_seq=? AND (status IN ('submitted','partially_filled','outcome_unknown','reconciling') OR (status IN ('filled','cancelled','rejected','replaced') AND broker_order_id IS NOT NULL AND submitted_at >= ?)) ORDER BY updated_at,client_order_id", (account_seq, cutoff)).fetchall()
        return [self._decode(row[0]) for row in rows]
    def intent_orders(self, intent_id: str) -> list[dict]:
        with runtime_connection(read_only=True) as connection:
            rows = connection.execute("SELECT payload_json FROM orders WHERE intent_id=? ORDER BY client_order_id", (intent_id,)).fetchall()
        return [self._decode(row[0]) for row in rows]
