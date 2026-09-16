"""Bull/Bear 강세·약세 토론과 Research Manager의 방향 판단.

모든 토론은 20거래일 벤치마크 대비 초과수익 하나만 다룬다(`SIGNAL_HORIZON_DAYS`).
업스트림 프롬프트가 논하던 "3~12개월·옵션·손절·비중"은 그 계약과 어긋나 옮기지 않는다.
"""
from __future__ import annotations

from typing import Any

from investment_agent.platform.serialization import canonical_json
from investment_agent.trading.decision.constants import SIGNAL_HORIZON_DAYS
from investment_agent.trading.decision.llm.agents.graph_state import (
    AnalystReports,
    InvestDebateState,
    debate_next_speaker,
)
from investment_agent.trading.decision.llm.client import LLMClient

_ARGUMENT_SCHEMA: dict[str, Any] = {
    "argument": "string: one debate turn in Korean prose, no price target, no options/stop-loss/sizing",
}

_RESEARCH_PLAN_SCHEMA: dict[str, Any] = {
    "stance": "bullish|neutral|bearish",
    "plan": "string: the debate's takeaway in Korean prose",
}

_ROLE_LABELS = {"bull": "강세론자(Bull)", "bear": "약세론자(Bear)"}
_ENTRY_LABELS = {"bull": "Bull", "bear": "Bear"}
_TASK_NAMES = {"bull": "tradingagents_bull_researcher", "bear": "tradingagents_bear_researcher"}


def _reports_payload(reports: AnalystReports) -> dict[str, str]:
    return {
        "market_report": reports.market_report,
        "sentiment_report": reports.sentiment_report,
        "news_report": reports.news_report,
        "fundamentals_report": reports.fundamentals_report,
        "macro_report": reports.macro_report,
    }


def _debate_turn(
    client: LLMClient, *, speaker: str, reports: AnalystReports, state: InvestDebateState,
) -> str:
    system = (
        f"너는 {_ROLE_LABELS[speaker]}다. 5개 분석가 리포트와 지금까지의 토론 내역을 근거로 이 "
        f"종목이 앞으로 {SIGNAL_HORIZON_DAYS}거래일 동안 벤치마크 대비 어떻게 움직일지 논증하라. "
        "상대 마지막 주장에 구체적으로 반박한다. 옵션 전략·손절가·비중·몇 개월 단위 전망은 언급 "
        f"하지 않는다 — 판단 지평은 {SIGNAL_HORIZON_DAYS}거래일 초과수익 하나뿐이다."
    )
    opponent_last = state.bear_history if speaker == "bull" else state.bull_history
    user = canonical_json({
        "reports": _reports_payload(reports),
        "debate_history": state.history,
        "opponent_last_argument": opponent_last,
    })
    result = client.complete_json(
        system=system, user=user, output_schema=_ARGUMENT_SCHEMA, task_name=_TASK_NAMES[speaker],
    )
    return str(result["argument"])


def run_bull_bear_debate(
    client: LLMClient, *, reports: AnalystReports, max_rounds: int = 1,
) -> InvestDebateState:
    """Bull/Bear가 번갈아 발언하며 InvestDebateState를 채운다(기본 2턴 = max_rounds 1)."""
    state = InvestDebateState()
    speaker = debate_next_speaker(state, max_rounds=max_rounds)
    while speaker is not None:
        argument = _debate_turn(client, speaker=speaker, reports=reports, state=state)
        entry = f"{_ENTRY_LABELS[speaker]}: {argument}"
        if speaker == "bull":
            state.bull_history = f"{state.bull_history}\n{entry}".strip()
        else:
            state.bear_history = f"{state.bear_history}\n{entry}".strip()
        state.history = f"{state.history}\n{entry}".strip()
        state.current_response = argument
        state.last_speaker = speaker
        state.count += 1
        speaker = debate_next_speaker(state, max_rounds=max_rounds)
    return state


def run_research_manager(
    client: LLMClient, *, reports: AnalystReports, state: InvestDebateState,
) -> InvestDebateState:
    """Bull/Bear 토론 전체를 근거로 방향(stance)과 근거를 정리한다."""
    system = (
        f"너는 Research Manager다. Bull/Bear 토론 전체를 근거로 이 종목의 앞으로 "
        f"{SIGNAL_HORIZON_DAYS}거래일 방향(bullish/neutral/bearish)과 그 근거를 정리하라. "
        "매수·매도·비중은 정하지 않는다 — 그건 포트폴리오 엔진의 몫이다."
    )
    user = canonical_json({
        "reports": _reports_payload(reports),
        "debate_history": state.history,
    })
    result = client.complete_json(
        system=system, user=user, output_schema=_RESEARCH_PLAN_SCHEMA,
        task_name="tradingagents_research_manager",
    )
    state.judge_decision = f"{result['stance']}: {result['plan']}"
    return state
