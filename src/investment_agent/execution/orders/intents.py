"""판단 계층이 실행 계층에 넘길 수 있는 **유일한** 물건.

## 왜 execution이 이 모양을 소유하나

`trading`이 만든 것을 `execution`이 그대로 받아들이면, 판단 쪽 자료구조가 바뀔 때마다
실행 경계가 함께 흔들린다. 그러면 "지금 무엇이 주문으로 나갈 수 있는가"를 판단 코드까지
읽어야만 알 수 있다.

그래서 실행 계층이 **받아들일 모양을 스스로 선언**하고, 그 밖의 것은 받지 않는다.
`trading`은 승인된 비중을 넘겨줄 뿐이고 이 dataclass를 import하지 않는다.

## 의도에는 유효 기간이 있다

`not_before`와 `expires_at`이 없으면, 며칠 전에 승인된 의도가 오늘 주문으로 나갈 수
있다. 그 사이에 가격도 판단 근거도 달라졌는데 승인만 살아 있는 상태다.

## 목표에 없는 종목을 0으로 추론하지 않는다

`target_weights`에 없는 보유는 "팔라"가 아니라 "이번 판단의 대상이 아니다"다. 명시적인
0 비중만 청산이다. 이 규칙이 없으면 일부 종목만 분석한 배치가 나머지 보유를 전량
매도한다.

## 현금을 포함한 합이 1이어야 한다

그래야 "나머지는 현금"이 암묵적 규칙이 아니라 적힌 값이 된다. 합을 요구하지 않으면
10%만 적힌 의도가 통과하고, 나머지 90%를 어떻게 다룰지는 아무도 말하지 않은 채
계획 단계가 결정하게 된다.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from investment_agent.platform.clock import ensure_aware, utc_now
from investment_agent.platform.serialization import parse_datetime

CASH_SYMBOL = "CASH"

TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,11}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

EXECUTION_MODES = ("paper", "live")
INTENT_STATUSES = (
    "approved", "claimed", "executing", "completed", "failed", "expired", "cancelled",
)
# 아직 실행할 수 있는 상태. 나머지는 이미 끝났거나 취소된 것이다.
EXECUTABLE_STATUSES = ("approved", "claimed")

# 비중 합계 비교의 여유. 부동소수 누적 오차만 흡수할 만큼만 둔다.
WEIGHT_TOLERANCE = 1e-8


class IntentError(ValueError):
    """실행 의도가 계약을 어겼다. **주문을 만들지 않는다.**"""


def validated_weights(weights: Mapping[str, Any], *, require_total: bool = True) -> dict[str, float]:
    """비중을 검증하고 현금을 포함한 정렬 사본을 돌려준다.

    **현금을 포함한 합이 1이어야 한다.** 이것이 이 함수의 핵심이다 — 없으면 "10% AAPL"
    같은 의도가 나머지 90%를 말하지 않은 채 통과하고, 계획 단계가 그것을 조용히
    현금으로 읽는다. 그 규칙은 어디에도 적혀 있지 않으므로, 여기서 명시를 요구한다.

    읽을 수 없거나 음수인 값은 0으로 바꾸지 않고 **거절한다.** 0으로 바꾸면 그 종목이
    청산 대상이 되는데, 그것은 데이터 오류가 매도 주문으로 바뀌는 길이다.
    """
    if not isinstance(weights, Mapping) or not weights:
        raise IntentError("weights must be a non-empty mapping")
    parsed: dict[str, float] = {}
    for raw_symbol, raw_value in weights.items():
        symbol = str(raw_symbol).strip().upper()
        if symbol != CASH_SYMBOL and not TICKER_RE.fullmatch(symbol):
            raise IntentError(f"invalid symbol in target weights: {raw_symbol!r}")
        if symbol in parsed:
            raise IntentError(f"duplicate symbol in target weights: {symbol}")
        # bool을 막는다. 파이썬에서 float(True)는 1.0이라 플래그가 100% 비중이 된다.
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise IntentError(f"{symbol}: weight must be numeric")
        value = float(raw_value)
        if not math.isfinite(value) or value < 0.0 or value > 1.0:
            # 공매도와 레버리지는 실행 계층이 다루지 않는다.
            raise IntentError(f"{symbol}: weight must be between 0 and 1")
        parsed[symbol] = value
    parsed.setdefault(CASH_SYMBOL, 0.0)
    total = math.fsum(parsed.values())
    if require_total and not math.isclose(total, 1.0, abs_tol=WEIGHT_TOLERANCE):
        raise IntentError(f"weights including {CASH_SYMBOL} must sum to 1, got {total:.12f}")
    return {symbol: parsed[symbol] for symbol in sorted(parsed)}


@dataclass(frozen=True)
class ExecutionIntent:
    intent_id: str
    risk_decision_id: str
    proposal_id: str
    execution_mode: str
    target_weights: dict[str, float]
    # 이 의도를 만든 입력의 지문. 승인 이후 입력이 달라졌는지 확인하는 데 쓴다.
    input_hash: str
    not_before: datetime
    expires_at: datetime
    status: str = "approved"

    def __post_init__(self) -> None:
        if not str(self.intent_id).strip():
            raise IntentError("intent_id is required")
        if self.execution_mode not in EXECUTION_MODES:
            raise IntentError(f"unknown execution_mode: {self.execution_mode!r}")
        if self.status not in INTENT_STATUSES:
            raise IntentError(f"unknown intent status: {self.status!r}")
        if not SHA256_RE.fullmatch(str(self.input_hash)):
            raise IntentError("input_hash must be a sha256 hex digest")
        start = parse_datetime(self.not_before)
        end = parse_datetime(self.expires_at)
        if end <= start:
            raise IntentError("expires_at must be after not_before")
        object.__setattr__(self, "not_before", start)
        object.__setattr__(self, "expires_at", end)
        object.__setattr__(self, "target_weights", validated_weights(self.target_weights))

    def assert_executable(
        self, *, now: datetime | None = None, required_mode: str = "paper"
    ) -> None:
        """지금 이 의도로 주문을 만들어도 되는가. 아니면 예외.

        `required_mode`를 인자로 받는 이유: 부르는 쪽이 **자기가 어느 경로인지 명시**해야
        한다. 기본값이 `paper`인 것도 같은 이유다 — 아무것도 안 적으면 종이로 간다.
        """
        current = ensure_aware(now or utc_now())
        if self.execution_mode != required_mode:
            raise IntentError(
                f"intent execution_mode {self.execution_mode!r} does not match "
                f"required {required_mode!r}"
            )
        if self.status not in EXECUTABLE_STATUSES:
            raise IntentError(f"intent is not executable: {self.status}")
        if current < ensure_aware(self.not_before):
            raise IntentError("intent not_before is in the future")
        if current >= ensure_aware(self.expires_at):
            raise IntentError("intent has expired")

    @property
    def risky_symbols(self) -> list[str]:
        """현금을 뺀 대상 종목. 주문 계획이 도는 목록이다."""
        return sorted(set(self.target_weights) - {CASH_SYMBOL})

    def as_row(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "risk_decision_id": self.risk_decision_id,
            "proposal_id": self.proposal_id,
            "execution_mode": self.execution_mode,
            "target_weights": dict(self.target_weights),
            "input_hash": self.input_hash,
            "not_before": ensure_aware(self.not_before).isoformat(),
            "expires_at": ensure_aware(self.expires_at).isoformat(),
            "status": self.status,
        }


__all__ = [
    "CASH_SYMBOL",
    "EXECUTABLE_STATUSES",
    "EXECUTION_MODES",
    "ExecutionIntent",
    "INTENT_STATUSES",
    "IntentError",
    "SHA256_RE",
    "WEIGHT_TOLERANCE",
    "TICKER_RE",
    "validated_weights",
]
