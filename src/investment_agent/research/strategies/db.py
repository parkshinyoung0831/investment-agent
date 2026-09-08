"""전략 계산 결과를 Research 로컬 저장소에 기록하는 경계."""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone

from investment_agent.research.storage.repository import ResearchStore

_TICKER = re.compile(r"^[A-Z0-9-]{1,12}$")


def _store() -> ResearchStore:
    return ResearchStore()


def _validated_weights(alloc: dict) -> dict[str, float]:
    if not isinstance(alloc, dict) or not alloc:
        raise ValueError("allocation weights must be a non-empty mapping")
    normalized: dict[str, float] = {}
    for raw_symbol, raw_weight in alloc.items():
        symbol = str(raw_symbol).strip().upper()
        if not _TICKER.fullmatch(symbol) or isinstance(raw_weight, bool):
            raise ValueError(f"invalid allocation entry: {raw_symbol!r}")
        weight = float(raw_weight)
        if not math.isfinite(weight) or not 0 < weight <= 1:
            raise ValueError(f"invalid allocation weight for {symbol}: {raw_weight!r}")
        if symbol in normalized:
            raise ValueError(f"duplicate normalized allocation symbol: {symbol}")
        normalized[symbol] = weight
    total = math.fsum(normalized.values())
    if not math.isclose(total, 1.0, rel_tol=0, abs_tol=1e-6):
        raise ValueError(f"allocation weights must sum to 1 (actual={total:.12g})")
    return normalized


def _validated_signals(signals: dict | None) -> dict:
    value = signals or {}
    if not isinstance(value, dict):
        raise TypeError("allocation signals must be an object")
    return value


def allocation_strategy_ids(apply_date: date) -> set[str]:
    return _store().allocation_strategy_ids(apply_date)


def mark_allocations_sent(apply_date: date) -> int:
    return _store().mark_allocations_sent(
        apply_date, sent_at=datetime.now(timezone.utc).isoformat()
    )


def upsert_allocation(
    strategy_id: str,
    decision_date: date,
    apply_date: date,
    mode: str,
    alloc: dict,
    signals: dict | None = None,
    *,
    mark_sent: bool = False,
) -> dict:
    if not str(mode).strip():
        raise ValueError("allocation mode must not be empty")
    payload = {
        "strategy_id": strategy_id,
        "decision_date": str(decision_date),
        "apply_date": str(apply_date),
        "mode": str(mode).strip(),
        "weights": _validated_weights(alloc),
        "signals": _validated_signals(signals),
    }
    del mark_sent
    return _store().upsert_allocation(payload)


def delete_allocations_before(cutoff_date: str) -> int:
    return _store().delete_allocations_before(cutoff_date)


def latest_allocation_per_strategy() -> list[dict]:
    rows = _store().allocations()
    latest: dict[str, dict] = {}
    for row in sorted(rows, key=lambda value: str(value["apply_date"]), reverse=True):
        latest.setdefault(str(row["strategy_id"]), row)
    return [latest[key] for key in sorted(latest)]


__all__ = [
    "allocation_strategy_ids", "delete_allocations_before", "latest_allocation_per_strategy",
    "mark_allocations_sent", "upsert_allocation",
]
