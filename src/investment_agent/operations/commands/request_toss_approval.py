"""live intent의 토스 주문표를 Discord 건별 승인 요청으로 발행한다.

이 진입점은 토스 계좌를 읽고 승인 카드만 보낸다. 주문 생성·정정·취소 API는
호출하지 않는다. Discord POST 결과를 잃은 경우 자동 재시도하지 않으며, message ID가
결합되지 않은 기존 요청은 사람이 확인하기 전까지 fail-closed로 남긴다.
"""
from __future__ import annotations

import argparse
import hashlib
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Protocol

from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import canonical_json, parse_datetime
from investment_agent.execution.orders.intents import ExecutionIntent, validated_weights
from investment_agent.execution.approval.ledger import ApprovalRequest, ApprovalSigner, approver_allowlist
from investment_agent.execution.approval.secret import load_or_create_approval_secret
from investment_agent.execution.approval.service import ApprovalWorkflow
from investment_agent.execution.brokers.toss import client as toss
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.db import ExecutionRepository
from investment_agent.execution.approval.discord import DiscordApprovalClient
from investment_agent.execution.orders.planning import ExecutionLimits, TargetWeightOrderPlanner
from investment_agent.execution.orders.toss_manual import TossManualHandoff, prepare_handoff

log = get_logger(__name__)

_SNOWFLAKE_RE = re.compile(r"^[1-9][0-9]{5,24}$")
_DEFAULT_QUOTE_MAX_AGE_SECONDS = 120.0


class ExecutionApprovalRepository(Protocol):
    """승인 생성 진입점이 사용하는 private execution 저장소 경계."""

    def load_intent(self, intent_id: str) -> ExecutionIntent | None: ...
    def approval_for_intent(self, intent_id: str) -> ApprovalRequest | None: ...
    def current_tracked_tickers(self) -> set[str]: ...
    def save_handoff(self, handoff: TossManualHandoff) -> None: ...


class DecisionRowRepository(Protocol):
    """승인에 hash로 결박할 proposal/risk 원문 조회 경계."""

    def portfolio_proposal(self, proposal_id: str) -> dict | None: ...
    def risk_decision(self, risk_decision_id: str) -> dict | None: ...


class ApprovalWorkflowPort(Protocol):
    """테스트에서 Discord/DB를 대역으로 바꿀 수 있는 workflow 경계."""

    def create_request(self, **kwargs: Any) -> ApprovalRequest: ...
    def publish_request(
        self,
        request: ApprovalRequest,
        handoff: TossManualHandoff,
    ) -> ApprovalRequest: ...


