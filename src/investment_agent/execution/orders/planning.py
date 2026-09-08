"""목표 비중과 계좌 현황의 차이를 **결정적인** 주문 목록으로 바꾼다.

## 같은 입력이면 같은 주문이 나와야 한다

`client_order_id`가 입력에서 계산되므로, 같은 계획을 두 번 세워도 같은 주문 id가
나온다. 그것이 중복 주문을 막는 첫 번째 방어선이다(두 번째는 `ledger`의 예약).

## 반올림은 항상 0 방향

수량을 올리면 목표와 현금을 동시에 넘긴다. 주문이 거부되면 그 종목만 빠지는 것이
아니라 배치 전체가 흔들리므로, 넘치는 쪽으로는 절대 반올림하지 않는다.

## 목표에 없는 보유는 건드리지 않는다

`target_weights`에 없는 종목은 이번 판단의 대상이 아니다. 0으로 추론하면 일부 종목만
분석한 배치가 나머지를 전량 매도한다.

## 한도를 넘으면 조용히 줄이지 않고 멈춘다

종목 하나가 한도를 넘으면 예외다. 잘라서 넣으면 "승인받은 계획"과 "실제 나간 주문"이
달라지고, 그 차이는 아무 데도 기록되지 않는다.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Mapping

from investment_agent.execution.safety.control import ExecutionSafetyError
from investment_agent.execution.orders.intents import IntentError
from investment_agent.execution.orders.intents import CASH_SYMBOL, ExecutionIntent

# 부동소수 비교 여유. 반올림 오차가 한도 위반으로 읽히지 않게 한다.
EPSILON = 1e-8


@dataclass(frozen=True)
class ExecutionLimits:
    """계획 단계의 한도. 실주문 게이트(`control`)의 한도와는 다른 층이다."""

    min_order_notional: float = 10.0
    max_order_notional: float = 5_000.0
    max_total_notional: float = 20_000.0
    # 소수점 주식을 어디까지 다룰지. broker가 받는 자리수와 같아야 한다.
    quantity_decimals: int = 6

    def __post_init__(self) -> None:
        for name in ("min_order_notional", "max_order_notional", "max_total_notional"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if self.min_order_notional > self.max_order_notional:
            raise ValueError("min_order_notional cannot exceed max_order_notional")
        if not isinstance(self.quantity_decimals, int) or not 0 <= self.quantity_decimals <= 8:
            raise ValueError("quantity_decimals must be an integer between 0 and 8")


@dataclass(frozen=True)
class OrderPlan:
    """broker에 넘기기 직전의 주문 하나."""

    intent_id: str
    client_order_id: str
    symbol: str
    side: str
    quantity: float
    reference_price: float
    notional: float

    def __post_init__(self) -> None:
        if self.side not in {"buy", "sell"}:
            raise ExecutionSafetyError(f"invalid order side: {self.side}")
        if not self.symbol or self.symbol == CASH_SYMBOL:
            raise ExecutionSafetyError("order symbol must be a risky asset")
        for name in ("quantity", "reference_price", "notional"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ExecutionSafetyError(f"{name} must be finite and positive")

    def to_dict(self) -> dict:
        return asdict(self)


def client_order_id(*, intent_id: str, symbol: str, side: str, quantity: float) -> str:
    """주문 하나의 멱등키.

    입력에서 계산하므로 같은 계획은 같은 id를 낳는다. 무작위 id를 쓰면 재시도가
    새 주문이 되고, 그 사실은 체결이 두 번 난 뒤에야 드러난다.
    """
    digest = hashlib.sha256(
        f"{intent_id}|{symbol}|{side}|{quantity:.6f}".encode("utf-8")
    ).hexdigest()[:20]
    return f"aix_{digest}"


class TargetWeightOrderPlanner:
    def __init__(self, limits: ExecutionLimits | None = None) -> None:
        self.limits = limits or ExecutionLimits()

    @staticmethod
    def validate_intent(
        intent: ExecutionIntent,
        *,
        now: datetime | None = None,
        required_mode: str = "paper",
    ) -> None:
        """주문 계획 전에 실행 모드·상태·유효 기간을 같은 오류 계층으로 검사한다."""
        try:
            intent.assert_executable(now=now, required_mode=required_mode)
        except IntentError as exc:
            raise ExecutionSafetyError(str(exc)) from exc

    def plan(
        self,
        intent: ExecutionIntent,
        *,
        portfolio_value: float,
        current_quantities: Mapping[str, float],
        prices: Mapping[str, float],
        eligible_buy_symbols: set[str] | None = None,
        required_mode: str = "paper",
        now: datetime | None = None,
    ) -> tuple[OrderPlan, ...]:
        """의도를 주문 목록으로. 매도가 앞에 오도록 정렬해 돌려준다.

        매도를 먼저 내는 이유는 현금이다 — 매수를 먼저 내면 아직 팔지 않은 돈으로
        사려다 거부된다.
        """
        self.validate_intent(intent, now=now, required_mode=required_mode)
        if not math.isfinite(float(portfolio_value)) or portfolio_value <= 0.0:
            raise ExecutionSafetyError("portfolio_value must be finite and positive")

        eligible = (
            {item.upper() for item in eligible_buy_symbols}
            if eligible_buy_symbols is not None else None
        )
        plans: list[OrderPlan] = []
        for symbol in intent.risky_symbols:
            price = float(prices.get(symbol, 0.0))
            if not math.isfinite(price) or price <= 0.0:
                # 가격을 모르면 수량을 정할 수 없다. 0으로 두면 전량 매도가 된다.
                raise ExecutionSafetyError(f"missing positive broker price for {symbol}")
            current_quantity = float(current_quantities.get(symbol, 0.0))
            if current_quantity < -1e-12:
                raise ExecutionSafetyError(f"short position is not supported: {symbol}")

            target_quantity = portfolio_value * float(intent.target_weights[symbol]) / price
            delta = target_quantity - current_quantity

            if delta > 1e-12 and eligible is not None and symbol not in eligible:
                # 추적 대상 밖 종목을 새로 사면, 그 종목의 자료를 우리는 갖고 있지 않다.
                raise ExecutionSafetyError(
                    f"new buy is outside the current tracked universe: {symbol}"
                )

            scale = 10 ** self.limits.quantity_decimals
            quantity = math.floor(abs(delta) * scale + 1e-12) / scale
            if quantity <= 0.0:
                continue
            notional = quantity * price
            if notional < self.limits.min_order_notional:
                # 수수료가 이득보다 큰 주문이다. 건너뛰는 것이 정상 동작이다.
                continue
            if notional > self.limits.max_order_notional + EPSILON:
                raise ExecutionSafetyError(
                    f"{symbol} order notional {notional:.2f} exceeds "
                    f"{self.limits.max_order_notional:.2f}"
                )

            side = "buy" if delta > 0.0 else "sell"
            plans.append(OrderPlan(
                intent_id=intent.intent_id,
                client_order_id=client_order_id(
                    intent_id=intent.intent_id, symbol=symbol, side=side, quantity=quantity
                ),
                symbol=symbol,
                side=side,
                quantity=quantity,
                reference_price=price,
                notional=notional,
            ))

        total = math.fsum(plan.notional for plan in plans)
        if total > self.limits.max_total_notional + EPSILON:
            raise ExecutionSafetyError(
                f"total order notional {total:.2f} exceeds "
                f"{self.limits.max_total_notional:.2f}"
            )
        return tuple(sorted(plans, key=lambda plan: (plan.side != "sell", plan.symbol)))


__all__ = [
    "EPSILON",
    "ExecutionLimits",
    "OrderPlan",
    "TargetWeightOrderPlanner",
    "client_order_id",
]
