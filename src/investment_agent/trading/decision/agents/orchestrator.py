"""분석가 5명 뒤의 판단 그래프. 운영 기본은 `run_compact_graph`(투자위원회 호출 1번)이고,
`run_local_graph`는 Bull/Bear 토론 → Research Manager → Trader → Risk 3자 토론 → Portfolio Manager를
고정 순서로 실행하는 전체 그래프다(`AI_INVESTOR_AGENT_GRAPH=full`로 고른다).

업스트림 LangGraph도 토론 라운드는 고정 횟수 루프였을 뿐(기본 Bull/Bear 2턴, Risk 3턴) 동적
라우팅의 이점이 없었다 — 그래프 엔진 없이 그냥 순서대로 부른다. `TradingAgentsRunner.run()`이
돌려주던 것과 같은 키 모양의 dict를 만들어, 그 위(citation 재요청·구조화 계약)는 그대로 둔다.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable

from investment_agent.trading.decision.agents import analysts, committee, debate, risk_debate, trader
from investment_agent.trading.decision.agents.graph_state import AnalystReports, InvestDebateState, RiskDebateState
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
    reports = _analyst_reports(
        client, ticker=ticker, curr_date=curr_date, fetch_market_evidence=fetch_market_evidence,
        fetch_fundamentals_evidence=fetch_fundamentals_evidence, fetch_news_evidence=fetch_news_evidence,
        fetch_sentiment_evidence=fetch_sentiment_evidence, fetch_macro_evidence=fetch_macro_evidence,
        macro_report_cache=macro_report_cache,
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
    return _result(reports, debate_state, trader_plan, risk_state, final_trade_decision)


def run_compact_graph(
    client: LLMClient,
    *,
    ticker: str,
    curr_date: str,
    fetch_market_evidence: Callable[[], str],
    fetch_fundamentals_evidence: Callable[[], str],
    fetch_news_evidence: Callable[[], str],
    fetch_sentiment_evidence: Callable[[], str],
    fetch_macro_evidence: Callable[[], str],
    macro_report_cache: dict[str, str] | None = None,
) -> dict[str, Any]:
    """분석가 리포트 뒤를 투자위원회 호출 한 번으로 끝낸다. 결과 키 모양은 전체 그래프와 같다."""
    reports = _analyst_reports(
        client, ticker=ticker, curr_date=curr_date, fetch_market_evidence=fetch_market_evidence,
        fetch_fundamentals_evidence=fetch_fundamentals_evidence, fetch_news_evidence=fetch_news_evidence,
        fetch_sentiment_evidence=fetch_sentiment_evidence, fetch_macro_evidence=fetch_macro_evidence,
        macro_report_cache=macro_report_cache,
    )
    verdict = committee.run_investment_committee(client, reports=reports)
    conclusion = f"{verdict['stance']}: {verdict['decision']}"
    debate_state = InvestDebateState(
        bull_history=f"Bull: {verdict['bull_case']}", bear_history=f"Bear: {verdict['bear_case']}",
        history="\n".join((f"Bull: {verdict['bull_case']}", f"Bear: {verdict['bear_case']}")), last_speaker="Judge",
        judge_decision=conclusion, count=2,
    )
    risk_state = RiskDebateState(latest_speaker="Judge", judge_decision=conclusion)
    return _result(reports, debate_state, "", risk_state, verdict["decision"])


def _analyst_reports(
    client: LLMClient,
    *,
    ticker: str,
    curr_date: str,
    fetch_market_evidence: Callable[[], str],
    fetch_fundamentals_evidence: Callable[[], str],
    fetch_news_evidence: Callable[[], str],
    fetch_sentiment_evidence: Callable[[], str],
    fetch_macro_evidence: Callable[[], str],
    macro_report_cache: dict[str, str] | None,
) -> AnalystReports:
    return AnalystReports(
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


def _result(reports: AnalystReports, debate_state: InvestDebateState, trader_plan: str,
            risk_state: RiskDebateState, final_trade_decision: str) -> dict[str, Any]:
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
