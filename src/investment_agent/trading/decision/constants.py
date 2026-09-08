"""결정 계층이 공유하는 정책 식별자와 기본 horizon."""
from __future__ import annotations

POLICY_KEY = "evidence-first"
POLICY_VERSION = 1
DEFAULT_HORIZON_DAYS = 20
EVALUATION_HORIZONS = (5, 20, 60)

__all__ = [
    "DEFAULT_HORIZON_DAYS",
    "EVALUATION_HORIZONS",
    "POLICY_KEY",
    "POLICY_VERSION",
]
