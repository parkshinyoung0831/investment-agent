"""Execution lifecycle owner persistence methods."""
from __future__ import annotations

import hashlib
from investment_agent.platform.db.sqlite import runtime_connection


class ReconciliationRepository:
    def load_position_baseline(self, *, account_seq: int) -> dict | None:
        """보유수량 대사가 마지막으로 설명한 계좌 상태. 계좌번호는 hash로만 키에 남긴다."""
        key = hashlib.sha256(f"toss|{account_seq}".encode("utf-8")).hexdigest()
        with runtime_connection(read_only=True) as connection:
            return self._record(connection, "position_reconciliation_baseline", key)
    def save_position_baseline(self, *, account_seq: int, baseline: dict) -> None:
        key = hashlib.sha256(f"toss|{account_seq}".encode("utf-8")).hexdigest()
        with runtime_connection() as connection:
            self._save_record(connection, "position_reconciliation_baseline", key, dict(baseline))
    def save_position_snapshots(self, rows: list[dict]) -> None:
        payloads = [self._with_security_identity(dict(row)) for row in rows]
        with runtime_connection() as connection:
            for payload in payloads:
                self._save_record(connection, "position_snapshot", hashlib.sha256(self._encode(payload).encode()).hexdigest(), payload)
