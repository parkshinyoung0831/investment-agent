"""로컬 TradingAgents 그래프의 분석가 리포트·토론 상태 스키마.

토론 상태 필드명은 대시보드가 실제로 읽는 이름(aggressive/conservative/neutral)과
일치시킨다 — 업스트림 위탁 시절에는 이 이름이 어긋나 대시보드가 Risk 토론을 못 보여줬다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AnalystReports:
    market_report: str = ""
    sentiment_report: str = ""
    news_report: str = ""
    fundamentals_report: str = ""
    macro_report: str = ""


@dataclass
class InvestDebateState:
    bull_history: str = ""
    bear_history: str = ""
    history: str = ""
    current_response: str = ""
    last_speaker: str = ""
    judge_decision: str = ""
    count: int = 0


@dataclass
class RiskDebateState:
    aggressive_history: str = ""
    conservative_history: str = ""
    neutral_history: str = ""
    history: str = ""
    latest_speaker: str = ""
    current_aggressive_response: str = ""
    current_conservative_response: str = ""
    current_neutral_response: str = ""
    judge_decision: str = ""
    count: int = 0


_RISK_ORDER = ("aggressive", "conservative", "neutral")


def debate_next_speaker(state: InvestDebateState, *, max_rounds: int = 1) -> str | None:
    """다음 Bull/Bear 발언자. 라운드를 다 썼으면 None(Research Manager로 넘어간다)."""
    if state.count >= 2 * max_rounds:
        return None
    return "bear" if state.last_speaker == "bull" else "bull"


def risk_next_speaker(state: RiskDebateState, *, max_rounds: int = 1) -> str | None:
    """다음 Risk 토론 발언자(aggressive→conservative→neutral 순환). 라운드를 다 썼으면 None(Portfolio Manager로)."""
    if state.count >= 3 * max_rounds:
        return None
    if not state.latest_speaker:
        return _RISK_ORDER[0]
    index = _RISK_ORDER.index(state.latest_speaker)
    return _RISK_ORDER[(index + 1) % len(_RISK_ORDER)]
