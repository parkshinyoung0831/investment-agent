"""분석가 5명 → Bull/Bear 토론 → Research Manager → Trader → Risk 3자 토론 →
Portfolio Manager를 고정 순서로 실행하는 로컬 그래프.

업스트림 LangGraph도 토론 라운드는 고정 횟수 루프였을 뿐(기본 Bull/Bear 2턴, Risk 3턴) 동적
라우팅의 이점이 없었다 — 그래프 엔진 없이 그냥 순서대로 부른다. `TradingAgentsRunner.run()`이
돌려주던 것과 같은 키 모양의 dict를 만들어, 그 위(citation 재요청·구조화 계약)는 그대로 둔다.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable

from investment_agent.trading.decision.agents import analysts, debate, risk_debate, trader
from investment_agent.trading.decision.agents.graph_state import AnalystReports
from investment_agent.trading.decision.llm.client import LLMClient


def run_local_graph(
    client: LLMClient,
    *,
    ticker: str,
    curr_date: str,
    fetch_market_evidence: Callable[[], str],
    fetch_fundamentals_evidence: Callable[[], str],
    fetch_news_evidence: Callable[[], str],
    fetch_sentiment_evidence: Callable[[], str],
    fetch_macro_evidence: Callable[[], str],
    max_debate_rounds: int = 1,
    max_risk_discuss_rounds: int = 1,
    macro_report_cache: dict[str, str] | None = None,
) -> dict[str, Any]:
    """옛 `TradingAgentsRunner.run()`이 반환하던 것과 같은 키 모양의 dict를 만든다."""
    reports = AnalystReports(
        market_report=analysts.run_market_analyst(
            client, ticker=ticker, curr_date=curr_date, evidence_text=fetch_market_evidence(),
        ),
        fundamentals_report=analysts.run_fundamentals_analyst(
            client, ticker=ticker, curr_date=curr_date, evidence_text=fetch_fundamentals_evidence(),
        ),
        news_report=analysts.run_news_analyst(
            client, ticker=ticker, curr_date=curr_date, evidence_text=fetch_news_evidence(),
        ),
        sentiment_report=analysts.run_sentiment_analyst(
            client, ticker=ticker, curr_date=curr_date, evidence_text=fetch_sentiment_evidence(),
        ),
        macro_report=analysts.run_macro_analyst(
            client, ticker=ticker, curr_date=curr_date, evidence_text=fetch_macro_evidence(),
            cache=macro_report_cache,
        ),
    )

    debate_state = debate.run_bull_bear_debate(client, reports=reports, max_rounds=max_debate_rounds)
    debate_state = debate.run_research_manager(client, reports=reports, state=debate_state)

    trader_plan = trader.run_trader(client, reports=reports, debate_state=debate_state)

    risk_state = risk_debate.run_risk_debate(
        client, reports=reports, trader_plan=trader_plan, max_rounds=max_risk_discuss_rounds,
    )
    risk_state, final_trade_decision = risk_debate.run_portfolio_manager(
        client, reports=reports, trader_plan=trader_plan, state=risk_state,
    )

    return {
        "market_report": reports.market_report,
        "sentiment_report": reports.sentiment_report,
        "news_report": reports.news_report,
        "fundamentals_report": reports.fundamentals_report,
        "macro_report": reports.macro_report,
        "investment_debate_state": asdict(debate_state),
        "investment_plan": debate_state.judge_decision,
        "trader_investment_plan": trader_plan,
        "risk_debate_state": asdict(risk_state),
        "final_trade_decision": final_trade_decision,
    }
