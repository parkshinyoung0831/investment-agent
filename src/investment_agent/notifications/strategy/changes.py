"""Allocation change analysis for strategy notifications."""
from __future__ import annotations

from .models import AllocationChange, AllocationDelta


def analyze_allocation_change(
    curr_alloc: dict[str, float],
    prev_alloc: dict[str, float] | None,
) -> AllocationChange:
    added: dict[str, float] = {}
    removed: dict[str, float] = {}
    changed: dict[str, AllocationDelta] = {}
    turnover = 0.0

    for ticker in set((prev_alloc or {}).keys()) | set(curr_alloc.keys()):
        prev = float((prev_alloc or {}).get(ticker, 0) or 0)
        curr = float(curr_alloc.get(ticker, 0) or 0)
        delta = curr - prev
        turnover += abs(delta)
        if prev == 0 and curr > 0:
            added[ticker] = curr
        elif curr == 0 and prev > 0:
            removed[ticker] = prev
        elif abs(delta) > 1e-6:
            changed[ticker] = AllocationDelta(
                from_weight=prev,
                to_weight=curr,
                delta=delta,
            )

    is_first = prev_alloc is None
    turnover_pct = 0.0 if is_first else round(turnover * 50, 1)
    return AllocationChange(
        added=added,
        removed=removed,
        changed=changed,
        turnover_pct=turnover_pct,
        is_first=is_first,
    )