@dataclass(frozen=True)
class ApprovalRuntimeConfig:
    """승인 카드가 의존하는 정확한 Discord 런타임 식별자."""

    guild_id: str
    channel_id: str
    approver_user_ids: tuple[str, ...]
    bot_token: str = field(repr=False)
    hmac_secret: str = field(repr=False)
    ttl_minutes: int = 15
    discord_timeout_sec: float = 15.0

    def __post_init__(self) -> None:
        for name, value in (
            ("DISCORD_GUILD_ID", self.guild_id),
            ("DISCORD_CHANNEL_AI_APPROVALS", self.channel_id),
        ):
            if _SNOWFLAKE_RE.fullmatch(str(value)) is None:
                raise ExecutionSafetyError(f"{name} must be an exact Discord snowflake")
        normalized = approver_allowlist(*self.approver_user_ids)
        if normalized != self.approver_user_ids:
            raise ExecutionSafetyError("Discord approver allowlist is not canonical")
        if not isinstance(self.bot_token, str) or not self.bot_token.strip():
            raise ExecutionSafetyError("DISCORD_APPROVAL_BOT_TOKEN is required")
        if not isinstance(self.hmac_secret, str):
            raise ExecutionSafetyError("DISCORD_APPROVAL_HMAC_SECRET is required")
        ApprovalSigner(self.hmac_secret)
        if not isinstance(self.ttl_minutes, int) or isinstance(self.ttl_minutes, bool):
            raise ExecutionSafetyError("AI_APPROVAL_TTL_MINUTES must be an integer")
        if not 1 <= self.ttl_minutes <= 24 * 60:
            raise ExecutionSafetyError(
                "AI_APPROVAL_TTL_MINUTES must be between 1 and 1440"
            )
        try:
            timeout = float(self.discord_timeout_sec)
        except (TypeError, ValueError) as exc:
            raise ExecutionSafetyError(
                "DISCORD_APPROVAL_TIMEOUT_SEC must be numeric"
            ) from exc
        if not math.isfinite(timeout) or timeout <= 0:
            raise ExecutionSafetyError(
                "DISCORD_APPROVAL_TIMEOUT_SEC must be finite and positive"
            )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ApprovalRuntimeConfig":
        values = os.environ if env is None else env
        guild_id = _required_env(values, "DISCORD_GUILD_ID")
        channel_id = _required_env(values, "DISCORD_CHANNEL_AI_APPROVALS")
        for name, value in (
            ("DISCORD_GUILD_ID", guild_id),
            ("DISCORD_CHANNEL_AI_APPROVALS", channel_id),
        ):
            if _SNOWFLAKE_RE.fullmatch(value) is None:
                raise ExecutionSafetyError(f"{name} must be an exact Discord snowflake")

        approvers = approver_allowlist(
            str(values.get("DISCORD_APPROVER_USER_IDS") or ""),
            str(values.get("DISCORD_APPROVER_USER_ID") or ""),
        )
        token = _required_env(values, "DISCORD_APPROVAL_BOT_TOKEN")
        secret = (
            load_or_create_approval_secret()
            if env is None
            else load_or_create_approval_secret(values)
        )
        # 서명기를 실제 카드 생성 전에도 만들어 길이 오류를 가장 먼저 차단한다.
        ApprovalSigner(secret)
        ttl = _integer_env(values, "AI_APPROVAL_TTL_MINUTES", 15)
        if not 1 <= ttl <= 24 * 60:
            raise ExecutionSafetyError(
                "AI_APPROVAL_TTL_MINUTES must be between 1 and 1440"
            )
        timeout = _positive_float_env(
            values, "DISCORD_APPROVAL_TIMEOUT_SEC", 15.0
        )
        return cls(
            guild_id=guild_id,
            channel_id=channel_id,
            approver_user_ids=approvers,
            bot_token=token,
            hmac_secret=secret,
            ttl_minutes=ttl,
            discord_timeout_sec=timeout,
        )


def _required_env(env: Mapping[str, str], name: str) -> str:
    value = str(env.get(name) or "").strip()
    if not value:
        raise ExecutionSafetyError(f"{name} is required")
    return value


