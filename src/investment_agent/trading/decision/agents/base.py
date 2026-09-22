"""투자 Agent 구현을 교체 가능한 인터페이스로 제한한다."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from investment_agent.research.adapters.trading import EvidenceBundle
from investment_agent.trading.portfolio.contracts import SecurityProposal


@dataclass(frozen=True)
class AgentEngineResult:
    engine: str
    engine_version: str
    proposal: SecurityProposal
    role_outputs: dict[str, Any]
    external_evidence: tuple[dict[str, Any], ...] = ()
    # 이 종목을 판단하는 데 든 LLM 토큰·지연(`llm/usage.py`). 판단의 일부가 아니라
    # 그 판단의 비용이라 결과에 싣되 proposal에는 넣지 않는다.
    usage: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "engine_version": self.engine_version,
            "proposal": self.proposal.to_dict(),
            "role_outputs": self.role_outputs,
            "external_evidence": list(self.external_evidence),
            "usage": self.usage,
        }


class DecisionEngine(Protocol):
    name: str
    version: str

    def run(self, bundle: EvidenceBundle, *, memory_text: str) -> AgentEngineResult: ...
