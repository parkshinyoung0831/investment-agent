"""ETF 전략과 FinRL-X 결과를 공통 목표 비중 계약으로 변환한다."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Sequence

from investment_agent.trading.contracts import ContractError
from investment_agent.trading.portfolio.contracts import (
    CASH_SYMBOL,
    PortfolioProposal,
    SecurityProposal,
)
from investment_agent.trading.portfolio.optimizer import (
    ExpectedReturnSignal,
    OptimizerPolicy,
    RiskAwareOptimizer,
)


def _with_cash(raw_weights: Mapping[str, Any]) -> dict[str, float]:
    weights = {str(symbol).upper(): float(weight) for symbol, weight in raw_weights.items()}
    risky = sum(weight for symbol, weight in weights.items() if symbol != CASH_SYMBOL)
    if CASH_SYMBOL not in weights:
        if risky > 1.0 + 1e-8:
            raise ContractError("risky weights exceed 1 and cannot infer CASH")
        weights[CASH_SYMBOL] = 1.0 - risky
    return weights


def from_strategy_allocation(
    row: Mapping[str, Any],
    *,
    run_id: str,
    as_of_at: str,
) -> PortfolioProposal:
    """ETF 전략을 주문 불가능한 성과 비교용 rule challenger로 편입한다."""
    strategy_id = str(row.get("strategy_id") or "").strip()
    alloc = row.get("weights")
    if not strategy_id or not isinstance(alloc, Mapping):
        raise ContractError("strategy allocation requires strategy_id and alloc")
    return PortfolioProposal.create(
        run_id=run_id,
        source_type="rule",
        source_version=strategy_id,
        stage="shadow",
        as_of_at=as_of_at,
        weights=_with_cash(alloc),
        confidence=1.0,
        reasoning=(f"research.strategy_allocations:{strategy_id}",),
        metadata={
            # 현재 6개 전략은 ETF라 S&P 500 개별주 실행 universe와 섞지 않는다.
            "coverage": "partial_universe",
            "execution_eligible": False,
            "purpose": "benchmark_reference_only",
            "decision_date": row.get("decision_date"),
            "apply_date": row.get("apply_date"),
            "signals": row.get("signals") or {},
        },
    )


def from_finrlx_strategy_result(
    result: Any,
    *,
    run_id: str,
    source_version: str,
    stage: str,
    as_of_at: str,
    confidence: float = 1.0,
) -> PortfolioProposal:
    """FinRL-X StrategyResult를 직접 재사용하되 로컬 저장 계약으로 검증한다."""
    frame = getattr(result, "weights", None)
    strategy_name = str(getattr(result, "strategy_name", "finrlx"))
    if frame is None or not hasattr(frame, "iloc") or len(frame.index) == 0:
        raise ContractError("FinRL-X StrategyResult.weights must contain at least one row")
    latest = frame.iloc[-1]
    weights = _with_cash({str(symbol): float(value) for symbol, value in latest.items()})
    return PortfolioProposal.create(
        run_id=run_id,
        source_type="rl",
        source_version=source_version,
        stage=stage,
        as_of_at=as_of_at,
        weights=weights,
        confidence=confidence,
        reasoning=(f"FinRL-X StrategyResult:{strategy_name}",),
        metadata={
            **dict(getattr(result, "metadata", None) or {}),
            "coverage": "full_portfolio",
        },
    )


def from_security_proposals(
    proposals: list[SecurityProposal],
    *,
    run_id: str,
    source_version: str,
    stage: str = "shadow",
    min_cash_weight: float = 0.05,
    case_keys: tuple[str, ...] = (),
    coverage: str = "partial_universe",
) -> PortfolioProposal:
    """독립 종목 제안을 전 종목 합계가 맞는 LLM 포트폴리오 제안으로 묶는다."""
    if not proposals:
        raise ContractError("at least one security proposal is required")
    as_of_values = {proposal.as_of_at for proposal in proposals}
    if len(as_of_values) != 1:
        raise ContractError("security proposals must share one as_of_at")
    if not 0.0 <= min_cash_weight <= 1.0:
        raise ContractError("min_cash_weight must be between 0 and 1")
    if coverage not in {"partial_universe", "full_portfolio"}:
        raise ContractError("coverage must be partial_universe or full_portfolio")
    weights: dict[str, float] = {}
    active_signals = {"open", "increase", "hold", "reduce"}
    for proposal in sorted(proposals, key=lambda item: item.ticker):
        if proposal.ticker in weights:
            raise ContractError(f"duplicate security proposal: {proposal.ticker}")
        weights[proposal.ticker] = (
            proposal.target_weight if proposal.signal in active_signals else 0.0
        )
    risky = sum(weights.values())
    max_risky = 1.0 - min_cash_weight
    if risky > max_risky and risky > 0.0:
        scale = max_risky / risky
        weights = {symbol: weight * scale for symbol, weight in weights.items()}
        risky = max_risky
    weights[CASH_SYMBOL] = 1.0 - risky
    confidence = sum(proposal.confidence for proposal in proposals) / len(proposals)
    return PortfolioProposal.create(
        run_id=run_id,
        source_type="llm",
        source_version=source_version,
        stage=stage,
        as_of_at=next(iter(as_of_values)),
        weights=weights,
        confidence=confidence,
        reasoning=(
            "TradingAgents 종목별 예비 target_weight를 합산",
            f"현금 최소 비중 {min_cash_weight:.4f}를 적용",
        ),
        case_keys=case_keys,
        metadata={
            "coverage": coverage,
            "security_proposal_count": len(proposals),
            "analyzed_symbols": sorted(proposal.ticker for proposal in proposals),
        },
    )


def from_optimized_security_proposals(
    proposals: list[SecurityProposal],
    *,
    run_id: str,
    source_version: str,
    current_weights: Mapping[str, float],
    stage: str = "shadow",
    case_keys: tuple[str, ...] = (),
    coverage: str = "partial_universe",
    sector_by_symbol: Mapping[str, str] | None = None,
    optimizer_policy: OptimizerPolicy | None = None,
    covariance: Sequence[Sequence[float]] | None = None,
    covariance_symbols: Sequence[str] | None = None,
    covariance_metadata: Mapping[str, Any] | None = None,
    preserve_unanalyzed_holdings: bool = False,
) -> PortfolioProposal:
    """LLM의 target_weight를 폐기하고 expected-return signal만 최적화한다."""
    if not proposals:
        raise ContractError("at least one security proposal is required")
    as_of_values = {proposal.as_of_at for proposal in proposals}
    if len(as_of_values) != 1:
        raise ContractError("security proposals must share one as_of_at")
    if coverage not in {"partial_universe", "full_portfolio"}:
        raise ContractError("coverage must be partial_universe or full_portfolio")
    signals = tuple(
        ExpectedReturnSignal.from_security_proposal(
            proposal,
            source="tradingagents",
            version=source_version,
            horizon_days=5,
        )
        for proposal in sorted(proposals, key=lambda item: item.ticker)
    )
    signal_symbols = tuple(signal.symbol for signal in signals)
    if covariance is not None:
        if covariance_symbols is None:
            raise ContractError("covariance symbols are required with covariance")
        normalized_covariance_symbols = tuple(str(symbol).upper().strip() for symbol in covariance_symbols)
        if normalized_covariance_symbols != signal_symbols:
            raise ContractError("covariance symbol order must match optimizer signals")
    elif covariance_symbols is not None or covariance_metadata is not None:
        raise ContractError("covariance values are required with covariance metadata")
    fixed_weights = (
        {
            symbol: weight
            for symbol, weight in current_weights.items()
            if str(symbol).upper() not in {CASH_SYMBOL, *(signal.symbol for signal in signals)}
        }
        if preserve_unanalyzed_holdings
        else None
    )
    optimization = RiskAwareOptimizer(optimizer_policy).optimize(
        signals,
        current_weights=current_weights,
        covariance=covariance,
        sector_by_symbol=sector_by_symbol,
        fixed_weights=fixed_weights,
    )
    confidence = sum(signal.confidence for signal in signals) / len(signals)
    return PortfolioProposal.create(
        run_id=run_id,
        source_type="optimizer",
        source_version=f"optimizer:{source_version}",
        stage=stage,
        as_of_at=next(iter(as_of_values)),
        weights=optimization.weights,
        confidence=confidence,
        reasoning=(
            "TradingAgents는 expected return/confidence/risk signal만 제공",
            "cvxpy mean-variance-turnover optimizer가 목표 비중을 결정",
            "LLM target_weight는 최적화 입력에서 제외",
        ),
        case_keys=case_keys,
        metadata={
            "coverage": coverage,
            "execution_eligible": coverage == "full_portfolio",
            "security_proposal_count": len(proposals),
            "analyzed_symbols": [signal.symbol for signal in signals],
            "signal_contracts": [asdict(signal) for signal in signals],
            "optimizer": {
                "solver": optimization.solver,
                "policy_hash": optimization.policy_hash,
                "input_hash": optimization.input_hash,
                "expected_return": optimization.expected_return,
                "estimated_variance": optimization.estimated_variance,
                "turnover": optimization.turnover,
                "expected_return_component": optimization.expected_return_component,
                "risk_penalty": optimization.risk_penalty,
                "turnover_penalty": optimization.turnover_penalty,
                "objective_value": optimization.objective_value,
                "covariance": (
                    dict(covariance_metadata or {})
                    if covariance is not None
                    else {"method": "signal_risk_score_diagonal"}
                ),
            },
            "llm_target_weight_used": False,
            "preserved_unanalyzed_holdings": preserve_unanalyzed_holdings,
        },
    )
