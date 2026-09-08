"""LLM·ML·RL 세 예측기를 하나의 실행 후보 묶음으로 모은다.

세 예측기는 **출력 모양이 다르다**. LLM과 ML은 종목별 기대수익을 내고, RL은 포트폴리오
비중을 통째로 낸다. 그래서 합치는 지점이 둘이다.

```text
LLM desk 의견 ─┐
               ├→ fuse_signals ─→ optimizer signal ─→ RiskAwareOptimizer ─→ 제안 A (optimizer)
ML 수치 예측 ─┘
RL 정책 ───────────────────────────────────────────────────────────────→ 제안 B (rl)
                                                                             ↓
                                                        둘 다 같은 DeterministicRiskGate
```

RL 비중을 기대수익으로 되돌려 섞지 않는다. 비중에서 수익률을 역산하면 없는 정보를
지어내는 것이고, 두 제안을 나란히 심사해 등록된 champion만 고르는 편이 정직하다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from investment_agent.trading.contracts import ContractError, parse_datetime
from investment_agent.trading.portfolio.contracts import PortfolioProposal
from investment_agent.trading.portfolio.optimizer import ExpectedReturnSignal as OptimizerSignal
from investment_agent.trading.decision.contracts import ExpectedReturnSignal as IntelligenceSignal

_HORIZON_FIELD = {
    1: "expected_1d_return",
    5: "expected_5d_return",
    20: "expected_20d_return",
}
_HORIZON_BY_LABEL = {"1d": 1, "5d": 5, "20d": 20}


def to_optimizer_signal(
    signal: IntelligenceSignal,
    *,
    horizon_days: int | None = None,
    source: str = "fusion",
    version: str = "ensemble-v1",
) -> OptimizerSignal:
    """fusion 결과를 optimizer가 받는 좁은 계약으로 옮긴다.

    `uncertainty`가 곧 `risk_score`다 — 모델들이 서로 다른 방향을 가리킬수록 fusion이
    uncertainty를 올리고, optimizer는 그만큼 그 종목을 덜 담는다.
    """
    horizon = horizon_days or _HORIZON_BY_LABEL[str(signal.preferred_horizon).lower()]
    if horizon not in _HORIZON_FIELD:
        raise ContractError(f"unsupported optimizer horizon: {horizon}")
    return OptimizerSignal(
        symbol=signal.ticker,
        expected_return=float(getattr(signal, _HORIZON_FIELD[horizon])),
        confidence=float(signal.confidence),
        risk_score=float(signal.uncertainty),
        horizon_days=horizon,
        source=source,
        timestamp=signal.as_of_at,
        version=version,
        evidence_ids=tuple(signal.evidence_ids),
    )


@dataclass(frozen=True)
class EnsembleCandidates:
    """같은 시점·같은 RiskGate를 통과시킬 후보 제안들이다."""

    as_of_at: str
    proposals: tuple[PortfolioProposal, ...]
    signals: tuple[OptimizerSignal, ...]
    contributors: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.proposals:
            raise ContractError("ensemble requires at least one proposal")
        as_of = parse_datetime(self.as_of_at).isoformat()
        sources = [proposal.source_type for proposal in self.proposals]
        if len(sources) != len(set(sources)):
            raise ContractError(f"ensemble proposals must have distinct source types: {sources}")
        for proposal in self.proposals:
            if parse_datetime(proposal.as_of_at) != parse_datetime(as_of):
                raise ContractError(
                    f"ensemble proposal as_of_at disagrees: {proposal.source_type}"
                )
        object.__setattr__(self, "as_of_at", as_of)

    def by_source(self, source_type: str) -> PortfolioProposal | None:
        for proposal in self.proposals:
            if proposal.source_type == source_type:
                return proposal
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_at": self.as_of_at,
            "sources": [proposal.source_type for proposal in self.proposals],
            "proposal_ids": [proposal.proposal_id for proposal in self.proposals],
            "signal_count": len(self.signals),
            "contributors": dict(self.contributors),
        }


def weight_disagreement(left: PortfolioProposal, right: PortfolioProposal) -> float:
    """두 제안이 얼마나 다른 포트폴리오인지 0~1로 잰다.

    총변동거리(비중 차이 절대값 합의 절반)다. 0이면 같은 포트폴리오, 1이면 완전히
    겹치지 않는다. 이 값이 크면 두 모델이 시장을 다르게 읽고 있다는 뜻이라, 어느
    쪽을 champion으로 둘지 사람이 볼 근거가 된다.
    """
    symbols = set(left.weights) | set(right.weights)
    total = sum(
        abs(float(left.weights.get(symbol, 0.0)) - float(right.weights.get(symbol, 0.0)))
        for symbol in symbols
    )
    return round(min(1.0, 0.5 * total), 10)


def collect_candidates(
    *,
    as_of_at: str,
    optimizer_proposal: PortfolioProposal | None = None,
    rl_proposal: PortfolioProposal | None = None,
    signals: Sequence[OptimizerSignal] = (),
    contributors: Mapping[str, Any] | None = None,
) -> EnsembleCandidates:
    """만들어진 제안만 모은다. 없는 예측기를 기본값으로 채우지 않는다."""
    proposals = tuple(
        proposal for proposal in (optimizer_proposal, rl_proposal) if proposal is not None
    )
    detail = dict(contributors or {})
    if optimizer_proposal is not None and rl_proposal is not None:
        detail["weight_disagreement"] = weight_disagreement(optimizer_proposal, rl_proposal)
    return EnsembleCandidates(
        as_of_at=as_of_at,
        proposals=proposals,
        signals=tuple(signals),
        contributors=detail,
    )


__all__ = [
    "EnsembleCandidates",
    "collect_candidates",
    "to_optimizer_signal",
    "weight_disagreement",
]
