"""Discord 승인 하나를 토스 실주문 원장과 안전하게 연결하는 worker.

네트워크 mutation 전에 모든 주문을 DB에 reserve한다. POST 응답을 잃으면 같은
``clientOrderId``를 다시 보내지 않고 즉시 reconciliation 상태로 멈춘다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Callable, Protocol
from zoneinfo import ZoneInfo

from investment_agent.platform.serialization import parse_datetime
from investment_agent.execution.orders.intents import ExecutionIntent
from investment_agent.execution.approval.ledger import ApprovalRequest, issue_live_execution_permit
from investment_agent.execution.brokers.toss import client as toss_read
from investment_agent.execution.brokers.toss.orders import (
    TossOrderApi,
    TossOrderCommand,
    TossOrderOutcomeUnknown,
    TossOrderReceipt,
    TossOrderRejected,
)
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.safety.control import LiveTradingControls, RuntimeRiskState
from investment_agent.execution.orders.ledger import OrderAttempt, OrderAttemptReservation
from investment_agent.execution.orders.planning import ExecutionLimits, TargetWeightOrderPlanner
from investment_agent.execution.orders.toss_manual import (
    TossManualHandoff,
    TossManualSnapshot,
    build_snapshot,
)

_NEW_YORK = ZoneInfo("America/New_York")


class LiveExecutionRepository(Protocol):
    def load_approval(self, approval_id: str) -> ApprovalRequest | None: ...
    def load_intent(self, intent_id: str) -> ExecutionIntent | None: ...
    def load_handoff(self, manifest_hash: str) -> TossManualHandoff | None: ...
    def current_tracked_tickers(self) -> set[str]: ...
    def consume_approval(self, approval_id: str, *, manifest_hash: str) -> ApprovalRequest | None: ...
    def reserve_order_attempt(self, attempt: OrderAttempt) -> OrderAttemptReservation | None: ...
    def append_order_attempt_event(
        self,
        attempt_id: str,
        *,
        status: str,
        broker_order_id: str | None = None,
        raw_status: str | None = None,
        raw_response: dict | None = None,
        occurred_at: datetime | None = None,
    ): ...
    def create_planned_order(self, row: dict) -> None: ...
    def attach_order_attempt(self, client_order_id: str, attempt_id: str) -> None: ...
    def update_order_execution(
        self,
        client_order_id: str,
        *,
        status: str,
        broker_order_id: str | None,
        raw_broker_status: str | None = None,
        raw_broker_response: dict | None = None,
        submitted_at: datetime | None = None,
    ) -> None: ...
    def update_intent_status(
        self,
        intent_id: str,
        status: str,
        failure_reason: str | None = None,
        *,
        expected_status: str | None = None,
    ) -> None: ...
    def runtime_risk_state(
        self,
        *,
        account_seq: int,
        current_equity: float,
        broker_daily_pnl_usd: float,
        captured_at: datetime,
    ) -> RuntimeRiskState: ...


@dataclass(frozen=True)
class LiveExecutionPolicy:
    """사람 승인 뒤에도 모델이 바꿀 수 없는 주문 재검증 규칙."""

    max_quote_age_seconds: float = 120.0
    max_price_drift_fraction: float = 0.01
    limit_band_bps: int = 25
    commission_buffer_bps: int = 10
    permit_ttl_seconds: int = 120
    market_open_delay_minutes: int = 5
    market_close_buffer_minutes: int = 15

    def __post_init__(self) -> None:
        if not math.isfinite(self.max_quote_age_seconds) or self.max_quote_age_seconds <= 0:
            raise ValueError("max_quote_age_seconds must be positive")
        if not 0 < self.max_price_drift_fraction <= 0.05:
            raise ValueError("max_price_drift_fraction must be between 0 and 0.05")
        if not isinstance(self.limit_band_bps, int) or not 0 <= self.limit_band_bps <= 100:
            raise ValueError("limit_band_bps must be between 0 and 100")
        if not isinstance(self.commission_buffer_bps, int) or not 0 <= self.commission_buffer_bps <= 100:
            raise ValueError("commission_buffer_bps must be between 0 and 100")
        if not 1 <= self.permit_ttl_seconds <= 300:
            raise ValueError("permit_ttl_seconds must be between 1 and 300")
        if not 0 <= self.market_open_delay_minutes <= 60:
            raise ValueError("market_open_delay_minutes must be between 0 and 60")
        if not 0 <= self.market_close_buffer_minutes <= 60:
            raise ValueError("market_close_buffer_minutes must be between 0 and 60")


@dataclass(frozen=True)
class LiveExecutionResult:
    approval_id: str
    intent_id: str
    manifest_hash: str
    submitted: tuple[TossOrderReceipt, ...]
    status: str


def assert_regular_us_session(
    now: datetime,
    *,
    open_delay_minutes: int = 5,
    close_buffer_minutes: int = 15,
) -> None:
    """공식 캘린더 조회 전에도 명백한 주말·장외 시각을 로컬에서 차단한다."""
    current = parse_datetime(now).astimezone(_NEW_YORK)
    if current.weekday() >= 5:
        raise ExecutionSafetyError("Toss live orders are allowed only on US market weekdays")
    start_minutes = 9 * 60 + 30 + open_delay_minutes
    end_minutes = 16 * 60 - close_buffer_minutes
    current_minutes = current.hour * 60 + current.minute
    if not start_minutes <= current_minutes < end_minutes:
        raise ExecutionSafetyError("Toss live orders are outside the guarded US regular session")


def assert_official_us_session(
    now: datetime,
    *,
    session_provider: Callable[[date], toss_read.TossUsRegularSession | None],
    open_delay_minutes: int,
    close_buffer_minutes: int,
) -> None:
    """휴장·조기폐장을 포함한 토스 공식 캘린더와 현재 시각을 대조한다."""
    current = parse_datetime(now)
    market_date = current.astimezone(_NEW_YORK).date()
    session = session_provider(market_date)
    if session is None:
        raise ExecutionSafetyError("Toss reports the US market is closed for this date")
    if session.market_date != market_date:
        raise ExecutionSafetyError("Toss US market calendar returned a different date")
    start = parse_datetime(session.start_at) + timedelta(minutes=open_delay_minutes)
    end = parse_datetime(session.end_at) - timedelta(minutes=close_buffer_minutes)
    if end <= start or not start <= current < end:
        raise ExecutionSafetyError("Toss live orders are outside the official guarded session")


def _tick(price: Decimal) -> Decimal:
    return Decimal("0.01") if price >= Decimal("1") else Decimal("0.0001")


def guarded_limit_price(
    reference_price: float,
    *,
    side: str,
    band_bps: int,
) -> Decimal:
    reference = Decimal(str(reference_price))
    fraction = Decimal(band_bps) / Decimal(10_000)
    if side == "buy":
        raw = reference * (Decimal(1) + fraction)
        rounding = ROUND_FLOOR
    elif side == "sell":
        raw = reference * (Decimal(1) - fraction)
        rounding = ROUND_CEILING
    else:
        raise ExecutionSafetyError("live order side is invalid")
    tick = _tick(reference)
    value = raw.quantize(tick, rounding=rounding)
    if value <= 0:
        raise ExecutionSafetyError("guarded limit price is not positive")
    return value


def commands_from_handoff(
    handoff: TossManualHandoff,
    *,
    policy: LiveExecutionPolicy,
) -> tuple[TossOrderCommand, ...]:
    """승인 카드의 수량·기준가에서 whole-share LIMIT 명령만 만든다."""
    handoff.validate_manifest()
    commands: list[TossOrderCommand] = []
    for ticket in handoff.tickets:
        quantity = Decimal(str(ticket.order_quantity))
        if quantity != quantity.to_integral_value():
            raise ExecutionSafetyError("automatic live execution is whole-share only")
        commands.append(TossOrderCommand(
            client_order_id=ticket.client_order_id,
            symbol=ticket.symbol,
            side=ticket.side.upper(),
            order_type="LIMIT",
            quantity=quantity,
            reference_price_usd=Decimal(str(ticket.reference_price)),
            limit_price_usd=guarded_limit_price(
                ticket.reference_price,
                side=ticket.side,
                band_bps=policy.limit_band_bps,
            ),
            time_in_force="DAY",
        ))
    return tuple(commands)


def revalidate_live_handoff(
    *,
    intent: ExecutionIntent,
    handoff: TossManualHandoff,
    fresh: TossManualSnapshot,
    eligible_buy_symbols: set[str],
    planner: TargetWeightOrderPlanner,
    policy: LiveExecutionPolicy,
    now: datetime,
) -> None:
    """승인 뒤 계좌·시세가 주문 수량을 바꾸지 않았는지 다시 계산한다."""
    handoff.validate_manifest()
    if intent.execution_mode != "live" or handoff.intent_id != intent.intent_id:
        raise ExecutionSafetyError("live intent and approved handoff do not match")
    captured = parse_datetime(fresh.captured_at)
    age = (parse_datetime(now) - captured).total_seconds()
    if age < 0 or age > policy.max_quote_age_seconds:
        raise ExecutionSafetyError("fresh Toss account snapshot is stale or future-dated")
    for symbol, timestamp in fresh.price_timestamps.items():
        if not timestamp:
            raise ExecutionSafetyError(f"Toss {symbol} quote has no timestamp")
        quote_age = (parse_datetime(now) - parse_datetime(timestamp)).total_seconds()
        if quote_age < 0 or quote_age > policy.max_quote_age_seconds:
            raise ExecutionSafetyError(f"Toss {symbol} quote is stale or future-dated")

    fresh_plans = planner.plan(
        intent,
        portfolio_value=fresh.portfolio_value,
        current_quantities=fresh.current_quantities,
        prices=fresh.prices,
        eligible_buy_symbols=eligible_buy_symbols,
        required_mode="live",
        now=now,
    )
    approved_identity = tuple(
        (item.client_order_id, item.symbol, item.side, float(item.order_quantity))
        for item in handoff.tickets
    )
    fresh_identity = tuple(
        (item.client_order_id, item.symbol, item.side, float(item.quantity))
        for item in fresh_plans
    )
    if fresh_identity != approved_identity:
        raise ExecutionSafetyError(
            "Toss holdings, cash, or prices changed the approved order quantities; reapproval required"
        )
    for ticket in handoff.tickets:
        current_price = float(fresh.prices.get(ticket.symbol, 0.0))
        drift = abs(current_price / ticket.reference_price - 1.0)
        if not math.isfinite(drift) or drift > policy.max_price_drift_fraction:
            raise ExecutionSafetyError(
                f"Toss {ticket.symbol} price drift exceeds the approved tolerance"
            )


def _same_intent_identity(
    expected: ExecutionIntent,
    current: ExecutionIntent,
) -> bool:
    """status 외 주문 의도 원문이 worker 실행 중 바뀌지 않았는지 확인한다."""
    return (
        current.intent_id == expected.intent_id
        and current.risk_decision_id == expected.risk_decision_id
        and current.proposal_id == expected.proposal_id
        and current.execution_mode == expected.execution_mode
        and current.target_weights == expected.target_weights
        and current.input_hash == expected.input_hash
        and current.not_before == expected.not_before
        and current.expires_at == expected.expires_at
    )


class TossLiveExecutionWorker:
    """승인 조회부터 reserve·제출까지 한 번만 수행하는 동기 worker."""

    def __init__(
        self,
        *,
        repository: LiveExecutionRepository,
        api: TossOrderApi,
        controls: LiveTradingControls,
        policy: LiveExecutionPolicy | None = None,
        planner: TargetWeightOrderPlanner | None = None,
        snapshot_provider: Callable[..., TossManualSnapshot] = build_snapshot,
        session_provider: Callable[
            [date], toss_read.TossUsRegularSession | None
        ] = toss_read.fetch_us_regular_session,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.repository = repository
        self.api = api
        self.controls = controls
        self.policy = policy or LiveExecutionPolicy()
        self.planner = planner or TargetWeightOrderPlanner(ExecutionLimits(
            min_order_notional=10.0,
            max_order_notional=controls.max_order_notional_usd,
            max_total_notional=controls.max_daily_notional_usd,
            quantity_decimals=0,
        ))
        self.snapshot_provider = snapshot_provider
        self.session_provider = session_provider
        self.clock = clock

    @staticmethod
    def _require_event(value, message: str) -> None:
        if value is None:
            raise ExecutionSafetyError(message)

    def _fail_unsubmitted_attempts(
        self,
        pending: tuple[tuple[TossOrderCommand, OrderAttempt], ...],
        *,
        occurred_at: datetime,
        reason: str,
    ) -> None:
        """브로커에 보내지 않은 reserve를 terminal 상태로 닫는다.

        한 주문이 거절되거나 결과 불명이 되면 같은 승인에 속한 뒤쪽 주문은
        제출하지 않는다. 이때 ``reserved/planned`` 행을 그대로 남기면 재시작 후
        사람이 실제 주문인지 구분할 수 없으므로, immutable event와 주문 행을 모두
        명시적인 ``failed`` 로 닫는다.
        """
        raw = {"reason": reason, "broker_request_sent": False}
        for command, attempt in pending:
            self._require_event(
                self.repository.append_order_attempt_event(
                    attempt.attempt_id,
                    status="failed",
                    raw_status="not_submitted",
                    raw_response=raw,
                    occurred_at=occurred_at,
                ),
                "unsubmitted order attempt could not be closed",
            )
            self.repository.update_order_execution(
                command.client_order_id,
                status="failed",
                broker_order_id=None,
                raw_broker_status="not_submitted",
                raw_broker_response=raw,
            )

    def _preflight_broker(
        self,
        commands: tuple[TossOrderCommand, ...],
    ) -> None:
        sell_by_symbol: dict[str, Decimal] = {}
        for command in commands:
            if command.side == "SELL":
                assert isinstance(command.quantity, Decimal)
                sell_by_symbol[command.symbol] = (
                    sell_by_symbol.get(command.symbol, Decimal(0)) + command.quantity
                )
        for symbol, required in sorted(sell_by_symbol.items()):
            available = self.api.sellable_quantity(
                account_seq=self.controls.account_seq,
                symbol=symbol,
            )
            if available < required:
                raise ExecutionSafetyError(f"Toss sellable quantity is insufficient for {symbol}")

        commission_rate = Decimal(self.policy.commission_buffer_bps) / Decimal(10_000)
        rates = self.api.commissions(account_seq=self.controls.account_seq)
        for row in rates:
            if str(row.get("marketCountry") or "").upper() == "US":
                commission_rate = max(commission_rate, Decimal(row["commissionRate"]))
        required_cash = Decimal(0)
        for command in commands:
            if command.side != "BUY":
                continue
            assert isinstance(command.quantity, Decimal)
            assert isinstance(command.limit_price_usd, Decimal)
            required_cash += command.quantity * command.limit_price_usd * (
                Decimal(1) + commission_rate
            )
        if required_cash:
            buying_power = self.api.buying_power(
                account_seq=self.controls.account_seq,
                currency="USD",
            )
            # 아직 체결되지 않은 매도대금에 의존하는 연쇄 매수를 금지한다.
            if buying_power < required_cash:
                raise ExecutionSafetyError(
                    "current USD buying power cannot fund every approved buy without sale proceeds"
                )

    def execute(self, approval_id: str, *, now: datetime | None = None) -> LiveExecutionResult:
        current = parse_datetime(now or self.clock())
        if not self.controls.live_enabled:
            raise ExecutionSafetyError("Toss live execution is disabled")
        if self.controls.kill_switch_on:
            raise ExecutionSafetyError("trading kill switch is on")
        assert_regular_us_session(
            current,
            open_delay_minutes=self.policy.market_open_delay_minutes,
            close_buffer_minutes=self.policy.market_close_buffer_minutes,
        )
        assert_official_us_session(
            current,
            session_provider=self.session_provider,
            open_delay_minutes=self.policy.market_open_delay_minutes,
            close_buffer_minutes=self.policy.market_close_buffer_minutes,
        )
        approval = self.repository.load_approval(approval_id)
        if approval is None or approval.status != "approved" or approval.execution_mode != "live":
            raise ExecutionSafetyError("a pending live execution requires one approved request")
        intent = self.repository.load_intent(approval.intent_id)
        handoff = self.repository.load_handoff(approval.manifest_hash)
        if intent is None or handoff is None:
            raise ExecutionSafetyError("approved intent or immutable Toss handoff is missing")
        if approval.account_seq != self.controls.account_seq:
            raise ExecutionSafetyError("approved Toss account differs from live controls")

        eligible = self.repository.current_tracked_tickers()
        fresh = self.snapshot_provider(
            intent,
            account_seq=self.controls.account_seq,
            captured_at=current,
        )
        revalidate_live_handoff(
            intent=intent,
            handoff=handoff,
            fresh=fresh,
            eligible_buy_symbols=eligible,
            planner=self.planner,
            policy=self.policy,
            now=current,
        )
        commands = commands_from_handoff(handoff, policy=self.policy)
        self._preflight_broker(commands)
        risk_state = self.repository.runtime_risk_state(
            account_seq=self.controls.account_seq,
            current_equity=fresh.portfolio_value,
            broker_daily_pnl_usd=fresh.daily_profit_loss_usd,
            captured_at=current,
        )

        # 모든 읽기·사전검증이 끝난 뒤에만 승인을 소비한다.
        consumed = self.repository.consume_approval(
            approval.approval_id,
            manifest_hash=handoff.manifest_hash,
        )
        if consumed is None:
            raise ExecutionSafetyError("live approval was expired, changed, or already consumed")
        permit = issue_live_execution_permit(
            approval=consumed,
            intent_id=intent.intent_id,
            intent_execution_mode=intent.execution_mode,
            intent_status=intent.status,
            intent_not_before=intent.not_before,
            intent_expires_at=intent.expires_at,
            intent_proposal_id=intent.proposal_id,
            intent_risk_decision_id=intent.risk_decision_id,
            handoff_intent_id=handoff.intent_id,
            handoff_manifest_hash=handoff.manifest_hash,
            handoff_account_seq=handoff.account_seq,
            handoff_client_order_ids=tuple(ticket.client_order_id for ticket in handoff.tickets),
            account_seq=self.controls.account_seq,
            now=current,
            ttl_seconds=self.policy.permit_ttl_seconds,
        )

        attempts: list[OrderAttempt] = []
        tickets = {item.client_order_id: item for item in handoff.tickets}
        for command in commands:
            ticket = tickets[command.client_order_id]
            self.repository.create_planned_order({
                "client_order_id": command.client_order_id,
                "intent_id": intent.intent_id,
                "approval_id": consumed.approval_id,
                "account_seq": self.controls.account_seq,
                "broker_order_id": None,
                "ticker": command.symbol,
                "side": command.side.lower(),
                "quantity": float(command.quantity or 0),
                "reference_price": ticket.reference_price,
                "notional": ticket.estimated_notional,
                "status": "planned",
            })
            attempt = OrderAttempt.create(
                client_order_id=command.client_order_id,
                intent_id=intent.intent_id,
                approval_id=consumed.approval_id,
                operation="create",
                request_payload=command.payload(),
                manifest_hash=handoff.manifest_hash,
                account_seq=self.controls.account_seq,
                reserved_at=current,
            )
            reservation = self.repository.reserve_order_attempt(attempt)
            if reservation is None:
                raise ExecutionSafetyError("order attempt reservation was rejected")
            reserved = reservation.require_new()
            self.repository.attach_order_attempt(command.client_order_id, reserved.attempt_id)
            attempts.append(reserved)

        self.repository.update_intent_status(
            intent.intent_id,
            "executing",
            expected_status="approved",
        )
        submitted: list[TossOrderReceipt] = []
        state = risk_state
        pairs = tuple(zip(commands, attempts, strict=True))
        for index, (command, attempt) in enumerate(pairs):
            # 테스트가 명시 시각을 주면 고정하고, 운영에서는 매 POST 직전 실제 시각을 다시
            # 읽는다. 느린 앞 주문이 permit/risk freshness를 소진하면 뒤 주문은 보내지 않는다.
            submit_time = current if now is not None else parse_datetime(self.clock())
            self._require_event(
                self.repository.append_order_attempt_event(
                    attempt.attempt_id,
                    status="submitting",
                    occurred_at=submit_time,
                ),
                "order attempt could not enter submitting state",
            )
            try:
                latest_intent = self.repository.load_intent(intent.intent_id)
                if (
                    latest_intent is None
                    or latest_intent.status != "executing"
                    or not _same_intent_identity(intent, latest_intent)
                ):
                    raise ExecutionSafetyError(
                        "live intent changed or was cancelled before submission"
                    )
                receipt = self.api.create_order(
                    command,
                    permit=permit,
                    controls=self.controls,
                    risk_state=state,
                    manifest_hash=handoff.manifest_hash,
                    now=submit_time,
                )
            except TossOrderOutcomeUnknown as exc:
                self.repository.append_order_attempt_event(
                    attempt.attempt_id,
                    status="outcome_unknown",
                    raw_status="outcome_unknown",
                    raw_response={"status_code": exc.status_code},
                    occurred_at=submit_time,
                )
                self.repository.update_order_execution(
                    command.client_order_id,
                    status="outcome_unknown",
                    broker_order_id=None,
                    raw_broker_status="outcome_unknown",
                    raw_broker_response={"status_code": exc.status_code},
                    submitted_at=submit_time,
                )
                self.repository.update_intent_status(
                    intent.intent_id,
                    "executing",
                    "TossOrderOutcomeUnknown",
                )
                self._fail_unsubmitted_attempts(
                    pairs[index + 1 :],
                    occurred_at=submit_time,
                    reason="prior_order_outcome_unknown",
                )
                raise
            except TossOrderRejected as exc:
                raw = {
                    "status_code": exc.status_code,
                    "code": exc.code,
                    "request_id": exc.request_id,
                }
                self.repository.append_order_attempt_event(
                    attempt.attempt_id,
                    status="rejected",
                    raw_status=exc.code,
                    raw_response=raw,
                    occurred_at=submit_time,
                )
                self.repository.update_order_execution(
                    command.client_order_id,
                    status="rejected",
                    broker_order_id=None,
                    raw_broker_status=exc.code,
                    raw_broker_response=raw,
                    submitted_at=submit_time,
                )
                self.repository.update_intent_status(
                    intent.intent_id,
                    "failed",
                    "TossOrderRejected",
                    expected_status="executing",
                )
                self._fail_unsubmitted_attempts(
                    pairs[index + 1 :],
                    occurred_at=submit_time,
                    reason="prior_order_rejected",
                )
                raise
            except ExecutionSafetyError as exc:
                raw = {
                    "reason": type(exc).__name__,
                    "broker_request_sent": False,
                }
                self._require_event(
                    self.repository.append_order_attempt_event(
                        attempt.attempt_id,
                        status="failed",
                        raw_status="pre_submission_safety_block",
                        raw_response=raw,
                        occurred_at=submit_time,
                    ),
                    "safety-blocked order attempt could not be closed",
                )
                self.repository.update_order_execution(
                    command.client_order_id,
                    status="failed",
                    broker_order_id=None,
                    raw_broker_status="pre_submission_safety_block",
                    raw_broker_response=raw,
                )
                self.repository.update_intent_status(
                    intent.intent_id,
                    "failed",
                    type(exc).__name__,
                    expected_status="executing",
                )
                self._fail_unsubmitted_attempts(
                    pairs[index + 1 :],
                    occurred_at=submit_time,
                    reason="prior_order_safety_blocked",
                )
                raise

            self._require_event(
                self.repository.append_order_attempt_event(
                    attempt.attempt_id,
                    status="submitted",
                    broker_order_id=receipt.order_id,
                    raw_status="submitted",
                    raw_response=receipt.raw_response,
                    occurred_at=submit_time,
                ),
                "submitted order could not be recorded",
            )
            self.repository.update_order_execution(
                command.client_order_id,
                status="submitted",
                broker_order_id=receipt.order_id,
                raw_broker_status="submitted",
                raw_broker_response=receipt.raw_response,
                submitted_at=submit_time,
            )
            submitted.append(receipt)
            state = RuntimeRiskState(
                submitted_order_count=state.submitted_order_count + 1,
                submitted_notional_usd=(
                    state.submitted_notional_usd + command.estimated_notional_usd
                ),
                realized_pnl_usd=state.realized_pnl_usd,
                drawdown_fraction=state.drawdown_fraction,
                captured_at=submit_time.isoformat(),
            )

        return LiveExecutionResult(
            approval_id=consumed.approval_id,
            intent_id=intent.intent_id,
            manifest_hash=handoff.manifest_hash,
            submitted=tuple(submitted),
            status="reconciling",
        )


__all__ = [
    "LiveExecutionPolicy",
    "LiveExecutionResult",
    "TossLiveExecutionWorker",
    "assert_regular_us_session",
    "assert_official_us_session",
    "commands_from_handoff",
    "guarded_limit_price",
    "revalidate_live_handoff",
]
