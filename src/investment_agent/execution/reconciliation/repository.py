"""Execution lifecycle owner persistence methods."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.platform.db.sqlite import runtime_connection
from investment_agent.platform.serialization import parse_datetime

_RUN_TERMINAL_STATUSES = {"ok", "mismatch", "failed"}


class ReconciliationRepository:
    def begin_reconciliation_run(self, *, started_at: datetime | None = None) -> int:
        """대사 실행 시작을 `reconciliation_runs`에 남기고 id를 반환한다."""
        moment = parse_datetime(started_at or datetime.now(timezone.utc)).isoformat()
        with runtime_connection() as connection:
            cursor = connection.execute(
                "INSERT INTO reconciliation_runs(started_at,status,payload_json) VALUES(?,?,?)",
                (moment, "running", "{}"),
            )
            return int(cursor.lastrowid)

    def finish_reconciliation_run(
        self,
        reconciliation_id: int,
        *,
        status: str,
        payload: dict,
        finished_at: datetime | None = None,
    ) -> None:
        """대사 실행 종료를 기록한다. 화면의 "대사 실행" 패널이 이 표를 읽는다."""
        if status not in _RUN_TERMINAL_STATUSES:
            raise ExecutionSafetyError(f"invalid reconciliation run status: {status}")
        moment = parse_datetime(finished_at or datetime.now(timezone.utc)).isoformat()
        with runtime_connection() as connection:
            connection.execute(
                "UPDATE reconciliation_runs SET finished_at=?, status=?, payload_json=? "
                "WHERE reconciliation_id=?",
                (moment, status, self._encode(dict(payload)), reconciliation_id),
            )

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
