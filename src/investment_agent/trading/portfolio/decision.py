"""자동 승격 없이 명시된 Champion 제안만 선택하는 결정 계층."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from investment_agent.trading.contracts import ContractError
from investment_agent.trading.portfolio.contracts import PortfolioProposal


@dataclass(frozen=True)
class ChampionPolicy:
    source_type: str
    source_version: str
    model_artifact_id: str | None = None


def select_champion(
    proposals: Iterable[PortfolioProposal],
    policy: ChampionPolicy,
) -> PortfolioProposal:
    """성과가 좋아 보여도 등록되지 않은 challenger는 선택하지 않는다."""
    matches = [
        proposal for proposal in proposals
        if proposal.source_type == policy.source_type
        and proposal.source_version == policy.source_version
        and proposal.model_artifact_id == policy.model_artifact_id
    ]
    if len(matches) != 1:
        raise ContractError(f"expected exactly one champion proposal, found {len(matches)}")
    return matches[0]
