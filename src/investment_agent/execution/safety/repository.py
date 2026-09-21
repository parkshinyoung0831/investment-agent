"""Execution lifecycle owner persistence methods."""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.safety.control import RuntimeRiskState
from investment_agent.execution.safety.control_state import DurableControlState
from investment_agent.platform.db.sqlite import runtime_connection
from investment_agent.platform.serialization import parse_datetime

# 오늘 장전 스냅샷이 없을 때 전일 마감 기준점으로 삼을 수 있는 가장 오래된 스냅샷. 연휴 주말(금요일 마감 →
# 화요일 개장, 4일)을 덮는 범위이고, 이보다 오래된 자산은 손실 판정의 기준이 아니라 입출금·평가 변동이 섞인 값이다.
PRIOR_BASELINE_MAX_AGE = timedelta(days=5)


class SafetyRepository:
    def load_control_state(self, scope: str = "global") -> DurableControlState:
        with runtime_connection(read_only=True) as connection:
            row = connection.execute(
                "SELECT control_value FROM execution_control WHERE control_key = ?", (scope,)
            ).fetchone()
        if row is None:
            raise ExecutionSafetyError("durable execution control state is missing")
        return DurableControlState.from_row(self._decode(row[0]))
    def initialize_control_state(self) -> DurableControlState:
        """최초 설치에만 모든 실행 권한을 닫고 기존 운영자 설정은 보존한다."""
        now = datetime.now(timezone.utc).isoformat()
        payload = dict(scope='global', kill_switch_on=True, durable_lockdown_on=True,
                       live_enabled=False, live_autonomy_enabled=False, version=1,
                       reason='초기 설치: 운영자 설정 대기', updated_at=now)
        with runtime_connection() as connection:
            connection.execute('INSERT OR IGNORE INTO execution_control VALUES(?,?,?)',
                               ('global', self._encode(payload), now))
        return self.load_control_state()
    def set_manual_control_state(self, *, expected_version: int, is_enabled: bool, reason: str) -> DurableControlState:
        """명시적인 운영자 CLI만 호출하며 환경변수의 별도 게이트는 유지한다."""
        if not reason.strip():
            raise ExecutionSafetyError('operator reason is required')
        now = datetime.now(timezone.utc).isoformat()
        with runtime_connection() as connection:
            old = connection.execute('SELECT control_value FROM execution_control WHERE control_key=?', ('global',)).fetchone()
            if old is None or self._decode(old[0])['version'] != expected_version:
                raise ExecutionSafetyError('execution control version changed or missing')
            payload = dict(scope='global', kill_switch_on=not is_enabled, durable_lockdown_on=not is_enabled,
                           live_enabled=is_enabled, live_autonomy_enabled=False, version=expected_version+1,
                           reason=reason.strip(), updated_at=now)
            connection.execute('UPDATE execution_control SET control_value=?,updated_at=? WHERE control_key=?',
                               (self._encode(payload), now, 'global'))
        return DurableControlState.from_row(payload)
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
                baseline_rows = [
                    row for row in matching
                    if day_start - PRIOR_BASELINE_MAX_AGE <= parse_datetime(str(row["captured_at"])) < day_start
                ]
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
        # realized_pnl_usd는 실현손익이 아니라 당일 손실 한도용 값이다 — 기준 자산 대비 변화와 브로커 일간 손익 중
        # 나쁜 쪽을 쓰므로 입출금은 손실로 읽힌다(조이는 방향으로만 틀린다).
        return RuntimeRiskState(submitted_order_count=len({str(row["client_order_id"]) for row in submitted}), submitted_notional_usd=sum(float(row.get("notional") or 0) for row in submitted), realized_pnl_usd=min(current_equity - baseline_equity, broker_daily_pnl_usd), drawdown_fraction=max(0.0, (peak-current_equity)/peak), captured_at=current.isoformat())
