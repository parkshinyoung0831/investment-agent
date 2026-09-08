"""투자 Agent 구현을 교체 가능한 인터페이스로 제한한다."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from investment_agent.trading.contracts import EvidenceBundle
from investment_agent.trading.portfolio.contracts import SecurityProposal


@dataclass(frozen=True)
class AgentEngineResult:
    engine: str
    engine_version: str
    proposal: SecurityProposal
    role_outputs: dict[str, Any]
    external_evidence: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "engine_version": self.engine_version,
            "proposal": self.proposal.to_dict(),
            "role_outputs": self.role_outputs,
            "external_evidence": list(self.external_evidence),
        }


class DecisionEngine(Protocol):
    name: str
    version: str

    def run(self, bundle: EvidenceBundle, *, memory_text: str) -> AgentEngineResult: ...
