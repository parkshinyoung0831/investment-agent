"""구조화 판단(System-One) 계층.

`trading/decision/agents/`의 Deep LLM Multi-Agent(Champion) 옆에 두는 **싼 단계**다.
같은 질문을 결정론 규칙·저비용 LLM·외부 System-One 모델(Jev 등)에게 똑같이 물어
비교할 수 있게 한다(§48).

이 계층은 비중을 정하지 않는다. 최종 비중·주문·hard limit은 Optimizer와
`trading/risk/gate.py`가 소유한다(`SYSTEM_UPGRADE_MASTER.md` §4.2/§4.3).
"""
from __future__ import annotations

from investment_agent.trading.decision.judgment.contracts import (
    Answer,
    JudgmentProvider,
    JudgmentResult,
    Question,
    QuestionSet,
)
from investment_agent.trading.decision.judgment.deterministic import DeterministicJudge
from investment_agent.trading.decision.judgment.questions import question_set, registered_names

__all__ = [
    "Answer",
    "DeterministicJudge",
    "JudgmentProvider",
    "JudgmentResult",
    "Question",
    "QuestionSet",
    "question_set",
    "registered_names",
]
