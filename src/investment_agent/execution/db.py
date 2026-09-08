"""로컬 SQLite 실행 원장과 canonical 종목 identity 조회 경계."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from investment_agent.execution.orders.intents import ExecutionIntent
from investment_agent.platform.db.postgres import sb, select_all_paged
from investment_agent.platform.serialization import parse_datetime
from investment_agent.execution.approval.ledger import ApprovalRequest
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.safety.control_state import DurableControlState
from investment_agent.execution.orders.ledger import (
    OrderAttempt,
    OrderAttemptEvent,
    OrderAttemptReservation,
)
from investment_agent.execution.safety.control import RuntimeRiskState
from investment_agent.execution.orders.market_state import MarketQuote
from investment_agent.execution.orders.toss_manual import TossManualHandoff
from investment_agent.platform.db.sqlite import runtime_connection

# --- DB 식별자 (SSOT) ---------------------------------------------------
# 문자열을 흩뿌리면 개명·오타가 런타임 PGRST 404로만 드러난다. 여기서만 바꾼다.
SCHEMA_UNIVERSE = "universe"
T_PORTFOLIO_PROPOSALS = "portfolio_proposals"
T_RISK_DECISIONS = "risk_decisions"
T_SECURITIES = "securities"
# ----------------------------------------------------------------------


_PLANNED_NUMERIC_FIELDS = {"account_seq", "quantity", "reference_price", "notional"}


def _same_planned_value(field: str, stored, expected) -> bool:
    """PostgREST numeric 직렬화 차이(``5``/``5.0``)를 충돌로 오인하지 않는다."""
    if stored is None or expected is None:
        return stored is None and expected is None
    if field not in _PLANNED_NUMERIC_FIELDS:
        return str(stored) == str(expected)
    try:
        left = Decimal(str(stored))
        right = Decimal(str(expected))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return left.is_finite() and right.is_finite() and left == right


def _intent(row: dict) -> ExecutionIntent:
    return ExecutionIntent(
        intent_id=str(row["intent_id"]),
        risk_decision_id=str(row["risk_decision_id"]),
        proposal_id=str(row["proposal_id"]),
        execution_mode=str(row["execution_mode"]),
        target_weights=dict(row["target_weights"]),
        input_hash=str(row["input_hash"]),
        not_before=parse_datetime(str(row["not_before"])),
        expires_at=parse_datetime(str(row["expires_at"])),
        status=str(row["status"]),
    )


def _approval(row: dict) -> ApprovalRequest:
    return ApprovalRequest(
        approval_id=str(row["approval_id"]),
        intent_id=str(row["intent_id"]),
        proposal_id=str(row["proposal_id"]),
        risk_decision_id=str(row["risk_decision_id"]),
        execution_mode=str(row["execution_mode"]),
        proposal_hash=str(row["proposal_hash"]),
        risk_hash=str(row["risk_hash"]),
        manifest_hash=str(row["manifest_hash"]),
        account_seq=int(row["account_seq"]),
        allowed_client_order_ids=tuple(row.get("allowed_client_order_ids") or ()),
        status=str(row["status"]),
        decision=str(row["decision"]) if row.get("decision") is not None else None,
        discord_guild_id=str(row["discord_guild_id"]),
        discord_channel_id=str(row["discord_channel_id"]),
        discord_message_id=(
            str(row["discord_message_id"])
            if row.get("discord_message_id") is not None else None
        ),
        allowed_approver_user_ids=tuple(row.get("allowed_approver_user_ids") or ()),
        requested_at=parse_datetime(str(row["requested_at"])),
        expires_at=parse_datetime(str(row["expires_at"])),
        decided_at=(
            parse_datetime(str(row["decided_at"])) if row.get("decided_at") is not None else None
        ),
        decided_by_user_id=(
            str(row["decided_by_user_id"])
            if row.get("decided_by_user_id") is not None else None
        ),
        consumed_at=(
            parse_datetime(str(row["consumed_at"])) if row.get("consumed_at") is not None else None
        ),
    )


def _order_attempt(row: dict) -> OrderAttempt:
    return OrderAttempt(
        attempt_id=str(row["attempt_id"]),
        client_order_id=str(row["client_order_id"]),
        intent_id=str(row["intent_id"]),
        approval_id=str(row["approval_id"]),
        operation=str(row["operation"]),
        payload_hash=str(row["payload_hash"]),
        manifest_hash=str(row["manifest_hash"]),
        account_seq=int(row["account_seq"]),
        request_payload=dict(row.get("request_payload") or {}),
        broker_order_id=(
            str(row["broker_order_id"]) if row.get("broker_order_id") is not None else None
        ),
        replaces_client_order_id=(
            str(row["replaces_client_order_id"])
            if row.get("replaces_client_order_id") is not None else None
        ),
        reserved_at=parse_datetime(str(row["reserved_at"])),
    )


def _attempt_event(row: dict) -> OrderAttemptEvent:
    return OrderAttemptEvent(
        event_id=int(row["event_id"]),
        attempt_id=str(row["attempt_id"]),
        status=str(row["status"]),
        broker_order_id=(
            str(row["broker_order_id"]) if row.get("broker_order_id") is not None else None
        ),
        raw_status=str(row["raw_status"]) if row.get("raw_status") is not None else None,
        raw_response=dict(row.get("raw_response") or {}),
        occurred_at=parse_datetime(str(row["occurred_at"])),
    )


class ExecutionRepository:
    """실행 컴퓨터의 SQLite 원장만 사용하는 주문·승인 저장소."""

    @staticmethod
    def _encode(row: dict) -> str:
        return json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def _decode(value: str) -> dict:
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ExecutionSafetyError("runtime ledger payload must be an object")
        return parsed

    @classmethod
    def _record(cls, connection, record_type: str, record_key: str) -> dict | None:
        row = connection.execute(
            "SELECT payload_json FROM runtime_records WHERE record_type = ? AND record_key = ?",
            (record_type, record_key),
        ).fetchone()
        return cls._decode(row[0]) if row else None

    @classmethod
    def _save_record(cls, connection, record_type: str, record_key: str, payload: dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        connection.execute(
            "INSERT INTO runtime_records(record_type,record_key,payload_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(record_type,record_key) DO UPDATE SET "
            "payload_json=excluded.payload_json,updated_at=excluded.updated_at",
            (record_type, record_key, cls._encode(payload), now, now),
        )

    def portfolio_proposal(self, proposal_id: str) -> dict | None:
        with runtime_connection(read_only=True) as connection:
            return self._decision_row(connection, T_PORTFOLIO_PROPOSALS, "proposal_id", proposal_id)

    def risk_decision(self, risk_decision_id: str) -> dict | None:
        with runtime_connection(read_only=True) as connection:
            return self._decision_row(connection, T_RISK_DECISIONS, "risk_decision_id", risk_decision_id)

    @staticmethod
    def _decision_row(connection, table: str, key: str, value: str) -> dict | None:
        cursor = connection.execute(f"SELECT * FROM {table} WHERE {key}=?", (value,))
        values = cursor.fetchone()
        if values is None:
            return None
        row = dict(zip([item[0] for item in cursor.description], values))
        types = {item[1]: str(item[2]).upper() for item in connection.execute(f"PRAGMA table_info({table})")}
        return {name: json.loads(value) if value is not None and types[name] == "JSON" else bool(value) if value is not None and types[name] == "BOOLEAN" else value for name, value in row.items()}

    def load_control_state(self, scope: str = "global") -> DurableControlState:
        with runtime_connection(read_only=True) as connection:
            row = connection.execute(
                "SELECT control_value FROM execution_control WHERE control_key = ?", (scope,)
            ).fetchone()
        if row is None:
            raise ExecutionSafetyError("durable execution control state is missing")
        return DurableControlState.from_row(self._decode(row[0]))

    def current_tracked_tickers(self) -> set[str]:
        return {str(row["ticker"]).upper() for row in select_all_paged(
            lambda: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES)
            .select("ticker").eq("is_tracked", True).order("ticker"), order_by="ticker",
        )}

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
            connection.execute(
                "INSERT INTO intents(intent_id,proposal_id,risk_decision_id,execution_mode,status,not_before,expires_at,payload_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(intent_id) DO NOTHING",
                (payload["intent_id"], payload["proposal_id"], payload["risk_decision_id"],
                 payload["execution_mode"], payload["status"], payload["not_before"],
                 payload["expires_at"], self._encode(payload), now, now),
            )

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

    def create_approval(self, request: ApprovalRequest) -> ApprovalRequest:
        payload = request.as_row()
        now = datetime.now(timezone.utc).isoformat()
        with runtime_connection() as connection:
            connection.execute(
                "INSERT INTO approvals(approval_id,intent_id,status,manifest_hash,expires_at,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (request.approval_id, request.intent_id, request.status, request.manifest_hash,
                 request.expires_at.isoformat(), self._encode(payload), now, now),
            )
        return request

    def _approval_by(self, column: str, value: str) -> ApprovalRequest | None:
        with runtime_connection(read_only=True) as connection:
            row = connection.execute(
                f"SELECT payload_json FROM approvals WHERE {column} = ? LIMIT 1", (value,)
            ).fetchone()
        return _approval(self._decode(row[0])) if row else None

    def load_approval(self, approval_id: str) -> ApprovalRequest | None:
        return self._approval_by("approval_id", approval_id)

    def approval_for_intent(self, intent_id: str) -> ApprovalRequest | None:
        return self._approval_by("intent_id", intent_id)

    def _update_approval(self, request: ApprovalRequest, *, expected: ApprovalRequest) -> ApprovalRequest | None:
        payload = request.as_row()
        with runtime_connection() as connection:
            changed = connection.execute(
                "UPDATE approvals SET status=?, manifest_hash=?, expires_at=?, payload_json=?, updated_at=? "
                "WHERE approval_id=? AND payload_json=? AND expires_at>?",
                (request.status, request.manifest_hash, request.expires_at.isoformat(), self._encode(payload),
                 datetime.now(timezone.utc).isoformat(), request.approval_id,
                 self._encode(expected.as_row()), datetime.now(timezone.utc).isoformat()),
            )
        return request if changed.rowcount == 1 else None

    def attach_approval_message(self, approval_id: str, *, discord_guild_id: str, discord_channel_id: str, discord_message_id: str) -> ApprovalRequest | None:
        request = self.load_approval(approval_id)
        now = datetime.now(timezone.utc)
        if request is None or request.status != "pending" or request.expires_at <= now:
            return None
        if (request.discord_guild_id, request.discord_channel_id, request.discord_message_id) != (discord_guild_id, discord_channel_id, None):
            return None
        return self._update_approval(ApprovalRequest(**{**request.__dict__, "discord_message_id": discord_message_id}), expected=request)

    def decide_approval(self, approval_id: str, *, action: str, discord_guild_id: str, discord_channel_id: str, discord_message_id: str, discord_user_id: str) -> ApprovalRequest | None:
        request = self.load_approval(approval_id)
        now = datetime.now(timezone.utc)
        if (request is None or request.status != "pending" or request.expires_at <= now or action not in ("approve", "reject")
                or request.discord_guild_id != discord_guild_id or request.discord_channel_id != discord_channel_id
                or request.discord_message_id != discord_message_id or discord_user_id not in request.allowed_approver_user_ids):
            return None
        return self._update_approval(ApprovalRequest(**{**request.__dict__, "status": "approved" if action == "approve" else "rejected", "decision": "approved" if action == "approve" else "rejected", "decided_at": now, "decided_by_user_id": discord_user_id}), expected=request)

    def consume_approval(self, approval_id: str, *, manifest_hash: str) -> ApprovalRequest | None:
        request = self.load_approval(approval_id)
        now = datetime.now(timezone.utc)
        if request is None or request.status != "approved" or request.manifest_hash != manifest_hash or request.expires_at <= now:
            return None
        return self._update_approval(ApprovalRequest(**{**request.__dict__, "status": "consumed", "consumed_at": now}), expected=request)

    def expire_due_approvals(self) -> int:
        now = datetime.now(timezone.utc)
        with runtime_connection() as connection:
            rows = connection.execute("SELECT payload_json FROM approvals WHERE status IN ('pending','approved') AND expires_at <= ?", (now.isoformat(),)).fetchall()
            for row in rows:
                request = _approval(self._decode(row[0]))
                updated = ApprovalRequest(**{**request.__dict__, "status": "expired"})
                connection.execute("UPDATE approvals SET status='expired', payload_json=?, updated_at=? WHERE approval_id=?", (self._encode(updated.as_row()), now.isoformat(), request.approval_id))
        return len(rows)

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

    def save_broker_order_snapshot(self, row: dict) -> None:
        payload = dict(row)
        raw = payload.pop("raw_broker_response", None) or payload.pop("raw_response", None)
        if raw:
            payload.update(self._raw_artifact(dict(raw)))
        self._save_auxiliary("broker_order_snapshot", str(payload.get("snapshot_hash") or ""), payload)

    def _save_auxiliary(self, record_type: str, record_key: str, payload: dict) -> None:
        if not record_key:
            raise ExecutionSafetyError("runtime record identity is required")
        with runtime_connection() as connection:
            old = self._record(connection, record_type, record_key)
            if old is not None and self._encode(old) != self._encode(payload):
                raise ExecutionSafetyError("runtime record conflicts with immutable identity")
            self._save_record(connection, record_type, record_key, dict(payload))

    @staticmethod
    def _with_security_identity(row: dict) -> dict:
        ticker = str(row.get("ticker") or "").strip().upper()
        identities = (sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES).select("security_id")
                      .eq("ticker", ticker).limit(2).execute().data or []) if ticker else []
        if len(identities) != 1:
            raise ExecutionSafetyError("order ticker is not present in universe")
        security_id = int(identities[0]["security_id"])
        if row.get("security_id") is not None and row["security_id"] != security_id:
            raise ExecutionSafetyError("security identity does not match ticker")
        return {**row, "ticker": ticker, "security_id": security_id}

    @classmethod
    def _raw_artifact(cls, payload: dict) -> dict:
        """원본 응답을 내용 주소 파일로 보존하고 원장에는 경로·해시만 남긴다."""
        import os
        from investment_agent.platform.db.sqlite import default_runtime_database_path

        data = cls._encode(payload).encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        root = default_runtime_database_path().resolve().parent / "artifacts" / "execution" / "raw"
        root.mkdir(parents=True, exist_ok=True)
        target = root / f"{digest}.json"
        if not target.exists():
            from tempfile import NamedTemporaryFile
            with NamedTemporaryFile(dir=root, delete=False) as stream:
                temporary = stream.name
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        elif hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ExecutionSafetyError("broker artifact digest mismatch")
        return {"raw_artifact_path": str(target), "raw_sha256": digest}

    def save_decision_record(self, record_type: str, record_key: str, payload: dict) -> None:
        """실행을 위해 보존해야 하는 판단 원문을 local runtime에 기록한다."""
        if record_type not in {"portfolio_proposal", "risk_decision"}:
            raise ValueError("unsupported runtime decision record type")
        self._save_auxiliary(record_type, record_key, payload)

    def reconcilable_orders(self, *, account_seq: int) -> list[dict]:
        with runtime_connection(read_only=True) as connection:
            rows = connection.execute("SELECT payload_json FROM orders WHERE account_seq=? AND status IN ('submitted','partially_filled','outcome_unknown','reconciling') ORDER BY updated_at,client_order_id", (account_seq,)).fetchall()
        return [self._decode(row[0]) for row in rows]

    def intent_orders(self, intent_id: str) -> list[dict]:
        with runtime_connection(read_only=True) as connection:
            rows = connection.execute("SELECT payload_json FROM orders WHERE intent_id=? ORDER BY client_order_id", (intent_id,)).fetchall()
        return [self._decode(row[0]) for row in rows]

    def runtime_risk_state(self, *, account_seq: int, current_equity: float, broker_daily_pnl_usd: float, captured_at: datetime) -> RuntimeRiskState:
        if captured_at.tzinfo is None or not math.isfinite(current_equity) or current_equity <= 0 or not math.isfinite(broker_daily_pnl_usd):
            raise ExecutionSafetyError("runtime risk snapshot is invalid")
        current = captured_at.astimezone(timezone.utc)
        account_ref = hashlib.sha256(f"toss|{account_seq}".encode("utf-8")).hexdigest()
        eastern = current.astimezone(ZoneInfo("America/New_York"))
        day_start = datetime.combine(eastern.date(), time.min, tzinfo=eastern.tzinfo).astimezone(timezone.utc)
        session_open = datetime.combine(eastern.date(), time(hour=9, minute=30), tzinfo=eastern.tzinfo).astimezone(timezone.utc)
        with runtime_connection() as connection:
            rows = connection.execute("SELECT payload_json FROM runtime_records WHERE record_type='account_snapshot'").fetchall()
            snapshots = [self._decode(row[0]) for row in rows]
            matching = [row for row in snapshots if row.get("execution_mode") == "live" and row.get("broker_account_hash") == account_ref]
            baseline_rows = [row for row in matching if day_start <= parse_datetime(str(row["captured_at"])) <= min(session_open, current)]
            if not baseline_rows:
                baseline_rows = [row for row in matching if parse_datetime(str(row["captured_at"])) < day_start]
            if not baseline_rows:
                raise ExecutionSafetyError("live risk baseline is missing; capture a Toss snapshot before US market open")
            baseline = max(baseline_rows, key=lambda row: str(row["captured_at"]))
            baseline_equity = float(baseline["equity"])
            if not math.isfinite(baseline_equity) or baseline_equity <= 0:
                raise ExecutionSafetyError("live risk baseline equity is invalid")
            snapshot = {"execution_mode": "live", "broker_account_hash": account_ref, "equity": current_equity, "cash": 0, "buying_power": None, "captured_at": current.isoformat(), "broker_daily_pnl_usd": broker_daily_pnl_usd}
            self._save_record(connection, "account_snapshot", hashlib.sha256(self._encode(snapshot).encode()).hexdigest(), snapshot)
            daily = [row for row in matching + [snapshot] if day_start <= parse_datetime(str(row["captured_at"])) <= current]
            order_rows = connection.execute("SELECT payload_json FROM orders WHERE account_seq=? AND submitted_at IS NOT NULL", (account_seq,)).fetchall()
        equities = [float(row["equity"]) for row in daily]
        if any(not math.isfinite(value) or value <= 0 for value in equities):
            raise ExecutionSafetyError("daily account equity history is invalid")
        peak = max([baseline_equity, *equities])
        orders = [self._decode(row[0]) for row in order_rows]
        submitted = [row for row in orders if day_start <= parse_datetime(str(row["submitted_at"])) <= current]
        if any(not math.isfinite(float(row.get("notional", 0))) or float(row.get("notional", 0)) < 0 for row in submitted):
            raise ExecutionSafetyError("daily order notional is invalid")
        return RuntimeRiskState(submitted_order_count=len({str(row["client_order_id"]) for row in submitted}), submitted_notional_usd=sum(float(row.get("notional") or 0) for row in submitted), realized_pnl_usd=min(current_equity - baseline_equity, broker_daily_pnl_usd), drawdown_fraction=max(0.0, (peak-current_equity)/peak), captured_at=current.isoformat())

    def save_fill(self, row: dict) -> None:
        payload = dict(row)
        fill_id = str(payload.get("broker_fill_id") or payload.get("fill_id") or "")
        if not fill_id:
            raise ExecutionSafetyError("fill identity is required")
        if any(not math.isfinite(float(payload[key])) or float(payload[key]) <= 0 for key in ("quantity", "price")):
            raise ExecutionSafetyError("fill quantity and price must be finite and positive")
        payload["filled_at"] = parse_datetime(payload["filled_at"]).isoformat()
        with runtime_connection() as connection:
            old = connection.execute("SELECT payload_json FROM fills WHERE fill_id=?", (fill_id,)).fetchone()
            if old:
                if self._decode(old[0]) != payload:
                    raise ExecutionSafetyError("fill identity conflicts with stored fill")
                return
            connection.execute("INSERT INTO fills(fill_id,broker_order_id,filled_at,quantity,price,payload_json) VALUES(?,?,?,?,?,?)", (fill_id, payload["broker_order_id"], payload["filled_at"], float(payload["quantity"]), float(payload["price"]), self._encode(payload)))

    def save_tca_report(self, report: dict | object) -> None:
        payload = report.to_dict() if hasattr(report, "to_dict") else dict(report)
        if not payload.get("tca_id"):
            raise ExecutionSafetyError("TCA report requires tca_id")
        self._save_auxiliary("tca_summary", str(payload["tca_id"]), {key: value for key, value in payload.items() if key not in {"raw_response", "raw_broker_response"}})

    def save_quote_snapshot(self, quote: MarketQuote, *, purpose: str, source_kind: str = "paper", captured_at: datetime | None = None, metadata: dict | None = None) -> None:
        if not isinstance(quote, MarketQuote):
            raise ExecutionSafetyError("quote snapshot requires MarketQuote")
        payload = quote.to_snapshot_row(purpose=purpose, source_kind=source_kind, captured_at=captured_at, metadata=metadata)
        self._save_auxiliary("quote_snapshot", str(payload["snapshot_id"]), payload)

    def save_account_snapshot(self, row: dict) -> int:
        payload = dict(row)
        moment = parse_datetime(payload.get("captured_at") or datetime.now(timezone.utc))
        captured_at = moment.isoformat()
        try:
            equity = float(payload["equity"])
            cash = float(payload["cash"])
            buying_power = (float(payload["buying_power"])
                            if payload.get("buying_power") is not None else None)
            market_value = float(payload.get("market_value", equity - cash))
        except (KeyError, TypeError, ValueError) as exc:
            raise ExecutionSafetyError("account snapshot amounts are invalid") from exc
        if any(not math.isfinite(value) for value in (equity, cash, market_value)) or (
            buying_power is not None and not math.isfinite(buying_power)
        ):
            raise ExecutionSafetyError("account snapshot amounts must be finite")
        raw = payload.pop("raw_snapshot", None)
        artifact = self._raw_artifact(dict(raw)) if isinstance(raw, dict) and raw else {}
        payload.update(artifact, captured_at=captured_at)
        key = hashlib.sha256(self._encode({
            "execution_mode": payload.get("execution_mode"),
            "broker_account_hash": payload.get("broker_account_hash"),
            "captured_at": captured_at,
        }).encode()).hexdigest()
        execution_mode = payload.get("execution_mode")
        broker_account_hash = payload.get("broker_account_hash")
        if execution_mode not in ("paper", "live") or not broker_account_hash:
            raise ExecutionSafetyError("account snapshot requires execution_mode and broker_account_hash")
        with runtime_connection() as connection:
            self._save_record(connection, "account_snapshot", key, payload)
            connection.execute(
                "INSERT INTO account_snapshots(snapshot_id,broker_account_hash,execution_mode,"
                "snapshot_date,captured_at,cash,market_value,equity,buying_power,"
                "source_artifact_path,source_artifact_sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(broker_account_hash,execution_mode,snapshot_date) DO UPDATE SET "
                "snapshot_id=excluded.snapshot_id,captured_at=excluded.captured_at,cash=excluded.cash,"
                "market_value=excluded.market_value,equity=excluded.equity,"
                "buying_power=excluded.buying_power,source_artifact_path=excluded.source_artifact_path,"
                "source_artifact_sha256=excluded.source_artifact_sha256",
                (key, broker_account_hash, execution_mode, moment.date().isoformat(), captured_at,
                 cash, market_value, equity, buying_power,
                 artifact.get("raw_artifact_path"), artifact.get("raw_sha256")),
            )
            # 주문 전후 위험 계산용 상세점은 짧게 유지하고 장기 사실은 일일 표가 맡는다.
            cutoff = (moment - timedelta(days=2)).isoformat()
            connection.execute(
                "DELETE FROM runtime_records WHERE record_type='account_snapshot' "
                "AND json_extract(payload_json,'$.captured_at') < ?",
                (cutoff,),
            )
        return int(key[:15], 16)

    def save_position_snapshots(self, rows: list[dict]) -> None:
        payloads = [self._with_security_identity(dict(row)) for row in rows]
        with runtime_connection() as connection:
            for payload in payloads:
                payload.pop("ticker")
                self._save_record(connection, "position_snapshot", hashlib.sha256(self._encode(payload).encode()).hexdigest(), payload)


# ops가 execution 스키마를 직접 조회하지 않도록 계약을 여기서 소유한다.


def latest_paper_account_snapshot() -> dict | None:
    with runtime_connection(read_only=True) as connection:
        rows = connection.execute("SELECT payload_json FROM runtime_records WHERE record_type='account_snapshot' ORDER BY updated_at DESC").fetchall()
    snapshots = [ExecutionRepository._decode(row[0]) for row in rows]
    return next((row for row in snapshots if row.get("execution_mode") == "paper"), None)


def latest_order() -> dict | None:
    with runtime_connection(read_only=True) as connection:
        row = connection.execute("SELECT payload_json FROM orders ORDER BY updated_at DESC LIMIT 1").fetchone()
    return ExecutionRepository._decode(row[0]) if row else None


def latest_reconciliation_run() -> dict | None:
    with runtime_connection(read_only=True) as connection:
        row = connection.execute("SELECT reconciliation_id,started_at,finished_at,status,payload_json FROM reconciliation_runs ORDER BY started_at DESC LIMIT 1").fetchone()
    if row is None:
        return None
    return {"reconciliation_id": row[0], "started_at": row[1], "completed_at": row[2], "status": row[3], **ExecutionRepository._decode(row[4])}
