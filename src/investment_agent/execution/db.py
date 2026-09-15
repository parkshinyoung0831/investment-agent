"""로컬 SQLite 실행 원장과 canonical 종목 identity 조회 경계."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from typing import Sequence

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


# 자금 확보(매도만) 주문표 뒤에 같은 signal batch로 허용하는 후속 실행 수. 1을 넘기면
# 체결 부족 → 재매도 → 재최적화가 같은 신호로 되풀이될 수 있다.
MAX_FUNDING_FOLLOWUPS = 1
_TERMINAL_ORDER_STATUSES = ("filled", "cancelled", "rejected", "failed", "replaced")


def funding_followup_allowed(connection, claim: dict | None) -> bool:
    """직전 실행이 끝난 자금 확보 매도였다면 같은 batch의 재구성을 한 번 허용한다.

    배치당 실행 1회 원칙은 같은 신호로 주문이 두 번 나가는 것을 막는다. 그런데 매수 자금이
    모자라 매도만 먼저 낸 경우에는, 그 매도가 끝난 뒤 **새 계좌 snapshot으로 다시 최적화한**
    주문표가 필요하다 — 그렇지 않으면 매도대금이 다음 batch까지 현금으로 논다. 그래서 다음을
    모두 만족할 때만 연다.

    - 직전 주문표가 `funding_sells`였다(매수가 한 주도 나가지 않았다).
    - 그 intent가 끝났다(completed/failed)고, 원장의 주문이 전부 종결 상태다(대사 완료).
    - 이 batch의 후속 실행 수가 한도 미만이다.
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


def funding_followup_batch_ids() -> set[str]:
    """지금 후속 실행을 받을 수 있는 signal batch. 진입 대기열과 batch 선택이 같은 판정을 쓴다."""
    with runtime_connection(read_only=True) as connection:
        rows = connection.execute(
            "SELECT record_key,payload_json FROM runtime_records WHERE record_type='signal_batch_execution'"
        ).fetchall()
        return {
            str(key) for key, payload in rows
            if funding_followup_allowed(connection, json.loads(payload))
        }


class ExecutionRepository:
    """실행 컴퓨터의 SQLite 원장만 사용하는 주문·승인 저장소."""

    def has_active_execution_for_proposals(
        self,
        proposal_ids: Sequence[str],
        *,
        as_of_at: datetime | None = None,
        batch_id: str | None = None,
    ) -> bool:
        """살아 있는 승인 대기와 제출 증거가 있는 실행만 재실행을 막는다.

        `batch_id`를 주면 그 batch가 자금 확보 매도 뒤 후속 실행을 받을 수 있는지 먼저 본다.
        """
        identities = set(proposal_ids)
        if not identities:
            return False
        if batch_id is not None and str(batch_id) in funding_followup_batch_ids():
            return False
        current = parse_datetime(as_of_at or datetime.now(timezone.utc))
        with runtime_connection(read_only=True) as connection:
            rows = connection.execute(
                "SELECT i.proposal_id,i.status,i.expires_at,a.status,"
                "EXISTS(SELECT 1 FROM order_attempts o WHERE o.intent_id=i.intent_id AND o.state IN ('reserved','submitted','unknown')),"
                "EXISTS(SELECT 1 FROM orders o WHERE o.intent_id=i.intent_id) "
                "FROM intents i LEFT JOIN approvals a ON a.intent_id=i.intent_id WHERE i.execution_mode='live'"
            ).fetchall()
        for proposal, status, expiry, approval, attempted, ordered in rows:
            if proposal not in identities:
                continue
            if attempted or ordered or status in ('executing', 'completed') or approval == 'consumed':
                return True
            if status in ('approved', 'claimed') and approval not in ('rejected', 'expired') and parse_datetime(expiry) > current:
                return True
        return False

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

    def assert_entry_timing(self, proposal_id: str, *, prices: dict, now: datetime) -> None:
        """승인 대기 중 벗어난 진입 가격·재판단 만료를 브로커 제출 전에 차단한다."""
        with runtime_connection(read_only=True) as connection:
            proposal=self._decision_row(connection,T_PORTFOLIO_PROPOSALS,'proposal_id',proposal_id)
            batch_id=(proposal or {}).get('metadata',{}).get('active_batch_id')
            guard=self._record(connection,'entry_guard',str(batch_id)) if batch_id else None
            candidate = connection.execute('SELECT status FROM entry_candidates WHERE signal_id=?',(guard['source_signal_id'],)).fetchone() if guard and guard.get('source_signal_id') else None
        if guard is None:
            return
        if guard.get('source_signal_id') and (candidate is None or candidate[0] != 'ready'):
            raise ExecutionSafetyError('entry decision was superseded or cancelled')
        review=guard['review']
        if review['decision']!='enter' or not parse_datetime(review['reviewed_at']) <= now < parse_datetime(review['expires_at']):
            raise ExecutionSafetyError('entry review expired before order submission')
        price=prices.get(guard['ticker'])
        plan=guard['plan']
        if price is None or not math.isfinite(float(price)) or not plan['lower_price'] <= float(price) <= plan['upper_price']:
            raise ExecutionSafetyError('price left approved entry range')

    def entry_guard_for_proposal(self, proposal_id: str) -> dict | None:
        with runtime_connection(read_only=True) as connection:
            proposal=self._decision_row(connection,T_PORTFOLIO_PROPOSALS,'proposal_id',proposal_id)
            batch_id=(proposal or {}).get('metadata',{}).get('active_batch_id')
            return self._record(connection,'entry_guard',str(batch_id)) if batch_id else None

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
            if payload['execution_mode'] == 'live':
                proposal = self._decision_row(connection, T_PORTFOLIO_PROPOSALS, 'proposal_id', payload['proposal_id'])
                batch_id = (proposal or {}).get('metadata', {}).get('active_batch_id')
                if batch_id:
                    claim = self._record(connection, 'signal_batch_execution', str(batch_id))
                    followup = funding_followup_allowed(connection, claim)
                    if claim and not followup:
                        if self._record(connection, 'entry_guard', str(batch_id)) is not None:
                            raise ExecutionSafetyError('signal batch entry review was already used')
                        previous = connection.execute(
                            "SELECT i.status,i.expires_at,a.status,"
                            "EXISTS(SELECT 1 FROM order_attempts o WHERE o.intent_id=i.intent_id AND o.state != 'failed'),"
                            "EXISTS(SELECT 1 FROM orders o WHERE o.intent_id=i.intent_id) "
                            "FROM intents i LEFT JOIN approvals a ON a.intent_id=i.intent_id WHERE i.intent_id=?",
                            (claim['intent_id'],)).fetchone()
                        if previous and (previous[3] or previous[4] or previous[0] in ('executing','completed') or previous[2] == 'consumed'
                            or (previous[0] in ('approved','claimed') and previous[2] not in ('rejected','expired') and parse_datetime(previous[1]) > parse_datetime(now))):
                            raise ExecutionSafetyError('signal batch already has an active execution')
                    record = {'intent_id': payload['intent_id']}
                    if followup:
                        record.update(
                            funding_followups=int(claim.get('funding_followups') or 0) + 1,
                            previous_intent_ids=[*claim.get('previous_intent_ids', ()), claim['intent_id']],
                        )
                    self._save_record(connection, 'signal_batch_execution', str(batch_id), record)
            connection.execute(
                "INSERT INTO intents(intent_id,proposal_id,risk_decision_id,execution_mode,status,not_before,expires_at,payload_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(intent_id) DO NOTHING",
                (payload["intent_id"], payload["proposal_id"], payload["risk_decision_id"],
                 payload["execution_mode"], payload["status"], payload["not_before"],
                 payload["expires_at"], self._encode(payload), now, now),
            )
            if payload["execution_mode"] == "live":
                self._supersede_pending_live_intents(connection, new_intent_id=payload["intent_id"], now=now)

    @classmethod
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

    def save_broker_order_snapshot(self, row: dict) -> bool:
        payload = dict(row)
        raw = payload.pop("raw_broker_response", None) or payload.pop("raw_response", None)
        if raw:
            payload.update(self._raw_artifact(dict(raw)))
        key = str(payload.get("snapshot_hash") or "")
        if not key:
            raise ExecutionSafetyError("broker snapshot identity is required")
        with runtime_connection() as connection:
            old = self._record(connection, "broker_order_snapshot", key)
            if old is not None:
                if {k: v for k, v in old.items() if k != "observed_at"} != {k: v for k, v in payload.items() if k != "observed_at"}:
                    raise ExecutionSafetyError("broker snapshot conflicts with immutable identity")
                return False
            self._save_record(connection, "broker_order_snapshot", key, payload)
        return True

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
            existing = self._record(connection, "performance_snapshot", key)
            if existing is not None and existing != payload:
                raise ExecutionSafetyError("performance snapshot identity conflicts with stored snapshot")
            self._save_record(connection, "performance_snapshot", key, payload)
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


