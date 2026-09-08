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
    calculate_market_covariance,
    calculate_market_risk,
)
from investment_agent.trading.risk.gate import DeterministicRiskGate, PortfolioRiskPolicy
from investment_agent.platform.logging import get_logger
from investment_agent.execution.brokers.toss.client import resolve_account_seq
from investment_agent.execution.orders.toss_snapshot import capture_toss_account_snapshot

log = get_logger(__name__)
_SOURCE_VERSION = "tradingagents-optimizer-portfolio-v2"


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


def _optimizer_covariance(
    repository: SupabaseRepository,
    *,
    symbols: tuple[str, ...],
    as_of_at: datetime,
) -> MarketCovariance | None:
    """Optimizer 입력 종목 순서 그대로 point-in-time 공분산을 계산한다."""
    if not hasattr(repository, "market_prices"):
        return None
    rows_by_symbol = {
        symbol: repository.market_prices(symbol, as_of_at, limit=260)
        for symbol in symbols
    }
    # 현재 TradingAgents ExpectedReturnSignal은 모두 5거래일 horizon이다.
    return calculate_market_covariance(
        rows_by_symbol,
        symbols=symbols,
        horizon_days=5,
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
    """명시한 batch로 포트폴리오를 만들고 후속 단계에 쓸 ID를 직접 반환한다."""
    if stage not in {"shadow", "paper", "live"}:
        raise ValueError("stage must be shadow, paper, or live")
    as_of = parse_datetime(as_of_at) if as_of_at is not None else datetime.now(timezone.utc)
    selected_repository = repository or SupabaseRepository()
    active_batch_id = batch_id or selected_repository.latest_signal_batch_id(as_of_at=as_of)
    if active_batch_id is None:
        raise RuntimeError("no completed TradingAgents signal batch is available")
    signal_book = selected_repository.load_signal_book(as_of_at=as_of)
    active_batch = signal_book.batch(active_batch_id)
    if stage != "shadow":
        artifact_id = active_batch.model_artifact_id
        if not artifact_id or not selected_repository.has_approved_promotion(
            artifact_id,
            stage,
        ):
            raise RuntimeError(
                f"active TradingAgents artifact has not been manually promoted to {stage}"
            )
    resolved_account_seq = resolve_account_seq(account_seq)
    # 실제 조회 완료 시각을 포트폴리오 결정 시각으로 사용한다.
    snapshot = capture_toss_account_snapshot(account_seq=resolved_account_seq)
    decision_at = parse_datetime(snapshot.captured_at)
    tracked = selected_repository.current_tracked_tickers()
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
    sectors = selected_repository.sp500_sector_map(candidate_symbols)
    active_records = signal_book.valid_records_for_batch(active_batch_id, as_of_at=decision_at)
    optimizer_symbols = tuple(sorted(active_records))
    try:
        optimizer_covariance = _optimizer_covariance(
            selected_repository,
            symbols=optimizer_symbols,
            as_of_at=decision_at,
        )
    except ContractError as exc:
        if stage != "shadow":
            raise
        # Shadow는 공분산 적재 전에도 관찰을 이어가되, 원장에 fallback을 남긴다.
        log.warning("optimizer covariance unavailable: %s", exc)
        optimizer_covariance = None
    proposal = PortfolioConstructor().construct_optimized(
        run_id=run_id,
        source_version=_SOURCE_VERSION,
        stage=stage,
        as_of_at=decision_at,
        active_batch_id=active_batch_id,
        signal_book=signal_book,
        snapshot=snapshot,
        expected_account_id=str(resolved_account_seq),
        tracked_symbols=tracked,
        sector_by_symbol=sectors,
        covariance=(optimizer_covariance.matrix if optimizer_covariance else None),
        covariance_symbols=(optimizer_covariance.symbols if optimizer_covariance else None),
        covariance_metadata=(optimizer_covariance.to_metadata() if optimizer_covariance else None),
    )
    risk_policy = PortfolioRiskPolicy()
    target_symbols = sorted(set(proposal.weights) - {CASH_SYMBOL})
    try:
        market_risk = _market_risk_metrics(
            selected_repository,
            weights=proposal.weights,
            as_of_at=decision_at,
        )
    except ContractError as exc:
        # paper/live는 누락된 값 자체를 RiskGate가 거부한다. shadow는 검증 재료가 없는
        # 상태도 저장해 다음 데이터 적재 전에 관찰할 수 있도록 둔다.
        log.warning("market risk inputs unavailable: %s", exc)
        market_risk = None
    risk = DeterministicRiskGate(risk_policy).evaluate(
        proposal,
        current_weights=snapshot.weights,
        tradable_symbols=set(tracked) | {position.ticker for position in snapshot.positions},
        decided_at=decision_at,
        sector_by_symbol=selected_repository.sp500_sector_map(target_symbols),
        portfolio_volatility=(market_risk.portfolio_volatility if market_risk else None),
        portfolio_beta=(market_risk.portfolio_beta if market_risk else None),
        max_pairwise_correlation=(market_risk.max_pairwise_correlation if market_risk else None),
        drawdown_fraction=(market_risk.drawdown_fraction if market_risk else None),
        market_risk_metadata=(market_risk.to_metadata() if market_risk else None),
    )
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
        "candidate_tickers": list(active_batch.requested_symbols),
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


__all__ = ["PortfolioConstructionOutcome", "construct_portfolio", "main"]


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
