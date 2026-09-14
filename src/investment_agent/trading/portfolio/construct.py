"""완료 SignalBook과 토스 계좌를 full portfolio + RiskDecision으로 결합한다."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone

from investment_agent.trading.contracts import ContractError, parse_datetime
from investment_agent.trading.supabase_repository import SupabaseRepository
from investment_agent.trading.portfolio.constructor import PortfolioConstructor
from investment_agent.trading.portfolio.contracts import CASH_SYMBOL
from investment_agent.platform.serialization import stable_id
from investment_agent.trading.portfolio.market_risk import (
    MarketCovariance,
    MarketRiskMetrics,
    TradingCostInputs,
    calibrate_trading_costs,
    calculate_market_covariance,
    calculate_market_risk,
    estimate_betas,
    estimate_trading_costs,
)
from investment_agent.trading.portfolio.optimizer import OptimizerPolicy
from investment_agent.trading.risk.gate import DeterministicRiskGate, PortfolioRiskPolicy
from investment_agent.trading.risk.stress import STRESS_PROXIES, scenario_sensitivities
from investment_agent.trading.decision.constants import SIGNAL_HORIZON_DAYS
from investment_agent.trading.risk.regime_budget import (
    REGIME_BUDGET_VERSION,
    regime_from_benchmark_prices,
    tighten_for_regime,
)
from investment_agent.platform.logging import get_logger
from investment_agent.execution.brokers.toss.client import resolve_account_seq
from investment_agent.execution.orders.snapshots import AccountSnapshot
from investment_agent.execution.orders.toss_snapshot import capture_toss_account_snapshot

log = get_logger(__name__)
_SOURCE_VERSION = "tradingagents-optimizer-portfolio-v2"


@dataclass(frozen=True)
class PortfolioEvaluation:
    """한 계좌 상태(실계좌든 가상계좌든)에 대한 목표 포트폴리오와 위험 판정.

    저장하지 않는다. 실계좌 경로는 이것을 판단·실행 원장에 기록하고, Shadow·Paper 가상계좌는
    자기 원장에만 기록한다 — 가상계좌 snapshot이 실계좌 원장에 섞이면 실주문 게이트가 가짜
    잔고를 읽는다.
    """

    run_id: str
    decision_at: datetime
    active_batch_id: str
    requested_symbols: tuple[str, ...]
    proposal: object
    risk: object
    risk_policy: PortfolioRiskPolicy


@dataclass(frozen=True)
class PortfolioConstructionOutcome:
    """ops가 raw DB 조회 없이 다음 단계를 연결하는 안정적 식별자 묶음이다."""

    run_id: str
    active_batch_id: str
    proposal_id: str
    risk_decision_id: str
    account_snapshot_id: str | None
    is_approved: bool
    persisted: bool


def _args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.trading.portfolio.construct")
    parser.add_argument("--batch-id")
    parser.add_argument("--account-seq", type=int)
    parser.add_argument("--as-of")
    parser.add_argument("--stage", choices=("shadow", "paper", "live"), default="shadow")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def _market_risk_metrics(
    repository: SupabaseRepository,
    *,
    weights: dict[str, float],
    as_of_at: datetime,
) -> MarketRiskMetrics | None:
    """DB에 point-in-time 가격 이력이 있을 때만 RiskGate 입력을 계산한다."""
    if not hasattr(repository, "market_prices"):
        return None
    symbols = sorted({symbol for symbol, weight in weights.items() if symbol != CASH_SYMBOL and weight > 0.0})
    if not symbols:
        return calculate_market_risk({}, target_weights=weights)
    rows_by_symbol = {
        symbol: repository.market_prices(symbol, as_of_at, limit=260)
        for symbol in (*symbols, "SPY")
    }
    return calculate_market_risk(rows_by_symbol, target_weights=weights)


def _filled_order_costs() -> list[dict]:
    """실행 원장의 실제 체결 비용. 원장이 없는 환경(분석 전용)에서는 빈 목록이다."""
    from investment_agent.execution.db import filled_order_costs
    try:
        return filled_order_costs()
    except Exception as exc:  # noqa: BLE001 - 보정 재료가 없어도 추정 비용으로 계속한다
        log.warning("filled order costs unavailable; estimated trading costs apply: %s", type(exc).__name__)
        return []


def _optimizer_betas(
    repository: SupabaseRepository,
    *,
    symbols: tuple[str, ...],
    held_symbols: tuple[str, ...],
    as_of_at: datetime,
) -> dict[str, float] | None:
    """신호 종목과 고정될 미분석 보유 전부의 시장 베타. optimizer 베타 제약의 재료다."""
    if not hasattr(repository, "market_prices"):
        return None
    wanted = tuple(sorted(set(symbols) | set(held_symbols)))
    rows = {symbol: repository.market_prices(symbol, as_of_at, limit=260) for symbol in (*wanted, "SPY")}
    return estimate_betas(rows, symbols=wanted)


def _stress_sensitivities(
    repository: SupabaseRepository,
    *,
    symbols: tuple[str, ...],
    as_of_at: datetime,
) -> dict[str, dict[str, float]] | None:
    """목표 비중 종목의 스트레스 시나리오 민감도. 대표 ETF 이력이 없으면 ContractError."""
    if not hasattr(repository, "market_prices"):
        return None
    rows = {
        symbol: repository.market_prices(symbol, as_of_at, limit=260)
        for symbol in (*symbols, *STRESS_PROXIES)
    }
    return scenario_sensitivities(rows, symbols=symbols)


def _optimizer_market_inputs(
    repository: SupabaseRepository,
    *,
    symbols: tuple[str, ...],
    as_of_at: datetime,
) -> tuple[MarketCovariance | None, dict[str, TradingCostInputs] | None]:
    """같은 PIT 일봉 한 번으로 공분산과 거래비용 재료를 함께 만든다.

    둘을 따로 조회하면 종목당 왕복이 두 배가 되고, 서로 다른 시점의 봉을 볼 수도 있다.
    """
    if not hasattr(repository, "market_prices"):
        return None, None
    rows_by_symbol = {
        symbol: repository.market_prices(symbol, as_of_at, limit=260)
        for symbol in symbols
    }
    # 기대수익과 같은 기간으로 위험을 잰다. 기간이 다르면 위험 회피 계수가 조용히 몇 배로 바뀐다.
    covariance = calculate_market_covariance(
        rows_by_symbol,
        symbols=symbols,
        horizon_days=SIGNAL_HORIZON_DAYS,
    )
    costs = calibrate_trading_costs(
        estimate_trading_costs(rows_by_symbol, symbols=symbols),
        _filled_order_costs(),
    )
    return covariance, costs


def _market_regime(repository: SupabaseRepository, *, as_of_at: datetime, stage: str):
    """벤치마크 일봉으로 regime을 만든다.

    Shadow는 regime을 못 만들어도 기본 한도로 관찰을 이어간다. paper/live는 멈춘다 — regime을
    모르는 날은 위기일 수도 있는 날이고, 그때 평상시 한도로 주문하면 조이기만 하는 위험 예산이
    가장 필요한 순간에 꺼진다.
    """
    if not hasattr(repository, "market_prices"):
        if stage != "shadow":
            raise ContractError("market regime inputs are unavailable for a trading stage")
        return None
    try:
        return regime_from_benchmark_prices(
            repository.market_prices("SPY", as_of_at, limit=260), as_of_at=as_of_at,
        )
    except ContractError as exc:
        if stage != "shadow":
            raise
        log.warning("market regime unavailable; base risk limits apply in shadow: %s", exc)
        return None


def _optimizer_policy_for(risk_policy: PortfolioRiskPolicy, *, unanalyzed_weight: float) -> OptimizerPolicy:
    """optimizer에 같은 한도를 넘긴다. 최소 현금은 고정된 미분석 보유가 허용하는 만큼만 요구한다.

    미분석 보유는 optimizer가 움직일 수 없어, regime이 올린 최소 현금이 그보다 크면 문제가
    풀리지 않는다. 그 나머지는 RiskGate가 보유 전체를 비례로 현금화해 채운다(위험 축소 방향).
    """
    feasible_cash = max(0.0, 1.0 - unanalyzed_weight)
    return OptimizerPolicy(
        max_symbol_weight=risk_policy.max_symbol_weight,
        max_sector_weight=risk_policy.max_sector_weight,
        max_turnover=risk_policy.max_turnover,
        min_cash_weight=min(risk_policy.min_cash_weight, feasible_cash),
        allow_increases=risk_policy.allow_risk_increase,
        max_portfolio_beta=risk_policy.max_abs_beta,
    )


def _require_promotion(repository: SupabaseRepository, signal_book, active_batch_id: str, stage: str) -> None:
    if stage == "shadow":
        return
    artifact_id = signal_book.batch(active_batch_id).model_artifact_id
    if not artifact_id or not repository.has_approved_promotion(artifact_id, stage):
        raise RuntimeError(f"active TradingAgents artifact has not been manually promoted to {stage}")


def evaluate_portfolio(
    repository: SupabaseRepository,
    *,
    signal_book,
    active_batch_id: str,
    snapshot: AccountSnapshot,
    expected_account_id: str,
    stage: str,
) -> PortfolioEvaluation:
    """계좌 상태 하나에 대해 목표 비중과 RiskDecision을 만든다. 아무것도 저장하지 않는다."""
    if stage not in {"shadow", "paper", "live"}:
        raise ValueError("stage must be shadow, paper, or live")
    _require_promotion(repository, signal_book, active_batch_id, stage)
    active_batch = signal_book.batch(active_batch_id)
    decision_at = parse_datetime(snapshot.captured_at)
    tracked = repository.current_tracked_tickers()
    run_id = stable_id("portfolio_run", {
        "active_batch_id": active_batch_id,
        "snapshot_id": snapshot.snapshot_id,
        "decision_at": decision_at.isoformat(),
        "source_version": _SOURCE_VERSION,
        "stage": stage,
    })
    candidate_symbols = sorted(
        set(position.ticker for position in snapshot.positions)
        | set(active_batch.requested_symbols)
    )
    sectors = repository.sp500_sector_map(candidate_symbols)
    active_records = signal_book.valid_records_for_batch(active_batch_id, as_of_at=decision_at)
    optimizer_symbols = tuple(sorted(active_records))
    try:
        optimizer_covariance, trading_costs = _optimizer_market_inputs(
            repository,
            symbols=optimizer_symbols,
            as_of_at=decision_at,
        )
    except ContractError as exc:
        if stage != "shadow":
            raise
        # Shadow는 공분산·거래비용 적재 전에도 관찰을 이어가되, 원장에 fallback을 남긴다.
        log.warning("optimizer market inputs unavailable: %s", exc)
        optimizer_covariance, trading_costs = None, None
    regime = _market_regime(repository, as_of_at=decision_at, stage=stage)
    risk_policy = tighten_for_regime(PortfolioRiskPolicy(), regime)
    unanalyzed_weight = sum(
        weight for symbol, weight in snapshot.weights.items()
        if symbol != CASH_SYMBOL and symbol not in active_records
    )
    regime_metadata = {
        "market_regime": (
            {
                "risk_state": regime.risk_state,
                "regime_id": regime.regime_id,
                "trend": regime.trend,
                "volatility_state": regime.volatility_state,
                "inputs": dict(regime.metadata.get("inputs", {})),
            }
            if regime is not None else None
        ),
        "regime_budget_version": REGIME_BUDGET_VERSION,
    }
    held_unanalyzed = tuple(sorted(
        symbol for symbol in snapshot.weights if symbol != CASH_SYMBOL and symbol not in active_records
    ))
    try:
        optimizer_betas = _optimizer_betas(
            repository, symbols=optimizer_symbols, held_symbols=held_unanalyzed, as_of_at=decision_at,
        )
    except ContractError as exc:
        if stage != "shadow":
            raise
        log.warning("optimizer betas unavailable: %s", exc)
        optimizer_betas = None
    proposal = PortfolioConstructor().construct_optimized(
        run_id=run_id,
        source_version=_SOURCE_VERSION,
        stage=stage,
        as_of_at=decision_at,
        active_batch_id=active_batch_id,
        signal_book=signal_book,
        snapshot=snapshot,
        expected_account_id=expected_account_id,
        tracked_symbols=tracked,
        sector_by_symbol=sectors,
        covariance=(optimizer_covariance.matrix if optimizer_covariance else None),
        covariance_symbols=(optimizer_covariance.symbols if optimizer_covariance else None),
        covariance_metadata=(optimizer_covariance.to_metadata() if optimizer_covariance else None),
        trading_costs=trading_costs,
        optimizer_policy=_optimizer_policy_for(risk_policy, unanalyzed_weight=unanalyzed_weight),
        extra_metadata=regime_metadata,
        betas=optimizer_betas,
    )
    target_symbols = sorted(set(proposal.weights) - {CASH_SYMBOL})
    try:
        market_risk = _market_risk_metrics(
            repository,
            weights=proposal.weights,
            as_of_at=decision_at,
        )
    except ContractError as exc:
        # paper/live는 누락된 값 자체를 RiskGate가 거부한다. shadow는 검증 재료가 없는
        # 상태도 저장해 다음 데이터 적재 전에 관찰할 수 있도록 둔다.
        log.warning("market risk inputs unavailable: %s", exc)
        market_risk = None
    try:
        stress_sensitivities = _stress_sensitivities(repository, symbols=tuple(target_symbols), as_of_at=decision_at)
    except ContractError as exc:
        if stage != "shadow":
            raise
        log.warning("stress sensitivities unavailable in shadow: %s", exc)
        stress_sensitivities = None
    risk = DeterministicRiskGate(risk_policy).evaluate(
        proposal,
        current_weights=snapshot.weights,
        tradable_symbols=set(tracked) | {position.ticker for position in snapshot.positions},
        decided_at=decision_at,
        sector_by_symbol=repository.sp500_sector_map(target_symbols),
        portfolio_volatility=(market_risk.portfolio_volatility if market_risk else None),
        portfolio_beta=(market_risk.portfolio_beta if market_risk else None),
        max_pairwise_correlation=(market_risk.max_pairwise_correlation if market_risk else None),
        drawdown_fraction=(market_risk.drawdown_fraction if market_risk else None),
        historical_cvar_95_5d=(market_risk.historical_cvar_95_5d if market_risk else None),
        stress_sensitivities=stress_sensitivities,
        market_risk_metadata={
            **(market_risk.to_metadata() if market_risk else {}),
            **regime_metadata,
        },
    )
    return PortfolioEvaluation(
        run_id=run_id,
        decision_at=decision_at,
        active_batch_id=active_batch_id,
        requested_symbols=tuple(active_batch.requested_symbols),
        proposal=proposal,
        risk=risk,
        risk_policy=risk_policy,
    )


def construct_portfolio(
    *,
    batch_id: str | None = None,
    account_seq: int | None = None,
    as_of_at: str | datetime | None = None,
    stage: str = "shadow",
    dry_run: bool = False,
    repository: SupabaseRepository | None = None,
) -> PortfolioConstructionOutcome:
    """명시한 batch와 실제 토스 계좌로 포트폴리오를 만들고 후속 단계에 쓸 ID를 직접 반환한다."""
    if stage not in {"shadow", "paper", "live"}:
        raise ValueError("stage must be shadow, paper, or live")
    as_of = parse_datetime(as_of_at) if as_of_at is not None else datetime.now(timezone.utc)
    selected_repository = repository or SupabaseRepository()
    active_batch_id = batch_id or selected_repository.latest_signal_batch_id(as_of_at=as_of)
    if active_batch_id is None:
        raise RuntimeError("no completed TradingAgents signal batch is available")
    signal_book = selected_repository.load_signal_book(as_of_at=as_of)
    # 계좌를 읽기 전에 승격부터 확인한다 — 승격되지 않은 조합으로 브로커를 부르지 않는다.
    _require_promotion(selected_repository, signal_book, active_batch_id, stage)
    resolved_account_seq = resolve_account_seq(account_seq)
    # 실제 조회 완료 시각을 포트폴리오 결정 시각으로 사용한다.
    snapshot = capture_toss_account_snapshot(account_seq=resolved_account_seq)
    evaluation = evaluate_portfolio(
        selected_repository,
        signal_book=signal_book,
        active_batch_id=active_batch_id,
        snapshot=snapshot,
        expected_account_id=str(resolved_account_seq),
        stage=stage,
    )
    run_id = evaluation.run_id
    decision_at = evaluation.decision_at
    proposal = evaluation.proposal
    risk = evaluation.risk
    risk_policy = evaluation.risk_policy
    target_symbols = sorted(set(proposal.weights) - {CASH_SYMBOL})
    if dry_run:
        log.info(
            "full portfolio dry-run batch=%s snapshot=%s positions=%d approved=%s",
            active_batch_id, snapshot.snapshot_id, len(target_symbols), risk.is_approved,
        )
        return PortfolioConstructionOutcome(
            run_id=run_id,
            active_batch_id=active_batch_id,
            proposal_id=proposal.proposal_id,
            risk_decision_id=risk.risk_decision_id,
            account_snapshot_id=None,
            is_approved=risk.is_approved,
            persisted=False,
        )

    selected_repository.save_policy({
        "policy_key": risk_policy.key,
        "policy_version": risk_policy.version,
        "stage": stage,
        "model_provider": "deterministic_python",
        "model_name": "DeterministicRiskGate",
        "prompt_version": "none",
        "config": risk_policy.to_config(),
    })
    account_snapshot_id = selected_repository.save_portfolio_snapshot(snapshot)
    if account_snapshot_id is None:
        raise RuntimeError("execution account snapshot writer returned no snapshot id")
    selected_repository.save_decision_run({
        "run_id": run_id,
        "as_of_at": decision_at.isoformat(),
        "stage": stage,
        "status": "running",
        "candidate_tickers": list(evaluation.requested_symbols),
        "account_snapshot_id": account_snapshot_id,
        "code_commit": None,
        "failure_reason": None,
    })
    proposal_row = proposal.to_dict()
    proposal_row["account_snapshot_id"] = str(account_snapshot_id)
    selected_repository.save_portfolio_proposal(proposal_row)
    selected_repository.save_risk_decision(risk.to_dict())
    decision_identity = {
        "run_id": run_id,
        "proposal_id": proposal.proposal_id,
        "risk_decision_id": risk.risk_decision_id,
    }
    selected_repository.save_portfolio_decision({
        "decision_id": stable_id("decision", decision_identity),
        **decision_identity,
        "champion_policy": {
            "source_type": proposal.source_type,
            "source_version": proposal.source_version,
            "automatic_promotion": False,
        },
        "status": "approved" if risk.is_approved else "rejected",
    })
    selected_repository.finish_decision_run(run_id, status="completed")
    log.info(
        "full portfolio stored run_id=%s proposal_id=%s snapshot=%s risk_approved=%s",
        run_id, proposal.proposal_id, snapshot.snapshot_id, risk.is_approved,
    )
    return PortfolioConstructionOutcome(
        run_id=run_id,
        active_batch_id=active_batch_id,
        proposal_id=proposal.proposal_id,
        risk_decision_id=risk.risk_decision_id,
        account_snapshot_id=str(account_snapshot_id),
        is_approved=risk.is_approved,
        persisted=True,
    )


def main(argv: list[str] | None = None) -> int:
    args = _args(argv)
    outcome = construct_portfolio(
        batch_id=args.batch_id,
        account_seq=args.account_seq,
        as_of_at=args.as_of,
        stage=args.stage,
        dry_run=args.dry_run,
    )
    return 0 if outcome.is_approved else 1


__all__ = ["PortfolioConstructionOutcome", "PortfolioEvaluation", "construct_portfolio", "evaluate_portfolio", "main"]


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
