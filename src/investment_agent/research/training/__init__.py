"""학습과 walk-forward 평가의 공통 호출 경계."""
from __future__ import annotations

from investment_agent.research.training.baseline import BaselineTrainingResult, train_baseline_dataset
from investment_agent.research.training.walk_forward import (
    WalkForwardSplit,
    make_purged_splits,
    make_walk_forward_splits,
)

__all__ = [
    "BaselineTrainingResult",
    "WalkForwardSplit",
    "make_purged_splits",
    "make_walk_forward_splits",
    "train_baseline_dataset",
]
