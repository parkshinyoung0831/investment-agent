"""시스템적 위험 상황에서 **신규 매수만** 자동으로 얼린다.

## 한도와 다른 층이다

`control`의 한도는 "이 주문 하나가 너무 큰가"를 본다. 여기는 "지금 시장이나 우리 상태가
주문을 낼 상황인가"를 본다. 둘을 한곳에 두면, 시장이 정상일 때의 한도와 급변할 때의
한도가 뒤섞인다.

## 매도는 막지 않는다

차단은 위험을 **늘리는** 행동에만 건다. 급락 중에 매도를 막으면 손실을 키운다.
그래서 이 판정은 신규 매수 경로에서만 부른다.

## 판단할 근거가 없으면 막지 않는다

VIX나 당일 손익을 못 읽었을 때 차단하면, 지표 수집이 실패한 날마다 거래가 멈춘다.
모르는 값은 `None`으로 들어오고 그 규칙은 건너뛴다 — 대신 **연속 실패**처럼 우리
스스로 아는 사실은 언제나 검사한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from investment_agent.platform.serialization import finite_float

STATES = ("NORMAL", "VOLATILITY_HALT", "DRAWDOWN_HALT", "FAILURE_LOCKOUT")


@dataclass(frozen=True)
class CircuitBreakerStatus:
    is_allowed: bool
    state: str
    reason: str | None

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise ValueError(f"unknown circuit breaker state: {self.state!r}")
        # 막았으면 왜 막았는지 말해야 한다. 이유 없는 차단은 운영자가 풀 수 없다.
        if not self.is_allowed and not (self.reason or "").strip():
            raise ValueError("a halted circuit breaker must give a reason")


@dataclass(frozen=True)
class CircuitBreakerPolicy:
    """사람이 정하는 차단 기준."""

    vix_halt_threshold: float = 35.0
    max_daily_drawdown: float = 0.03
    max_consecutive_failures: int = 3

    def __post_init__(self) -> None:
        # 하한을 두는 이유: 설정 오타로 0이 들어오면 모든 날이 차단된다.
        if self.vix_halt_threshold < 10.0:
            raise ValueError("vix_halt_threshold below 10 would halt on ordinary days")
        if not 0.005 <= self.max_daily_drawdown <= 1.0:
            raise ValueError("max_daily_drawdown must be between 0.5% and 100%")
        if self.max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be >= 1")


def evaluate(
    policy: CircuitBreakerPolicy,
    *,
    current_vix: float | None = None,
    daily_pnl_fraction: float | None = None,
    consecutive_order_failures: int = 0,
) -> CircuitBreakerStatus:
    """신규 매수를 허용할지 판정한다.

    순서가 의미를 갖는다. **우리 쪽 고장(연속 실패)을 먼저** 본다 — 주문이 계속
    거부되는 상황에서 시장 지표를 따지는 것은 순서가 뒤바뀐 것이고, 그 상태로 계속
    보내면 broker 쪽 제한에 걸린다.
    """
    failures = max(0, int(consecutive_order_failures))
    if failures >= policy.max_consecutive_failures:
        return CircuitBreakerStatus(
            is_allowed=False,
            state="FAILURE_LOCKOUT",
            reason=f"주문이 연속 {failures}회 실패해 신규 매수를 멈춥니다",
        )

    vix = finite_float(current_vix)
    if vix is not None and vix >= policy.vix_halt_threshold:
        return CircuitBreakerStatus(
            is_allowed=False,
            state="VOLATILITY_HALT",
            reason=f"VIX {vix:.1f}가 한계치 {policy.vix_halt_threshold:.1f}를 넘었습니다",
        )

    pnl = finite_float(daily_pnl_fraction)
    if pnl is not None and pnl <= -policy.max_daily_drawdown:
        return CircuitBreakerStatus(
            is_allowed=False,
            state="DRAWDOWN_HALT",
            reason=(
                f"당일 손실 {pnl * 100:.2f}%가 한계 "
                f"-{policy.max_daily_drawdown * 100:.1f}%를 넘었습니다"
            ),
        )

    return CircuitBreakerStatus(is_allowed=True, state="NORMAL", reason=None)


__all__ = ["CircuitBreakerPolicy", "CircuitBreakerStatus", "STATES", "evaluate"]
