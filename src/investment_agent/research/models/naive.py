"""Naive를 모든 challenger의 가장 단순한 기준으로 노출한다."""
from __future__ import annotations

from typing import Any

from investment_agent.research.models.baselines import fit_baseline


def fit(**kwargs: Any):
    return fit_baseline("naive", **kwargs)


__all__ = ["fit"]
