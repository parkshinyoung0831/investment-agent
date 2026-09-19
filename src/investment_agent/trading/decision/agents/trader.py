"""Research Manager의 방향 판단을 근거로 Trader의 계획 텍스트를 만든다."""
from __future__ import annotations

from typing import Any

from investment_agent.platform.serialization import canonical_json
from investment_agent.trading.decision.constants import SIGNAL_HORIZON_DAYS
from investment_agent.trading.decision.agents.graph_state import AnalystReports, InvestDebateState
from investment_agent.trading.decision.llm.client import LLMClient

_TRADER_PLAN_SCHEMA: dict[str, Any] = {
    "plan": "string: Korean prose reasoning about the next "
    f"{SIGNAL_HORIZON_DAYS} trading days, no options/stop-loss/sizing talk",
}


def _reports_payload(reports: AnalystReports) -> dict[str, str]:
    return {
        "market_report": reports.market_report,
        "sentiment_report": reports.sentiment_report,
        "news_report": reports.news_report,
        "fundamentals_report": reports.fundamentals_report,
        "macro_report": reports.macro_report,
    }


def run_trader(
    client: LLMClient, *, reports: AnalystReports, debate_state: InvestDebateState,
) -> str:
    """Research Manager 판단 + 5개 분석가 리포트를 근거로 트레이더 계획을 만든다."""
    system = (
        f"너는 Trader다. Research Manager의 방향 판단과 5개 분석가 리포트를 근거로 앞으로 "
        f"{SIGNAL_HORIZON_DAYS}거래일 동안의 판단 근거를 정리하라. 매수·매도·비중·옵션 전략· "
        "손절가는 말하지 않는다 — 그건 포트폴리오 엔진과 리스크 게이트의 몫이다."
    )
    user = canonical_json({
        "reports": _reports_payload(reports),
        "research_manager_decision": debate_state.judge_decision,
    })
    result = client.complete_json(
        system=system, user=user, output_schema=_TRADER_PLAN_SCHEMA, task_name="tradingagents_trader",
    )
    return str(result["plan"])
