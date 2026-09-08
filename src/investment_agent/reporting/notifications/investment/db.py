"""자동매매 보고서의 로컬 판단·실행 원장 조회 경계."""
from __future__ import annotations

from typing import Any

from investment_agent.platform.db.postgres import sb, select_paged_in_chunks
from investment_agent.platform.logging import get_logger
from investment_agent.reporting.services.investment import build_decision_case_read_model
from investment_agent.reporting.readers.runtime import read_runtime_rows

SCHEMA_UNIVERSE = "universe"
T_SECURITIES = "securities"

log = get_logger(__name__)


def latest_portfolio() -> dict[str, Any] | None:
    """가장 최근 제안과 그 risk 판정·실행을 로컬 원장에서 묶는다."""
    proposals = read_runtime_rows("portfolio_proposals")
    if not proposals:
        return None
    proposal = max(proposals, key=lambda row: str(row.get("as_of_at") or ""))
    risks = [row for row in read_runtime_rows("risk_decisions")
             if row.get("proposal_id") == proposal.get("proposal_id")]
    runs = [row for row in read_runtime_rows("decision_runs")
            if row.get("run_id") == proposal.get("run_id")]
    if not risks or not runs:
        log.info(
            "portfolio proposal has no risk decision or run yet proposal_id=%s",
            proposal.get("proposal_id"),
        )
        return None
    risk = max(risks, key=lambda row: str(row.get("decided_at") or ""))
    return {"proposal": dict(proposal), "risk": dict(risk), "run": dict(runs[0])}


def top_candidates(run_id: str, *, limit: int) -> list[dict[str, Any]]:
    """한 실행의 완료 판단을 신뢰도 순으로 상위 N개 돌려준다."""
    if limit < 1:
        return []
    rows = [row for row in read_runtime_rows("security_decisions")
            if row.get("run_id") == run_id and row.get("status") == "completed"]
    security_ids = sorted({int(row["security_id"]) for row in rows
                           if row.get("security_id") is not None})
    securities = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES)
        .select("security_id,ticker").in_("security_id", chunk),
        security_ids,
        order_by="security_id",
    ) if security_ids else []
    ticker_by_id = {int(row["security_id"]): row.get("ticker") for row in securities}
    candidates = []
    for source in rows:
        if not source.get("final_decision"):
            continue
        row = dict(source)
        row["ticker"] = ticker_by_id.get(int(row["security_id"]))
        candidates.append(build_decision_case_read_model(row))
    candidates.sort(
        key=lambda row: float((row.get("final_decision") or {}).get("confidence") or 0.0),
        reverse=True,
    )
    return candidates[:limit]


def recent_orders(*, since_at: str) -> list[dict[str, Any]]:
    """지정 시각 이후 갱신된 로컬 주문과 체결·실행 대상을 모은다."""
    orders = [row for row in read_runtime_rows("orders")
              if str(row.get("updated_at") or "") >= since_at]
    if not orders:
        return []
    order_ids = {str(row["client_order_id"]) for row in orders}
    intent_ids = {str(row["intent_id"]) for row in orders}
    fills = [row for row in read_runtime_rows("fills")
             if str(row.get("client_order_id") or "") in order_ids]
    intents = [row for row in read_runtime_rows("intents")
               if str(row.get("intent_id") or "") in intent_ids]
    mode_by_intent = {str(row["intent_id"]): str(row["execution_mode"]) for row in intents}
    fills_by_order: dict[str, list[dict[str, Any]]] = {}
    for fill in fills:
        fills_by_order.setdefault(str(fill.get("client_order_id") or ""), []).append(fill)
    return [{
        "order": dict(order),
        "fills": fills_by_order.get(str(order["client_order_id"]), []),
        "execution_mode": mode_by_intent.get(str(order["intent_id"]), "unknown"),
    } for order in orders]


__all__ = ["latest_portfolio", "recent_orders", "top_candidates"]
