"""Small data shapes used inside the strategy notification pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


Alloc = dict[str, float]


@dataclass(frozen=True)
class AllocationRow:
    allocation_id: str
    strategy_id: str
    apply_date: str
    mode: str
    alloc: Alloc
    signals: dict[str, Any]

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "AllocationRow":
        return cls(
            allocation_id=f"{row['strategy_id']}:{row['apply_date']}",
            strategy_id=str(row["strategy_id"]),
            apply_date=str(row["apply_date"]),
            mode=str(row.get("mode") or ""),
            alloc={str(k): float(v) for k, v in (row.get("weights") or {}).items()},
            signals=dict(row.get("signals") or {}),
        )


@dataclass(frozen=True)
class AllocationDelta:
    from_weight: float
    to_weight: float
    delta: float


@dataclass(frozen=True)
class AllocationChange:
    added: Alloc
    removed: Alloc
    changed: dict[str, AllocationDelta]
    turnover_pct: float
    is_first: bool

    @property
    def has_changes(self) -> bool:
        return bool(self.is_first or self.added or self.removed or self.changed)


@dataclass(frozen=True)
class StrategyNotification:
    allocation_id: str
    strategy_id: str
    apply_date: str
    has_changes: bool
    turnover_pct: float
    embed: dict[str, Any]
