"""실주문을 열고 닫는 게이트.

## 안전 게이트

이 모듈은 환경 설정·durable control·fresh risk state·permit을 결합해 주문 허용 여부를
판정한다. 설정을 코드가 쓰지 않으며, 기본값은 항상 fail-closed 방향이다.

## 이중 fail-closed

두 값이 **모두** 맞아야 열린다.

* `TOSS_LIVE_ENABLED`는 정확히 `"true"`여야 켜진다. 오타·빈 값·`"1"`은 전부 꺼짐이다.
* `TRADING_KILL_SWITCH`는 정확히 `"off"`여야 풀린다. 없으면 **켜진 것**으로 읽는다.

방향이 서로 반대인 것은 의도다. 둘 다 "없으면 안전한 쪽"으로 읽히도록 각각의 기본값을
잡았다.

## 코드가 이 값을 바꾸지 않는다

이 모듈에는 쓰기가 없다. 실거래를 켜는 것은 사람이 명시적으로 하는 일이다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from investment_agent.config import Config
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.platform.clock import ensure_aware, utc_now
from investment_agent.platform.serialization import parse_datetime

# 실거래 스위치. 이름을 상수로 둬서 오타가 조용히 "꺼짐"이 되지 않게 한다.
LIVE_FLAG = "TOSS_LIVE_ENABLED"
KILL_SWITCH_FLAG = "TRADING_KILL_SWITCH"
ACCOUNT_SETTING = "TOSS_ACCOUNT_SEQ"

# 위험 상태가 이보다 오래되면 주문하지 않는다.
MAX_STATE_AGE_SECONDS = 30


class LiveOrderLike(Protocol):
    """게이트가 주문 구현에서 요구하는 최소한."""

    client_order_id: str
    order_type: str

    @property
    def estimated_notional_usd(self) -> float: ...  # pragma: no cover - Protocol 선언


def _positive_float(config: Config, name: str, default: float) -> float:
    raw = (config.get(name) or str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ExecutionSafetyError(f"{name} must be numeric") from exc
    if not math.isfinite(value) or value <= 0:
        raise ExecutionSafetyError(f"{name} must be finite and positive")
    return value


def _positive_int(config: Config, name: str, default: int) -> int:
    raw = (config.get(name) or str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ExecutionSafetyError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ExecutionSafetyError(f"{name} must be positive")
    return value


@dataclass(frozen=True)
class LiveTradingControls:
    """실주문 한도. 테스트는 값을 직접 넣고, 운영은 `from_config`로 읽는다."""

    live_enabled: bool
    kill_switch_on: bool
    account_seq: int
    max_order_notional_usd: float = 5_000.0
    max_daily_notional_usd: float = 20_000.0
    max_daily_orders: int = 20
    max_daily_loss_usd: float = 500.0
    max_drawdown_fraction: float = 0.05
    allow_market_orders: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.account_seq, int) or self.account_seq <= 0:
            raise ExecutionSafetyError("live account_seq must be a positive integer")
        for name in ("max_order_notional_usd", "max_daily_notional_usd",
                     "max_daily_loss_usd", "max_drawdown_fraction"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0:
                raise ExecutionSafetyError(f"{name} must be finite and positive")
        if self.max_drawdown_fraction > 1:
            raise ExecutionSafetyError("max_drawdown_fraction cannot exceed 1")
        if not isinstance(self.max_daily_orders, int) or self.max_daily_orders <= 0:
            raise ExecutionSafetyError("max_daily_orders must be positive")

    @classmethod
    def from_config(cls, config: Config) -> "LiveTradingControls":
        raw_account = (config.get(ACCOUNT_SETTING) or "").strip()
        if not raw_account:
            raise ExecutionSafetyError(f"{ACCOUNT_SETTING} is required for live execution")
        try:
            account_seq = int(raw_account)
        except ValueError as exc:
            raise ExecutionSafetyError(f"{ACCOUNT_SETTING} must be an integer") from exc
        return cls(
            # 두 값 모두 명시돼야 열린다. 기본 상태는 이중 fail-closed다.
            live_enabled=(config.get(LIVE_FLAG) or "false").strip().lower() == "true",
            kill_switch_on=(config.get(KILL_SWITCH_FLAG) or "on").strip().lower() != "off",
            account_seq=account_seq,
            max_order_notional_usd=_positive_float(config, "TOSS_MAX_ORDER_NOTIONAL_USD", 5_000.0),
            max_daily_notional_usd=_positive_float(config, "TOSS_MAX_DAILY_NOTIONAL_USD", 20_000.0),
            max_daily_orders=_positive_int(config, "TOSS_MAX_DAILY_ORDERS", 20),
            max_daily_loss_usd=_positive_float(config, "TOSS_MAX_DAILY_LOSS_USD", 500.0),
            max_drawdown_fraction=_positive_float(config, "TOSS_MAX_DRAWDOWN_FRACTION", 0.05),
            allow_market_orders=(
                (config.get("TOSS_ALLOW_MARKET_ORDERS") or "false").strip().lower() == "true"
            ),
        )


@dataclass(frozen=True)
class RuntimeRiskState:
    """주문 직전에 DB와 broker에서 **다시 계산한** 당일 상태.

    캐시된 값을 쓰지 않는 이유: 한도는 "지금" 기준이어야 하고, 몇 분 전 상태로
    판단하면 그 사이에 난 손실이 한도에 반영되지 않는다.
    """

    submitted_order_count: int
    submitted_notional_usd: float
    realized_pnl_usd: float
    drawdown_fraction: float
    captured_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.submitted_order_count, int) or self.submitted_order_count < 0:
            raise ExecutionSafetyError("submitted_order_count must be nonnegative")
        for name in ("submitted_notional_usd", "realized_pnl_usd", "drawdown_fraction"):
            if not math.isfinite(float(getattr(self, name))):
                raise ExecutionSafetyError(f"{name} must be finite")
        if self.submitted_notional_usd < 0 or not 0 <= self.drawdown_fraction <= 1:
            raise ExecutionSafetyError("runtime risk totals are outside their valid ranges")
        object.__setattr__(self, "captured_at", parse_datetime(self.captured_at))


@dataclass(frozen=True)
class LiveCancellationPermit:
    """특정 미체결 주문 하나만 취소할 수 있는 짧은 운영자 승인."""

    approval_id: str
    broker_order_id: str
    account_seq: int
    approved_by_user_id: str
    issued_at: datetime
    expires_at: datetime
    reason: str
    grant_status: str = "consumed"

    def __post_init__(self) -> None:
        if not self.approval_id or not self.broker_order_id or not self.approved_by_user_id:
            raise ExecutionSafetyError("cancellation permit identity is incomplete")
        if not isinstance(self.account_seq, int) or self.account_seq <= 0:
            raise ExecutionSafetyError("cancellation permit account_seq must be positive")
        if not str(self.reason).strip():
            raise ExecutionSafetyError("cancellation permit reason is required")
        issued = parse_datetime(self.issued_at)
        expires = parse_datetime(self.expires_at)
        if expires <= issued:
            raise ExecutionSafetyError("cancellation permit expires_at must be after issued_at")
        if self.grant_status != "consumed":
            raise ExecutionSafetyError("cancellation approval must be atomically consumed")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)


def assert_live_order_allowed(
    *,
    permit: object,
    controls: LiveTradingControls,
    state: RuntimeRiskState,
    order: LiveOrderLike,
    manifest_hash: str,
    now: datetime | None = None,
    max_state_age_seconds: int = MAX_STATE_AGE_SECONDS,
    lockdown_state_dir: Path | str | None = None,
) -> None:
    """모든 실주문 조건을 한 곳에서 fail-closed로 검사한다.

    조건 하나라도 어기면 예외다. **통과 경로는 하나뿐**이고, 여기서 통과하지 못한
    주문이 나가는 길은 없다.

    잠금 sentinel은 operations가 소유하고, 호출 시점에만 읽는다.
    """
    current = ensure_aware(now or utc_now())

    # 잠금은 다른 무엇보다 먼저 본다. 잠긴 동안에는 어떤 조건도 검사할 이유가 없다.
    from investment_agent.operations.harness.emergency import is_execution_locked_down
    if is_execution_locked_down(lockdown_state_dir):
        raise ExecutionSafetyError("trading execution is under durable lockdown")
    if not controls.live_enabled:
        raise ExecutionSafetyError("Toss live execution is disabled")
    if controls.kill_switch_on:
        raise ExecutionSafetyError("trading kill switch is on")
    if controls.account_seq != permit.account_seq:
        raise ExecutionSafetyError("permit account does not match configured live account")
    if manifest_hash != permit.manifest_hash:
        # 승인받은 계획과 지금 내려는 것이 다르다. 승인은 그 계획에만 유효하다.
        raise ExecutionSafetyError("approved plan hash changed before submission")
    if order.client_order_id not in permit.allowed_client_order_ids:
        raise ExecutionSafetyError("client order id is not covered by the approval")
    if current < parse_datetime(permit.issued_at) or current >= parse_datetime(permit.expires_at):
        raise ExecutionSafetyError("live approval permit is not currently valid")

    state_age = (current - ensure_aware(state.captured_at)).total_seconds()
    # 음수도 막는다. 미래에 찍힌 상태는 시계가 틀렸다는 뜻이고, 그때 나이 계산은 무의미하다.
    if state_age < 0 or state_age > max_state_age_seconds:
        raise ExecutionSafetyError("runtime risk state is stale")

    notional = float(order.estimated_notional_usd)
    if not math.isfinite(notional) or notional <= 0:
        raise ExecutionSafetyError("order notional must be finite and positive")
    if notional > controls.max_order_notional_usd:
        raise ExecutionSafetyError("order exceeds the per-order notional limit")
    if state.submitted_order_count + 1 > controls.max_daily_orders:
        raise ExecutionSafetyError("daily order count limit reached")
    if state.submitted_notional_usd + notional > controls.max_daily_notional_usd:
        raise ExecutionSafetyError("daily submitted notional limit reached")
    if state.realized_pnl_usd <= -controls.max_daily_loss_usd:
        raise ExecutionSafetyError("daily loss limit reached")
    if state.drawdown_fraction >= controls.max_drawdown_fraction:
        raise ExecutionSafetyError("drawdown limit reached")
    if order.order_type == "MARKET" and not controls.allow_market_orders:
        # 시장가는 체결가를 모른 채 내는 주문이라 한도 계산이 사후에 어긋난다.
        raise ExecutionSafetyError("market orders are disabled")


def assert_live_cancel_allowed(
    *,
    permit: LiveCancellationPermit,
    controls: LiveTradingControls,
    account_seq: int,
    broker_order_id: str,
    now: datetime | None = None,
) -> None:
    """취소는 킬스위치가 켜져도 허용한다 — 위험을 **줄이는** 행동이기 때문이다.

    대신 대상이 정확해야 한다. 취소 permit이 가리키는 그 주문만 취소한다.
    """
    current = ensure_aware(now or utc_now())
    if account_seq != controls.account_seq or account_seq != permit.account_seq:
        raise ExecutionSafetyError("cancellation account does not match configured live account")
    if broker_order_id != permit.broker_order_id:
        raise ExecutionSafetyError("cancellation permit does not cover this broker order")
    if current < parse_datetime(permit.issued_at) or current >= parse_datetime(permit.expires_at):
        raise ExecutionSafetyError("cancellation permit is not currently valid")


__all__ = [
    "ACCOUNT_SETTING",
    "ExecutionSafetyError",
    "KILL_SWITCH_FLAG",
    "LIVE_FLAG",
    "LiveOrderLike",
    "LiveCancellationPermit",
    "LiveTradingControls",
    "MAX_STATE_AGE_SECONDS",
    "RuntimeRiskState",
    "assert_live_cancel_allowed",
    "assert_live_order_allowed",
    "parse_datetime",
]
