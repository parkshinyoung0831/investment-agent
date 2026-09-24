"""분석가 리포트를 한 번에 읽고 강세·약세 논거와 최종 판단을 함께 내는 투자위원회 호출.

판단 기록에 남는 것은 방향(stance)과 그 근거다. 한 호출이 양쪽 논거를 먼저 적고 결론을 내게 하면 역할별
토론을 여러 번 부르지 않고도 같은 정보를 남긴다 — 종목당 LLM 호출이 분석가 5 + 위원회 1 + 구조화 1이다.
"""
from __future__ import annotations

from typing import Any

from investment_agent.forecasting import SIGNAL_HORIZON_DAYS
from investment_agent.platform.serialization import canonical_json
from investment_agent.trading.decision.agents.graph_state import AnalystReports, shared_context
from investment_agent.trading.decision.llm.client import LLMClient

_COMMITTEE_SCHEMA: dict[str, Any] = {
    "bull_case": "string: the strongest case for outperforming the benchmark, in Korean prose",
    "bear_case": "string: the strongest case for underperforming the benchmark, in Korean prose",
    "stance": "bullish|neutral|bearish",
    "decision": "string: which side wins and why, in Korean prose",
}


def run_investment_committee(client: LLMClient, *, reports: AnalystReports) -> dict[str, str]:
    """강세 논거 → 약세 논거 → 결론 순서로 한 번에 쓴다. 매수·매도·비중은 정하지 않는다."""
    system = (
        f"너는 투자위원회 의장이다. 5개 분석가 리포트를 근거로 이 종목이 앞으로 {SIGNAL_HORIZON_DAYS}거래일 동안 "
        "벤치마크 대비 초과수익을 낼지 판단하라. 먼저 가장 강한 강세 논거와 가장 강한 약세 논거를 각각 적고, "
        "그다음 어느 쪽이 이기는지와 이유를 적는다. 한쪽 논거가 약하면 약하다고 쓴다. 옵션 전략·손절가·비중·"
        f"몇 개월 단위 전망은 언급하지 않는다 — 판단 지평은 {SIGNAL_HORIZON_DAYS}거래일 초과수익 하나뿐이고, "
        "매수·매도·비중은 포트폴리오 엔진과 리스크 게이트의 몫이다."
    )
    result = client.complete_json(
        context=shared_context(reports),
        system=system, user=canonical_json({"task": "investment_committee"}),
        output_schema=_COMMITTEE_SCHEMA, task_name="tradingagents_investment_committee",
    )
    return {key: str(result[key]) for key in _COMMITTEE_SCHEMA}


__all__ = ["run_investment_committee"]
