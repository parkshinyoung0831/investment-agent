"""가볍고 설명 가능한 Ridge baseline."""
from __future__ import annotations

from typing import Any

from investment_agent.research.models.baselines import fit_baseline


def fit(**kwargs: Any):
    return fit_baseline("ridge", **kwargs)


__all__ = ["fit"]
