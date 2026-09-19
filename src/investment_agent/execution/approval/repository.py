"""Execution lifecycle owner persistence methods."""
from __future__ import annotations

from datetime import datetime, timezone

from investment_agent.execution.db import _approval
from investment_agent.execution.approval.ledger import ApprovalRequest
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.platform.db.sqlite import runtime_connection


class ApprovalRepository:
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
