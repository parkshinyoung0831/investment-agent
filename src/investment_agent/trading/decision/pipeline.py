"""Fast Ranker부터 Fusion까지 이어지는 종목 단위 네이티브 파이프라인."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from investment_agent.trading.contracts import EvidenceBundle
from investment_agent.trading.decision.contracts import AnalystSignal, Event, ExpectedReturnSignal, MarketRegime
from investment_agent.trading.decision.debate import DebatePolicy, run_conditional_debate
from investment_agent.trading.decision.desks import analyze_event, analyze_fundamental, analyze_macro, analyze_market
from investment_agent.trading.decision.fusion import FusionResult, NumericPrediction, fuse_signals
from investment_agent.trading.decision.fast_ranker import FastCandidateRank, FastRankFeatures, FastRankerPolicy, rank_fast_candidates
from investment_agent.trading.decision.regime import build_market_regime


@dataclass(frozen=True)
class IntelligenceResult:
    """한 ticker에 대한 regime·desk·debate·fusion 산출물."""

    regime: MarketRegime
    ranks: tuple[FastCandidateRank, ...]
    desk_signals: tuple[AnalystSignal, ...]
    debate_signal: AnalystSignal | None
    fusion: FusionResult

    @property
    def signal(self) -> ExpectedReturnSignal:
        return self.fusion.signal


def run_intelligence(
    *,
    bundle: EvidenceBundle,
    candidate_features: Sequence[FastRankFeatures] = (),
    numeric_predictions: Sequence[NumericPrediction] = (),
    events: Sequence[Event] = (),
    regime_inputs: Mapping[str, Any] | None = None,
    ranker_policy: FastRankerPolicy | None = None,
    debate_policy: DebatePolicy | None = None,
) -> IntelligenceResult:
    """한 후보에 대해 공통 regime을 만들고 네 desk를 같은 계약으로 실행한다."""
    inputs = dict(regime_inputs or {})
    regime = build_market_regime(
        bundle.as_of_at,
        source_ids=tuple(sorted(bundle.evidence_ids)),
        **inputs,
    )
    ranks = rank_fast_candidates(
        tuple(candidate_features),
        as_of_at=bundle.as_of_at,
        limit=(ranker_policy.max_candidates if ranker_policy else 30),
        policy=ranker_policy,
    ) if candidate_features else ()
    desks = (
        analyze_market(bundle),
        analyze_fundamental(bundle),
        analyze_macro(bundle),
        analyze_event(bundle, events=events),
    )
    debate_signal = run_conditional_debate(
        desks,
        events=events,
        regime=regime,
        policy=debate_policy,
    )
    fused = fuse_signals(
        ticker=bundle.ticker,
        as_of_at=bundle.as_of_at,
        desk_signals=desks,
        numeric_predictions=numeric_predictions,
        debate_signal=debate_signal,
    )
    return IntelligenceResult(
        regime=regime,
        ranks=ranks,
        desk_signals=desks,
        debate_signal=debate_signal,
        fusion=fused,
    )


__all__ = ["IntelligenceResult", "run_intelligence"]
