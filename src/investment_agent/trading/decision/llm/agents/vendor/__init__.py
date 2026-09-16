"""외부 오픈소스에서 가져온, 프레임워크 의존이 없는 데이터 fetcher 모음.

TradingAgents(Apache-2.0, https://github.com/TauricResearch/TradingAgents,
commit a33fd4c0f134485a43553a2c23a63cb14adbd88f)의 `dataflows/` 하위 유틸리티 중
그래프·LLM 프레임워크에 의존하지 않는 순수 REST/라이브러리 fetcher만 이 패키지로
옮겨 왔다. 나머지(그래프·에이전트·토론 로직)는 `investment_agent.trading.decision.llm.agents`
아래에 자체 구현으로 대체했다.
"""
from __future__ import annotations