def _integer_env(env: Mapping[str, str], name: str, default: int) -> int:
    raw = str(env.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ExecutionSafetyError(f"{name} must be an integer") from exc


def _positive_float_env(
    env: Mapping[str, str],
    name: str,
    default: float,
) -> float:
    raw = str(env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ExecutionSafetyError(f"{name} must be numeric") from exc
    if not math.isfinite(value) or value <= 0:
        raise ExecutionSafetyError(f"{name} must be finite and positive")
    return value


def canonical_row_sha256(row: Mapping[str, Any]) -> str:
    """DB 행 전체를 키 순서와 무관한 canonical SHA-256으로 만든다."""
    if not isinstance(row, Mapping) or not row:
        raise ExecutionSafetyError("approval source row must be a non-empty object")
    return hashlib.sha256(canonical_json(dict(row)).encode("utf-8")).hexdigest()


def _validate_source_rows(
    intent: ExecutionIntent,
    *,
    proposal: Mapping[str, Any] | None,
    risk: Mapping[str, Any] | None,
) -> tuple[str, str]:
    """intent와 불변 proposal/risk 원문의 연결을 다시 확인한다."""
    if proposal is None:
        raise ExecutionSafetyError("portfolio proposal was not found")
    if risk is None:
        raise ExecutionSafetyError("risk decision was not found")
    if str(proposal.get("proposal_id") or "") != intent.proposal_id:
        raise ExecutionSafetyError("portfolio proposal does not match live intent")
    if str(proposal.get("stage") or "") != "live":
        raise ExecutionSafetyError("live intent requires a live-stage proposal")
    metadata = proposal.get("metadata")
    if not isinstance(metadata, Mapping):
        raise ExecutionSafetyError("portfolio proposal metadata is invalid")
    if metadata.get("execution_eligible") is not True:
        raise ExecutionSafetyError("portfolio proposal is not execution eligible")
    if str(risk.get("risk_decision_id") or "") != intent.risk_decision_id:
        raise ExecutionSafetyError("risk decision does not match live intent")
    if str(risk.get("proposal_id") or "") != intent.proposal_id:
        raise ExecutionSafetyError("risk decision proposal does not match live intent")
    if risk.get("approved") is not True or risk.get("approved_weights") is None:
        raise ExecutionSafetyError("risk decision is not approved")
    if tuple(risk.get("violations") or ()):
        raise ExecutionSafetyError("approved risk decision contains violations")
    if str(risk.get("input_hash") or "") != intent.input_hash:
        raise ExecutionSafetyError("risk input hash does not match live intent")
    try:
        approved_weights = validated_weights(dict(risk["approved_weights"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ExecutionSafetyError("risk approved weights are invalid") from exc
    if canonical_json(approved_weights) != canonical_json(intent.target_weights):
        raise ExecutionSafetyError("risk approved weights do not match live intent")
    return canonical_row_sha256(proposal), canonical_row_sha256(risk)


def _validate_fresh_whole_share_handoff(
    handoff: TossManualHandoff,
    *,
    intent: ExecutionIntent,
    account_seq: int,
    now: datetime,
    max_age_seconds: float,
) -> None:
    """승인 카드에 저장하기 전에 snapshot 시각과 실행 수량을 검사한다."""
    handoff.validate_manifest()
    # dataclass를 직접 만든 대역도 역직렬화 계약을 통과시킨다. 실제 prepare_handoff의
    # 반환값만 신뢰하지 않고 snapshot/ticket의 타입·통화·side를 이 경계에서 재검증한다.
    TossManualHandoff.from_private_dict(
        handoff.to_dict(),
        account_seq=handoff.account_seq,
    )
    if handoff.intent_id != intent.intent_id or handoff.account_seq != account_seq:
        raise ExecutionSafetyError("Toss handoff identity does not match live intent")
    if not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
        raise ExecutionSafetyError("max snapshot age must be finite and positive")
    try:
        captured_age = (
            now - parse_datetime(handoff.snapshot.captured_at)
        ).total_seconds()
    except (TypeError, ValueError) as exc:
        raise ExecutionSafetyError("Toss account snapshot time is invalid") from exc
    if captured_age < 0 or captured_age > max_age_seconds:
        raise ExecutionSafetyError("Toss account snapshot is stale or future-dated")
    if set(handoff.snapshot.prices) != set(handoff.snapshot.price_timestamps):
        raise ExecutionSafetyError("Toss quote timestamps do not match prices")
    for symbol, timestamp in handoff.snapshot.price_timestamps.items():
        if not timestamp:
            raise ExecutionSafetyError(f"Toss {symbol} quote has no timestamp")
        try:
            quote_age = (now - parse_datetime(timestamp)).total_seconds()
        except (TypeError, ValueError) as exc:
            raise ExecutionSafetyError(f"Toss {symbol} quote time is invalid") from exc
        if quote_age < 0 or quote_age > max_age_seconds:
            raise ExecutionSafetyError(
                f"Toss {symbol} quote is stale or future-dated"
            )
    if not handoff.tickets:
        raise ExecutionSafetyError("Toss handoff has no whole-share orders")
    for ticket in handoff.tickets:
        if ticket.intent_id != intent.intent_id:
            raise ExecutionSafetyError("Toss ticket intent does not match live intent")
        if ticket.symbol not in handoff.snapshot.prices:
            raise ExecutionSafetyError("Toss ticket has no matching snapshot quote")
        quote_timestamp = handoff.snapshot.price_timestamps.get(ticket.symbol)
        if not ticket.price_timestamp or ticket.price_timestamp != quote_timestamp:
            raise ExecutionSafetyError("Toss ticket quote timestamp changed")
        if not math.isclose(
            float(ticket.reference_price),
            float(handoff.snapshot.prices[ticket.symbol]),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ExecutionSafetyError("Toss ticket reference price changed")
        quantity = float(ticket.order_quantity)
        if not math.isfinite(quantity) or quantity <= 0 or not quantity.is_integer():
            raise ExecutionSafetyError("live approval is whole-share only")


def _published_existing(
    request: ApprovalRequest,
    *,
    intent: ExecutionIntent,
    account_seq: int,
    config: ApprovalRuntimeConfig,
) -> ApprovalRequest:
    """이미 발송된 같은 intent는 성공으로, 모호한 미결합 요청은 실패로 처리한다."""
    if (
        request.intent_id != intent.intent_id
        or request.proposal_id != intent.proposal_id
        or request.risk_decision_id != intent.risk_decision_id
        or request.execution_mode != "live"
        or request.account_seq != account_seq
    ):
        raise ExecutionSafetyError("existing approval does not match live intent")
    if (
        request.discord_guild_id != config.guild_id
        or request.discord_channel_id != config.channel_id
        or request.allowed_approver_user_ids != config.approver_user_ids
    ):
        raise ExecutionSafetyError("existing approval Discord identity has changed")
    if request.discord_message_id is None:
        raise ExecutionSafetyError(
            "existing approval has no Discord message ID; automatic repost is forbidden"
        )
    return request


def request_toss_approval(
    intent_id: str,
    *,
    account_seq: int,
    config: ApprovalRuntimeConfig,
    execution_repository: ExecutionApprovalRepository,
    decision_repository: DecisionRowRepository,
    workflow: ApprovalWorkflowPort,
    planner: TargetWeightOrderPlanner,
    prepare_handoff_fn: Callable[..., TossManualHandoff] = prepare_handoff,
    now: datetime | None = None,
    max_snapshot_age_seconds: float = _DEFAULT_QUOTE_MAX_AGE_SECONDS,
) -> ApprovalRequest:
    """live 주문표를 한 번 저장하고 Discord 승인 카드도 최대 한 번 발송한다."""
    current = parse_datetime(now or datetime.now(timezone.utc))
    if (
        not isinstance(intent_id, str)
        or not intent_id.strip()
        or intent_id != intent_id.strip()
    ):
        raise ExecutionSafetyError("an exact execution intent_id is required")
    if not isinstance(account_seq, int) or isinstance(account_seq, bool) or account_seq <= 0:
        raise ExecutionSafetyError("Toss account_seq must be a positive integer")
    intent = execution_repository.load_intent(intent_id)
    if intent is None:
        raise ExecutionSafetyError("execution intent was not found")
    if intent.execution_mode != "live":
        raise ExecutionSafetyError("only a live ExecutionIntent can request approval")

    existing = execution_repository.approval_for_intent(intent.intent_id)
    if existing is not None:
        return _published_existing(
            existing,
            intent=intent,
            account_seq=account_seq,
            config=config,
        )

    if intent.status != "approved":
        raise ExecutionSafetyError("only an approved live ExecutionIntent can request approval")
    TargetWeightOrderPlanner.validate_intent(
        intent, now=current, required_mode="live"
    )
    if planner.limits.quantity_decimals != 0:
        raise ExecutionSafetyError("live approval planner must use whole shares")

    proposal = decision_repository.portfolio_proposal(intent.proposal_id)
    risk = decision_repository.risk_decision(intent.risk_decision_id)
    proposal_hash, risk_hash = _validate_source_rows(
        intent, proposal=proposal, risk=risk
    )
    eligible = execution_repository.current_tracked_tickers()
    if not eligible:
        raise ExecutionSafetyError("tracked universe is empty")

    handoff = prepare_handoff_fn(
        intent,
        account_seq=account_seq,
        eligible_buy_symbols=set(eligible),
        planner=planner,
        required_mode="live",
        now=current,
    )
    _validate_fresh_whole_share_handoff(
        handoff,
        intent=intent,
        account_seq=account_seq,
        now=current,
        max_age_seconds=max_snapshot_age_seconds,
    )

    # handoff가 먼저 durable해야 approval의 manifest_hash FK가 같은 원문을 가리킨다.
    try:
        execution_repository.save_handoff(handoff)
        request = workflow.create_request(
            intent=intent,
            handoff=handoff,
            proposal_hash=proposal_hash,
            risk_hash=risk_hash,
            discord_guild_id=config.guild_id,
            discord_channel_id=config.channel_id,
            allowed_approver_user_ids=config.approver_user_ids,
            ttl=timedelta(minutes=config.ttl_minutes),
            now=current,
        )
    except Exception:
        # intent unique 제약과 경합한 다른 프로세스가 이미 게시를 끝냈다면 성공이다.
        # 아직 message가 결합되지 않았다면 POST 결과가 모호할 수 있어 재발송하지 않는다.
        concurrent = execution_repository.approval_for_intent(intent.intent_id)
        if concurrent is None:
            raise
        return _published_existing(
            concurrent,
            intent=intent,
            account_seq=account_seq,
            config=config,
        )

    # POST timeout/5xx를 이 계층에서 재시도하지 않는다. 실패하면 message 미결합
    # pending 행이 남고, 다음 실행은 위의 existing gate에서 멈춘다.
    return workflow.publish_request(request, handoff)


def request_toss_approval_by_id(
    intent_id: str,
    *,
    account_seq: int | None = None,
    config: ApprovalRuntimeConfig | None = None,
    execution_repository: ExecutionApprovalRepository | None = None,
    decision_repository: DecisionRowRepository | None = None,
    workflow: ApprovalWorkflowPort | None = None,
    planner: TargetWeightOrderPlanner | None = None,
    prepare_handoff_fn: Callable[..., TossManualHandoff] = prepare_handoff,
    now: datetime | None = None,
) -> ApprovalRequest:
    """ops 하네스가 latest 추론 없이 stable intent_id로 호출하는 runtime API."""
    runtime = config or ApprovalRuntimeConfig.from_env()
    # 운영 하네스가 이미 고정된 account_seq를 넘기면 중복 승인 확인 전의 불필요한
    # 계좌 목록 네트워크 호출을 피한다. 생략했을 때만 환경값/계좌 목록으로 해석한다.
    resolved_account = (
        account_seq if account_seq is not None else toss.resolve_account_seq(None)
    )
    execution = execution_repository or ExecutionRepository()
    decisions = decision_repository or execution
    selected_planner = planner or _whole_share_planner()
    selected_workflow = workflow
    if selected_workflow is None:
        signer = ApprovalSigner(runtime.hmac_secret)
        selected_workflow = ApprovalWorkflow(
            repository=execution,
            signer=signer,
            discord_client=DiscordApprovalClient(
                bot_token=runtime.bot_token,
                guild_id=runtime.guild_id,
                timeout_sec=runtime.discord_timeout_sec,
            ),
            runtime_approver_user_ids=runtime.approver_user_ids,
        )
    return request_toss_approval(
        intent_id,
        account_seq=resolved_account,
        config=runtime,
        execution_repository=execution,
        decision_repository=decisions,
        workflow=selected_workflow,
        planner=selected_planner,
        prepare_handoff_fn=prepare_handoff_fn,
        now=now,
    )


def _whole_share_planner(env: Mapping[str, str] | None = None) -> TargetWeightOrderPlanner:
    values = os.environ if env is None else env
    return TargetWeightOrderPlanner(ExecutionLimits(
        min_order_notional=_positive_float_env(
            values, "TOSS_MIN_ORDER_NOTIONAL_USD", 10.0
        ),
        max_order_notional=_positive_float_env(
            values, "TOSS_MAX_ORDER_NOTIONAL_USD", 5_000.0
        ),
        max_total_notional=_positive_float_env(
            values, "TOSS_MAX_TOTAL_NOTIONAL_USD", 20_000.0
        ),
        quantity_decimals=0,
    ))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="investment_agent.operations.commands.request_toss_approval"
    )
    parser.add_argument("--intent-id", required=True)
    parser.add_argument("--account-seq", type=int)
    args = parser.parse_args(argv)

    request = request_toss_approval_by_id(
        args.intent_id,
        account_seq=args.account_seq,
    )
    log.info(
        "Toss live approval ready approval_id=%s intent_id=%s status=%s message_id=%s",
        request.approval_id,
        request.intent_id,
        request.status,
        request.discord_message_id,
    )
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
