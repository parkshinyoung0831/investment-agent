"""AI 승인 화면이 읽는 종목별 판단·제안·승인 read model."""
from __future__ import annotations

from investment_agent.reporting.readers.select_only import (
    DB_SOURCE,
    SCHEMA_UNIVERSE,
    T_SECURITIES,
    latest_at,
    open_gateway,
    preflight,
)

import re
from typing import Any
from investment_agent.platform.cache import cache_data
from investment_agent.reporting.models import DataResult, public_exception_message
from investment_agent.reporting.services.investment import (
    build_decision_cases_read_model,
)
from investment_agent.reporting.readers.runtime import read_local_rows, read_runtime_rows

@cache_data(ttl="5m", max_entries=64)
def load_ai_data(ticker: str) -> DataResult:
    """선택 종목의 v1 판단·시그널·포트폴리오·승인 사실을 읽는다."""

    symbol = str(ticker or "").strip().upper()
    source = f"{DB_SOURCE} · reporting/execution"
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,14}", symbol):
        return DataResult.blocked(source=source, message="유효한 종목 코드가 필요합니다.")
    blocked = preflight()
    if blocked:
        return blocked
    payload: dict[str, list[dict[str, Any]]] = {
        "cases": [],
        "signals": [],
        "proposals": [],
        "risk_decisions": [],
        "approvals": [],
    }
    try:
        gateway = open_gateway()
        case_rows = [
            row for row in read_local_rows("security_decisions", canonical_db=gateway)
            if row.get("ticker") == symbol
        ]
        case_rows.sort(key=lambda row: str(row.get("as_of_at") or ""), reverse=True)
        case_rows = case_rows[:12]
        cases = build_decision_cases_read_model(case_rows)
        securities = gateway.select_rows(
            schema=SCHEMA_UNIVERSE,
            table=T_SECURITIES,
            columns="security_id,ticker",
            equal={"ticker": symbol, "is_active_listing": True},
            limit=1,
        )
        security_id = securities[0].get("security_id") if securities else None
        signals = [row for row in read_runtime_rows("signals")
                   if security_id is not None and row.get("security_id") == security_id]
        signals.sort(key=lambda row: str(row.get("recorded_at") or ""), reverse=True)
        signals = signals[:40]
        proposal_rows = read_runtime_rows("portfolio_proposals")
        proposal_rows.sort(key=lambda row: str(row.get("as_of_at") or ""), reverse=True)
        proposal_rows = proposal_rows[:80]
        case_keys = {str(row.get("case_key")) for row in cases if row.get("case_key")}
        proposals = [
            row
            for row in proposal_rows
            if symbol in (row.get("weights") or {})
            or bool(case_keys.intersection(str(item) for item in (row.get("case_keys") or [])))
        ]
        proposal_ids = {
            str(row.get("proposal_id")) for row in proposals if row.get("proposal_id")
        }
        risk_rows = read_runtime_rows("risk_decisions")
        risk_rows.sort(key=lambda row: str(row.get("decided_at") or ""), reverse=True)
        risk_rows = risk_rows[:120]
        risk_decisions = [
            row
            for row in risk_rows
            if str(row.get("proposal_id")) in proposal_ids
            or symbol in (row.get("approved_weights") or {})
        ]
        approvals = [row for row in read_runtime_rows("approvals")
                     if str(row.get("proposal_id")) in proposal_ids]
        approvals.sort(key=lambda row: str(row.get("requested_at") or row.get("created_at") or ""), reverse=True)
        approvals = approvals[:80]
        payload = {
            "cases": cases,
            "signals": signals,
            "proposals": proposals,
            "risk_decisions": risk_decisions,
            "approvals": approvals,
        }
        observed_at = latest_at(
            (
                (cases, ("as_of_at", "created_at")),
                (signals, ("recorded_at", "created_at")),
                (proposals, ("as_of_at", "created_at")),
                (risk_decisions, ("decided_at",)),
                (approvals, ("updated_at", "requested_at")),
            )
        )
        if not any(payload.values()):
            return DataResult.empty(
                source=source,
                value=payload,
                observed_at=observed_at,
                message=f"{symbol}의 저장된 AI 판단이 없습니다.",
            )
        return DataResult.ok(value=payload, source=source, observed_at=observed_at)
    except Exception as error:
        return DataResult.error(
            source=source,
            value=payload,
            message=public_exception_message("AI 투자 DB 조회에 실패했습니다.", error),
        )
