"""Risk 3자 토론(aggressive/conservative/neutral)과 Portfolio Manager(Risk Judge).

상태 필드명은 대시보드가 실제로 읽는 이름(`RiskDebateState`의 aggressive/conservative/neutral)
과 일치한다 — 업스트림 위탁 시절에는 risky_history/safe_history로 어긋나 대시보드가
Risk 토론을 못 보여줬다.
"""
from __future__ import annotations

from typing import Any

from investment_agent.platform.serialization import canonical_json
from investment_agent.forecasting import SIGNAL_HORIZON_DAYS
from investment_agent.trading.decision.agents.graph_state import (
    AnalystReports,
    RiskDebateState,
    risk_next_speaker,
    shared_context,
)
from investment_agent.trading.decision.llm.client import LLMClient

_ARGUMENT_SCHEMA: dict[str, Any] = {
    "argument": "string: one debate turn in Korean prose, no price target, no options/stop-loss/sizing",
}

_PORTFOLIO_DECISION_SCHEMA: dict[str, Any] = {
    "stance": "bullish|neutral|bearish",
    "decision": "string: the final risk-debate takeaway in Korean prose",
}

_ROLE_LABELS = {
    "aggressive": "공격적 리스크 분석가(Aggressive)",
    "conservative": "보수적 리스크 분석가(Conservative)",
    "neutral": "중립 리스크 분석가(Neutral)",
}
_ENTRY_LABELS = {"aggressive": "Aggressive", "conservative": "Conservative", "neutral": "Neutral"}
_TASK_NAMES = {
    "aggressive": "tradingagents_aggressive_debator",
    "conservative": "tradingagents_conservative_debator",
    "neutral": "tradingagents_neutral_debator",
}
_HISTORY_ATTR = {
    "aggressive": "aggressive_history",
    "conservative": "conservative_history",
    "neutral": "neutral_history",
}
_CURRENT_ATTR = {
    "aggressive": "current_aggressive_response",
    "conservative": "current_conservative_response",
    "neutral": "current_neutral_response",
}



def _risk_turn(
    client: LLMClient, *, speaker: str, reports: AnalystReports, trader_plan: str, state: RiskDebateState,
) -> str:
    system = (
        f"너는 {_ROLE_LABELS[speaker]}다. Trader의 계획과 5개 분석가 리포트, 지금까지의 리스크 "
        f"토론 내역을 근거로 앞으로 {SIGNAL_HORIZON_DAYS}거래일 동안의 하방·상방 위험을 논증하라. "
        "다른 두 분석가의 최근 주장에 구체적으로 반박한다. 옵션 전략·손절가·비중은 언급하지 "
        f"않는다 — 판단 지평은 {SIGNAL_HORIZON_DAYS}거래일 초과수익 하나뿐이다."
    )
    user = canonical_json({
        "trader_plan": trader_plan,
        "risk_debate_history": state.history,
    })
    result = client.complete_json(
        context=shared_context(reports),
        system=system, user=user, output_schema=_ARGUMENT_SCHEMA, task_name=_TASK_NAMES[speaker],
    )
    return str(result["argument"])


def run_risk_debate(
    client: LLMClient, *, reports: AnalystReports, trader_plan: str, max_rounds: int = 1,
) -> RiskDebateState:
    """Aggressive→Conservative→Neutral 순으로 번갈아 발언하며 RiskDebateState를 채운다."""
    state = RiskDebateState()
    speaker = risk_next_speaker(state, max_rounds=max_rounds)
    while speaker is not None:
        argument = _risk_turn(
            client, speaker=speaker, reports=reports, trader_plan=trader_plan, state=state,
        )
        entry = f"{_ENTRY_LABELS[speaker]}: {argument}"
        setattr(state, _HISTORY_ATTR[speaker], f"{getattr(state, _HISTORY_ATTR[speaker])}\n{entry}".strip())
        setattr(state, _CURRENT_ATTR[speaker], argument)
        state.history = f"{state.history}\n{entry}".strip()
        state.latest_speaker = speaker
        state.count += 1
        speaker = risk_next_speaker(state, max_rounds=max_rounds)
    return state


def run_portfolio_manager(
    client: LLMClient, *, reports: AnalystReports, trader_plan: str, state: RiskDebateState,
) -> tuple[RiskDebateState, str]:
    """Risk 3자 토론 전체를 근거로 최종 판단(final_trade_decision)을 정리한다(=Risk Judge)."""
    system = (
        f"너는 Portfolio Manager(Risk Judge)다. Trader 계획과 Risk 3자 토론 전체를 근거로 이 "
        f"종목의 앞으로 {SIGNAL_HORIZON_DAYS}거래일 방향(bullish/neutral/bearish)과 최종 판단을 "
        "정리하라. 매수·매도·비중은 정하지 않는다 — 그건 포트폴리오 엔진과 리스크 게이트의 몫이다."
    )
    user = canonical_json({
        "trader_plan": trader_plan,
        "risk_debate_history": state.history,
    })
    result = client.complete_json(
        context=shared_context(reports),
        system=system, user=user, output_schema=_PORTFOLIO_DECISION_SCHEMA,
        task_name="tradingagents_portfolio_manager",
    )
    state.judge_decision = f"{result['stance']}: {result['decision']}"
    state.latest_speaker = "Judge"
    return state, str(result["decision"])
