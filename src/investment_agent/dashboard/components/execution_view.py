"""실행 원장의 상태·체결 비용·정산 결과를 읽기 전용으로 요약한다."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


_OPEN_ORDER_STATES = {
    "planned",
    "submitted",
    "partially_filled",
    "outcome_unknown",
    "reconciling",
}
_INCIDENT_ORDER_STATES = {"rejected", "failed", "outcome_unknown", "reconciling"}


def _rows(payload: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    values = payload.get(key)
    if not isinstance(values, list):
        return []
    return [dict(row) for row in values if isinstance(row, Mapping)]


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def execution_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    """운영 화면의 핵심 지표를 저장 사실만으로 계산한다."""

    controls = _rows(payload, "control_state")
    intents = _rows(payload, "intents")
    approvals = _rows(payload, "approvals")
    orders = _rows(payload, "orders")
    fills = _rows(payload, "fills")
    tca_rows = _rows(payload, "tca_reports")
    reconciliations = _rows(payload, "reconciliations")
    control = controls[0] if controls else {}
    pending_approvals = sum(row.get("status") == "pending" for row in approvals)
    open_orders = sum(str(row.get("status") or "") in _OPEN_ORDER_STATES for row in orders)
    order_incidents = sum(
        str(row.get("status") or "") in _INCIDENT_ORDER_STATES for row in orders
    )
    notional = 0.0
    shortfall = 0.0
    for row in tca_rows:
        price = _number(row.get("decision_price"))
        quantity = _number(row.get("quantity"))
        cost = _number(row.get("implementation_shortfall"))
        if price is not None and quantity is not None and price > 0.0 and quantity > 0.0:
            notional += price * quantity
        if cost is not None:
            shortfall += cost
    shortfall_bps = shortfall / notional * 10_000.0 if notional > 0.0 else None
    latest_reconciliation = reconciliations[0] if reconciliations else {}
    return {
        "kill_switch_on": control.get("kill_switch_on"),
        "durable_lockdown_on": control.get("durable_lockdown_on"),
        "live_enabled": control.get("live_enabled"),
        "live_autonomy_enabled": control.get("live_autonomy_enabled"),
        "intent_count": len(intents),
        "pending_approval_count": pending_approvals,
        "order_count": len(orders),
        "open_order_count": open_orders,
        "order_incident_count": order_incidents,
        "fill_count": len(fills),
        "tca_count": len(tca_rows),
        "implementation_shortfall": shortfall if tca_rows else None,
        "implementation_shortfall_bps": shortfall_bps,
        "reconciliation_status": latest_reconciliation.get("status"),
        "reconciliation_mismatch_count": latest_reconciliation.get("mismatch_count"),
        "reconciliation_repair_count": latest_reconciliation.get("repair_count"),
    }


def trace_for_intent(payload: Mapping[str, Any], intent_id: str) -> dict[str, Any]:
    """한 execution intent에 연결된 승인·주문·체결·TCA 이벤트를 반환한다."""

    identity = str(intent_id or "").strip()
    intent = next(
        (row for row in _rows(payload, "intents") if str(row.get("intent_id")) == identity),
        {},
    )
    approvals = [
        row for row in _rows(payload, "approvals")
        if str(row.get("intent_id")) == identity
    ]
    orders = [
        row for row in _rows(payload, "orders")
        if str(row.get("intent_id")) == identity
    ]
    order_ids = {str(row.get("client_order_id")) for row in orders if row.get("client_order_id")}
    attempt_ids = {str(row.get("attempt_id")) for row in orders if row.get("attempt_id")}
    fills = [
        row for row in _rows(payload, "fills")
        if str(row.get("client_order_id")) in order_ids
    ]
    tca_rows = [
        row for row in _rows(payload, "tca_reports")
        if str(row.get("intent_id")) == identity
        or str(row.get("client_order_id")) in order_ids
    ]
    events = [
        row for row in _rows(payload, "order_events")
        if str(row.get("attempt_id")) in attempt_ids
    ]
    return {
        "intent": intent,
        "approval": approvals[0] if approvals else {},
        "orders": orders,
        "fills": fills,
        "tca_reports": tca_rows,
        "order_events": events,
    }


__all__ = ["execution_summary", "trace_for_intent"]
