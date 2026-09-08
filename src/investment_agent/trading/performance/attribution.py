"""Total PnL을 selection·allocation·timing·risk·execution으로 분해한다."""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from investment_agent.platform.serialization import ContractError, canonical_json, json_value, parse_datetime

_COMPONENTS = (
    "market_effect",
    "selection_alpha",
    "allocation_effect",
    "timing_effect",
    "risk_overlay_effect",
    "execution_slippage",
    "fees",
)


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ContractError(f"{name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ContractError(f"{name} must be finite")
    return parsed


@dataclass(frozen=True)
class AttributionReport:
    """합계 identity를 보존하는 모듈별 손익 보고서."""

    attribution_id: str
    total_pnl: float
    market_effect: float
    selection_alpha: float
    allocation_effect: float
    timing_effect: float
    risk_overlay_effect: float
    execution_slippage: float
    fees: float
    residual: float
    created_at: str
    ticker: str | None = None
    outcome_id: str | None = None
    proposal_id: str | None = None
    intent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("total_pnl", *_COMPONENTS, "residual"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        expected = sum(float(getattr(self, name)) for name in (*_COMPONENTS, "residual"))
        if not math.isclose(self.total_pnl, expected, rel_tol=1e-10, abs_tol=1e-8):
            raise ContractError("attribution components do not reconcile to total_pnl")
        created_at = parse_datetime(self.created_at).isoformat()
        ticker = None if self.ticker is None else str(self.ticker).upper().strip() or None
        if not str(self.attribution_id).strip():
            raise ContractError("attribution_id is required")
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


def build_attribution_report(
    *,
    total_pnl: float,
    components: Mapping[str, float] | None = None,
    ticker: str | None = None,
    outcome_id: str | None = None,
    proposal_id: str | None = None,
    intent_id: str | None = None,
    created_at: str,
    residual: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> AttributionReport:
    """누락된 모듈은 0으로 두고 residual로 회계 identity를 명시한다."""
    values = {name: _finite((components or {}).get(name, 0.0), name) for name in _COMPONENTS}
    total = _finite(total_pnl, "total_pnl")
    computed_residual = total - sum(values.values()) if residual is None else _finite(residual, "residual")
    identity = {
        "total_pnl": total,
        "components": values,
        "residual": computed_residual,
        "ticker": ticker,
        "outcome_id": outcome_id,
        "proposal_id": proposal_id,
        "intent_id": intent_id,
        "created_at": parse_datetime(created_at).isoformat(),
    }
    attribution_id = "attribution_" + hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:24]
    return AttributionReport(
        attribution_id=attribution_id,
        total_pnl=total,
        **values,
        residual=computed_residual,
        created_at=created_at,
        ticker=ticker,
        outcome_id=outcome_id,
        proposal_id=proposal_id,
        intent_id=intent_id,
        metadata=metadata or {},
    )


__all__ = ["AttributionReport", "build_attribution_report"]
