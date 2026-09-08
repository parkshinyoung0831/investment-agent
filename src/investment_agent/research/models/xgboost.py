"""XGBoost challenger adapter. 실제 import는 fit 시점에만 일어난다."""
from __future__ import annotations

from typing import Any

from investment_agent.research.models.baselines import fit_baseline


def fit(**kwargs: Any):
    return fit_baseline("xgboost", **kwargs)


__all__ = ["fit"]
