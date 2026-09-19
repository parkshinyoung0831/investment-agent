"""Metadata validation shared by operational stage adapters."""
from __future__ import annotations

import re

from investment_agent.operations.harness.contracts import StageContext


_ID_PATTERNS = {
    "batch_id": re.compile(r"^signal_batch_[0-9a-f]{24}$"),
    "target_id": re.compile(r"^system_target_[0-9a-f]{24}$"),
    "risk_decision_id": re.compile(r"^risk_[0-9a-f]{24}$"),
    "intent_id": re.compile(r"^intent_[0-9a-f]{24}$"),
    "approval_id": re.compile(r"^approval_[0-9a-f]{32}$"),
}


def metadata_id(
    context: StageContext,
    *,
    stage_id: str,
    key: str,
    required: bool = True,
) -> str | None:
    value = context.completed_metadata.get(stage_id, {}).get(key)
    if value is None and not required:
        return None
    text = str(value or "")
    if _ID_PATTERNS[key].fullmatch(text) is None:
        raise RuntimeError(f"prior {key} is missing or invalid")
    return text


__all__ = ["_ID_PATTERNS", "metadata_id"]