# ops가 execution 스키마를 직접 조회하지 않도록 계약을 여기서 소유한다.


def filled_order_costs(*, since_days: int = 180) -> list[dict]:
    """체결된 live 주문의 승인 기준가와 브로커 평균 체결가·수수료. 거래비용 보정의 원천이다."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
    with runtime_connection(read_only=True) as connection:
        orders = {
            str(row[0]): ExecutionRepository._decode(row[1])
            for row in connection.execute(
                "SELECT client_order_id,payload_json FROM orders WHERE status IN ('filled','partially_filled') "
                "AND submitted_at >= ?", (cutoff,),
            ).fetchall()
        }
        snapshots = [
            ExecutionRepository._decode(row[0])
            for row in connection.execute(
                "SELECT payload_json FROM runtime_records WHERE record_type='broker_order_snapshot'"
            ).fetchall()
        ]
    latest: dict[str, dict] = {}
    for snapshot in snapshots:
        key = str(snapshot.get("client_order_id") or "")
        if key in orders and str(snapshot.get("observed_at") or "") >= str(latest.get(key, {}).get("observed_at") or ""):
            latest[key] = snapshot
    return [
        {
            "ticker": orders[key].get("ticker"),
            "side": orders[key].get("side"),
            "reference_price": orders[key].get("reference_price"),
            "average_fill_price": snapshot.get("average_fill_price"),
            "filled_quantity": snapshot.get("filled_quantity"),
            "commission": snapshot.get("commission"),
            "observed_at": snapshot.get("observed_at"),
        }
        for key, snapshot in sorted(latest.items())
    ]


def latest_live_position_tickers(*, max_age_days: int = 7) -> list[str]:
    """가장 최근 live 계좌 snapshot 한 번에 잡힌 보유종목. 너무 오래된 snapshot은 쓰지 않는다."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    with runtime_connection(read_only=True) as connection:
        rows = connection.execute(
            "SELECT payload_json FROM runtime_records WHERE record_type='position_snapshot' "
            "AND json_extract(payload_json,'$.execution_mode')='live' "
            "AND json_extract(payload_json,'$.captured_at') >= ?",
            (cutoff,),
        ).fetchall()
    payloads = [ExecutionRepository._decode(row[0]) for row in rows]
    if not payloads:
        return []
    latest = max(str(row.get("captured_at") or "") for row in payloads)
    return sorted({
        str(row["ticker"]).upper()
        for row in payloads
        if str(row.get("captured_at") or "") == latest and float(row.get("quantity") or 0) > 0
    })


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
