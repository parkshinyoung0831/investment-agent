"""RL baseline이 낸 비중을 실행 권한 없는 challenger 제안으로 감싼다."""
from __future__ import annotations

from typing import Mapping

from investment_agent.trading.portfolio.contracts import PortfolioProposal


def rl_challenger_proposal(
    *,
    run_id: str,
    stage: str,
    as_of_at: str,
    weights: Mapping[str, float],
    source_version: str,
    model_artifact_id: str,
    input_hash: str,
    membership_hash: str,
) -> PortfolioProposal:
    """연구가 계산한 비중에 출처·입력 hash를 붙이되 주문 자격은 주지 않는다."""
    return PortfolioProposal.create(
        run_id=run_id,
        source_type="rl",
        source_version=source_version,
        stage=stage,
        as_of_at=as_of_at,
        weights=weights,
        confidence=0.5,
        reasoning=("point-in-time 선형 ridge baseline challenger 추론",),
        model_artifact_id=model_artifact_id,
        metadata={
            "coverage": "partial_universe",
            "execution_eligible": False,
            "purpose": "rl_baseline_challenger",
            "inference_input_hash": input_hash,
            "membership_hash": membership_hash,
        },
    )
