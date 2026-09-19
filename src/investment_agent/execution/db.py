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

# 자금 확보(매도만) 주문표 뒤에 같은 System 목표로 허용하는 후속 실행 수. 1을 넘기면
# 체결 부족 → 재매도 → 재주문이 같은 목표로 되풀이될 수 있다.
MAX_FUNDING_FOLLOWUPS = 1
# System 목표 하나를 실계좌가 따라간 실행 기록. 같은 목표로 주문이 두 번 나가지 않게 intent 저장 시 선점한다.
RECORD_SYSTEM_TARGET_EXECUTION = "system_target_execution"
_TERMINAL_ORDER_STATUSES = ("filled", "cancelled", "rejected", "failed", "replaced")

def funding_followup_allowed(connection, claim: dict | None) -> bool:
    """직전 실행이 끝난 자금 확보 매도였다면 같은 System 목표를 한 번 더 따라가게 허용한다.

    목표당 실행 1회 원칙은 같은 목표로 주문이 두 번 나가는 것을 막는다. 그런데 매수 자금이
    모자라 매도만 먼저 낸 경우에는, 그 매도가 끝난 뒤 **새 계좌 snapshot으로 다시 계산한**
    주문표가 필요하다 — 그렇지 않으면 매도대금이 다음 목표까지 현금으로 논다. 그래서 다음을
    모두 만족할 때만 연다.

    - 직전 주문표가 `funding_sells`였다(매수가 한 주도 나가지 않았다).
    - 그 intent가 끝났다(completed/failed)고, 원장의 주문이 전부 종결 상태다(대사 완료).
    - 이 목표의 후속 실행 수가 한도 미만이다.
    """
    if not claim or int(claim.get("funding_followups") or 0) >= MAX_FUNDING_FOLLOWUPS:
        return False
    intent_id = str(claim.get("intent_id") or "")
    manifest = connection.execute(
        "SELECT payload_json FROM order_manifests WHERE intent_id=?", (intent_id,),
    ).fetchone()
    if manifest is None or json.loads(manifest[0]).get("funding_phase") != "funding_sells":
        return False
    intent = connection.execute("SELECT status FROM intents WHERE intent_id=?", (intent_id,)).fetchone()
    if intent is None or intent[0] not in ("completed", "failed"):
        return False
    statuses = [row[0] for row in connection.execute(
        "SELECT status FROM orders WHERE intent_id=?", (intent_id,),
    ).fetchall()]
    return bool(statuses) and all(status in _TERMINAL_ORDER_STATUSES for status in statuses)

class RuntimeLedgerRepository:
    """실행 컴퓨터의 SQLite 원장만 사용하는 주문·승인 저장소."""

    def is_system_target_followed(self, target_id: str) -> bool:
        """이 System 목표로 이미 승인을 물었으면 True다. 같은 목표는 한 번만 묻는다.

        거절·만료도 물은 것이다 — 사용자가 거절한 목표를 매분 다시 묻지 않는다. 다음 목표가 생기면 다시
        묻는다. 승인 요청까지 가지 못한 intent(카드 발송 실패)나 자금 확보 매도 뒤 후속 실행은 다시 연다.
        """
        with runtime_connection() as connection:
            claim = self._record(connection, RECORD_SYSTEM_TARGET_EXECUTION, str(target_id))
            if claim is None or funding_followup_allowed(connection, claim):
                return False
            return connection.execute(
                "SELECT 1 FROM approvals WHERE intent_id=?", (str(claim["intent_id"]),),
            ).fetchone() is not None

    def performance_sources(self) -> dict:
        """성과 owner에게 실제 원장 사실을 전달하며 누락된 비용·통화를 추정하지 않는다."""
        with runtime_connection(read_only=True) as connection:
            result = {name: [self._decode(row[0]) for row in connection.execute(f"SELECT payload_json FROM {name}")]
                      for name in ('fills', 'orders', 'intents')}
            snapshots = {}
            for kind in ('account_snapshot', 'performance_snapshot'):
                for key, payload in connection.execute("SELECT record_key,payload_json FROM runtime_records WHERE record_type=?", (kind,)):
                    snapshots[key] = {**self._decode(payload), 'snapshot_id': key}
            cursor = connection.execute("SELECT * FROM account_snapshots")
            columns = [column[0] for column in cursor.description]
            for values in cursor:
                row = dict(zip(columns, values))
                snapshots.setdefault(row['snapshot_id'], row)
            result['account_snapshots'] = sorted(snapshots.values(), key=lambda row: row['captured_at'])
            result['position_snapshots'] = [self._decode(row[0]) for row in connection.execute("SELECT payload_json FROM runtime_records WHERE record_type='position_snapshot'")]
            result['broker_order_snapshots'] = [self._decode(row[0]) for row in connection.execute("SELECT payload_json FROM runtime_records WHERE record_type='broker_order_snapshot'")]
        orders_by_broker = {row['broker_order_id']: row for row in result['orders'] if row.get('broker_order_id')}
        for fill in result['fills']:
            order = orders_by_broker.get(fill.get('broker_order_id'), {})
            for key in ('client_order_id', 'ticker', 'side', 'currency'):
                if fill.get(key) is None and order.get(key) is not None:
                    fill[key] = order[key]
        return result

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

    def current_tracked_tickers(self) -> set[str]:
        return {str(row["ticker"]).upper() for row in select_all_paged(
            lambda: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES)
            .select("ticker").eq("is_tracked", True).order("ticker"), order_by="ticker",
        )}


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
        # 주문은 상장 중인 종목에만 낸다. 같은 ticker의 과거 자리표시 종목은 후보가 아니다.
        identities = (sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES).select("security_id")
                      .eq("ticker", ticker).eq("is_active_listing", True)
                      .limit(2).execute().data or []) if ticker else []
        if len(identities) != 1:
            raise ExecutionSafetyError("order ticker is not present in universe")
        security_id = int(identities[0]["security_id"])
        if row.get("security_id") is not None and row["security_id"] != security_id:
            raise ExecutionSafetyError("security identity does not match ticker")
        return {**row, "ticker": ticker, "security_id": security_id}


    def save_decision_record(self, record_type: str, record_key: str, payload: dict) -> None:
        """실행을 위해 보존해야 하는 판단 원문을 local runtime에 기록한다."""
        if record_type not in {"portfolio_proposal", "risk_decision"}:
            raise ValueError("unsupported runtime decision record type")
        self._save_auxiliary(record_type, record_key, payload)

from investment_agent.execution.approval.repository import ApprovalRepository
from investment_agent.execution.brokers.repository import BrokerRepository
from investment_agent.execution.orders.repository import OrderRepository
from investment_agent.execution.reconciliation.repository import ReconciliationRepository
from investment_agent.execution.safety.repository import SafetyRepository

class ExecutionRepository(
    ApprovalRepository,
    OrderRepository,
    BrokerRepository,
    ReconciliationRepository,
    SafetyRepository,
    RuntimeLedgerRepository,
):
    """Lifecycle owner를 조합해 기존 실행 원장 계약을 유지하는 호환 façade."""

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
