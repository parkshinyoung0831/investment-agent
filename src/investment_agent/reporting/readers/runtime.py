"""화면의 로컬 상태 조회. SELECT만 사용하고 파일·스키마를 만들지 않는다."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from investment_agent.platform.db.sqlite import runtime_connection

LOCAL_VIEWS = frozenset({"execution_control_state", "execution_intents", "execution_approvals",
    "execution_orders", "execution_fills", "current_model_stage", "security_decisions",
    "portfolio_decisions", "notification_failures", "job_health"})
SCHEMA_UNIVERSE = "universe"
T_SECURITIES = "securities"
T_CONTROL = "execution_control"
T_INTENTS = "intents"
T_APPROVALS = "approvals"
T_ORDERS = "orders"
T_FILLS = "fills"
T_OUTBOX = "notification_outbox"
T_DELIVERIES = "notification_deliveries"
T_MODELS = "model_versions"
T_PROMOTIONS = "model_promotions"
T_SECURITY_DECISIONS = "security_decisions"
T_DECISION_EVIDENCE = "decision_evidence"
T_PORTFOLIO_DECISIONS = "portfolio_decisions"
T_PROPOSALS = "portfolio_proposals"
T_RISK_DECISIONS = "risk_decisions"
T_JOB_STATE = "local_job_state"
T_ACCOUNT_SNAPSHOTS = "account_snapshots"

_PLAIN_DATASETS = frozenset({
    "decision_runs", "security_decisions", "signal_runs", "signals", "portfolio_proposals",
    "risk_decisions", "model_promotions",
})
_PAYLOAD_DATASETS = frozenset({
    "intents", "approvals", "orders", "fills", "notification_outbox",
})


def _rows(connection, sql, params=()):
    cursor = connection.execute(sql, params)
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _table_rows(connection, table):
    types = {item[1]: str(item[2]).upper() for item in connection.execute(f"PRAGMA table_info({table})")}
    return [{key: json.loads(value) if value is not None and types[key] == "JSON"
             else bool(value) if value is not None and types[key] == "BOOLEAN" else value
             for key, value in row.items()} for row in _rows(connection, f"SELECT * FROM {table}")]


def _payload_rows(connection, table: str, payload_column: str = "payload_json") -> list[dict]:
    """고정 컬럼과 JSON payload를 합치되 원장 컬럼을 최종 사실로 둔다."""
    output = []
    for row in _rows(connection, f"SELECT * FROM {table}"):
        payload = json.loads(row.pop(payload_column))
        if not isinstance(payload, dict):
            raise ValueError(f"{table} payload must be an object")
        output.append({**payload, **row})
    return output


def read_runtime_rows(dataset: str) -> list[dict]:
    """Dashboard가 사용하는 로컬 원장 데이터셋만 읽는다.

    호출자가 table 이름을 임의로 전달해 SQL을 만들 수 없도록 allowlist를 먼저
    검사한다. 이 함수는 읽기 전용 연결만 열며 빈 파일이나 낡은 스키마를 만들거나
    고치지 않는다.
    """
    allowed = _PLAIN_DATASETS | _PAYLOAD_DATASETS | {
        "execution_control", "order_events", "reconciliation_runs",
        "account_snapshots",
    }
    if dataset not in allowed:
        raise ValueError("unknown runtime reporting dataset")
    with runtime_connection(read_only=True) as connection:
        if dataset in _PLAIN_DATASETS:
            return _table_rows(connection, dataset)
        if dataset in _PAYLOAD_DATASETS:
            return _payload_rows(connection, dataset)
        if dataset == "execution_control":
            return [json.loads(row[0]) for row in connection.execute(
                f"SELECT control_value FROM {T_CONTROL} ORDER BY updated_at"
            )]
        if dataset == "order_events":
            rows = _payload_rows(connection, "order_events", "detail_json")
            for row in rows:
                row["status"] = row.pop("event_type")
            return rows
        if dataset == "reconciliation_runs":
            rows = _payload_rows(connection, "reconciliation_runs")
            for row in rows:
                row["completed_at"] = row.pop("finished_at")
            return rows
        if dataset == "account_snapshots":
            return _table_rows(connection, T_ACCOUNT_SNAPSHOTS)
    raise AssertionError("unhandled runtime reporting dataset")


def read_local_rows(view: str, *, canonical_db=None) -> list[dict]:
    if view not in LOCAL_VIEWS:
        raise ValueError("unknown local reporting view")
    with runtime_connection(read_only=True) as connection:
        if view == "execution_control_state":
            return [json.loads(row[0]) for row in connection.execute(f"SELECT control_value FROM {T_CONTROL}")]
        table = {"execution_intents": T_INTENTS, "execution_approvals": T_APPROVALS,
                 "execution_orders": T_ORDERS, "execution_fills": T_FILLS}.get(view)
        if table:
            output = []
            for row in _rows(connection, f"SELECT * FROM {table}"):
                payload = json.loads(row.pop("payload_json"))
                output.append({**payload, **row})
            return output
        if view == "notification_failures":
            rows = _rows(connection, f"SELECT o.producer,o.notification_key,o.kind,o.entity_key,o.status,o.attempt_count,d.failure_reason,d.attempted_at FROM {T_OUTBOX} o JOIN {T_DELIVERIES} d USING(producer,notification_key) WHERE o.status IN ('pending','failed','abandoned') AND d.status='failed'")
            return [{**row, "channel": "discord"} for row in rows]
        if view == "current_model_stage":
            models = _table_rows(connection, T_MODELS)
            promotions = _table_rows(connection, T_PROMOTIONS)
            for model in models:
                approved = [row for row in promotions if row["artifact_id"] == model["artifact_id"] and row["status"] == "approved"]
                latest = max(approved, key=lambda row: (row["approved_at"], row["promotion_id"])) if approved else {}
                model.update(stage=latest.get("to_stage", "shadow"), current_promotion_id=latest.get("promotion_id"), stage_changed_at=latest.get("approved_at"))
            return models
        if view == "security_decisions":
            decisions = _table_rows(connection, T_SECURITY_DECISIONS)
            evidence = _table_rows(connection, T_DECISION_EVIDENCE)
            security_ids = sorted({row["security_id"] for row in decisions})
            if security_ids and canonical_db is None:
                raise RuntimeError("canonical security identity reader is unavailable")
            if security_ids and hasattr(canonical_db, "select_in_chunks"):
                identities = canonical_db.select_in_chunks(
                    schema=SCHEMA_UNIVERSE, table=T_SECURITIES,
                    columns="security_id,ticker", filter_column="security_id",
                    values=security_ids, order_by="security_id",
                )
            elif security_ids and hasattr(canonical_db, "select_rows"):
                identities = canonical_db.select_rows(
                    schema=SCHEMA_UNIVERSE, table=T_SECURITIES,
                    columns="security_id,ticker", in_values={"security_id": security_ids},
                    order=(("security_id", False),), limit=20_000,
                )
            else:
                identities = []
            tickers = {row["security_id"]: row["ticker"] for row in identities}
            if set(security_ids) - set(tickers):
                raise RuntimeError("local decisions reference unknown securities")
            for decision in decisions:
                bundle = next((row for row in evidence if row["case_key"] == decision["case_key"] and row["evidence_kind"] == "bundle"), {})
                decision.update(ticker=tickers[decision["security_id"]], evidence_uri=bundle.get("artifact_uri"), evidence_sha256=bundle.get("sha256"), evidence_byte_size=bundle.get("byte_size"), evidence_schema_version=bundle.get("schema_version"))
            return decisions
        if view == "portfolio_decisions":
            decisions = _table_rows(connection, T_PORTFOLIO_DECISIONS)
            proposals = {row["proposal_id"]: row for row in _table_rows(connection, T_PROPOSALS)}
            risks = {row["risk_decision_id"]: row for row in _table_rows(connection, T_RISK_DECISIONS)}
            for row in decisions:
                proposal, risk = proposals[row["proposal_id"]], risks[row["risk_decision_id"]]
                row.update(as_of_at=proposal["as_of_at"], stage=proposal["stage"], source_type=proposal["source_type"], confidence=proposal["confidence"], risk_approved=risk["is_approved"], approved_weights=risk["approved_weights"], violations=risk["violations"])
            return decisions
        if view == "job_health":
            now = datetime.now(timezone.utc)
            output = []
            for row in _rows(connection, f"SELECT * FROM {T_JOB_STATE}"):
                succeeded = row["last_finished_at"] if row["last_status"] == "ok" else None
                parsed = datetime.fromisoformat(str(succeeded).replace("Z", "+00:00")) if succeeded else None
                age = max(0, int((now - parsed.astimezone(timezone.utc)).total_seconds())) if parsed else None
                output.append({"job_key": row["job_name"], "runner": "local", "last_status": row["last_status"],
                    "last_run_at": row["last_started_at"], "last_success_at": succeeded,
                    "items_processed": None, "items_failed": None, "last_detail": row["detail"],
                    "seconds_since_success": age, "is_overdue": None})
            return output
        raise AssertionError("unhandled local reporting view")


__all__ = ["LOCAL_VIEWS", "read_local_rows", "read_runtime_rows"]
