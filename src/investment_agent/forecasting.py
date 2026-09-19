"""Research 예측과 Trading 판단이 공유하는 금융 도메인 계약."""
from __future__ import annotations

# LLM 의견·ML label·공분산·optimizer가 같은 기간의 기대수익을 다루게 한다.
# 서로 다른 기간의 숫자를 한 목적함수에 넣으면 단위가 달라진다. 20거래일은
# 공시·실적·수정치의 반영 속도와 거래비용, historical label 표본 수의 균형이다.
SIGNAL_HORIZON_DAYS = 20

__all__ = ["SIGNAL_HORIZON_DAYS"]
