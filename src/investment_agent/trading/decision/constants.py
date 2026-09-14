"""결정 계층이 공유하는 정책 식별자와 기대수익 기간."""
from __future__ import annotations

POLICY_KEY = "evidence-first"
POLICY_VERSION = 1

# 비중을 정하는 기대수익이 말하는 기간(거래일). LLM 의견·ML label·공분산·optimizer가 모두 이
# 한 값을 쓴다. 서로 다른 기간의 숫자를 한 목적함수에 넣으면 예외 없이 틀린 비중이 나온다 —
# 5일 수익과 20일 수익을 같은 단위로 더하는 셈이기 때문이다. 20인 이유: 공시·실적·수정치가
# 주가에 반영되는 속도에 맞고, 매매비용이 기대수익에 비해 과하게 커지지 않으며, 과거 재현으로
# label을 충분히 만들 수 있는 가장 긴 기간이다. 더 긴 기간(63일 이상)은 별도 모델로 추가한다.
SIGNAL_HORIZON_DAYS = 20
DEFAULT_HORIZON_DAYS = SIGNAL_HORIZON_DAYS
EVALUATION_HORIZONS = (5, 20, 60)

__all__ = [
    "DEFAULT_HORIZON_DAYS",
    "EVALUATION_HORIZONS",
    "POLICY_KEY",
    "POLICY_VERSION",
    "SIGNAL_HORIZON_DAYS",
]
