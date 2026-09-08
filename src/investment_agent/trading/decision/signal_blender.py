"""LLM 정성 분석 신호와 강화학습(RL) 정량 정책 신호의 동적 앙상블 블렌더.

TradingAgents(LLM)의 펀더멘털·뉴스·거시 기대수익률 신호와,
지속 학습된 RL 정책(PPO)의 최적 목표 비중 신호를 결합하여
포트폴리오 최적화기(CVXPY)에 입력할 최종 앙상블 기대수익률 신호를 도출한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from investment_agent.platform.serialization import finite_float, normalize_ticker


@dataclass(frozen=True)
class BlendedSignal:
    """LLM과 RL이 결합된 앙상블 신호."""

    symbol: str
    expected_return: float
    confidence: float
    risk_score: float
    llm_weight: float
    rl_weight: float
    metadata: dict[str, Any]


class SignalBlender:
    """LLM 신호와 RL 정책의 동적 블렌더."""

    def __init__(
        self,
        base_rl_weight: float = 0.30,
        max_rl_weight: float = 0.50,
        min_rl_weight: float = 0.0,
    ) -> None:
        self.base_rl_weight = max(0.0, min(1.0, float(base_rl_weight)))
        self.max_rl_weight = max(self.base_rl_weight, min(1.0, float(max_rl_weight)))
        self.min_rl_weight = max(0.0, min(self.base_rl_weight, float(min_rl_weight)))

    def calculate_rl_weight(self, rl_dsr_probability: float | None = None) -> float:
        """RL 모델의 DSR 확률에 따라 RL 신호 반영 비중을 동적으로 결정한다."""
        if rl_dsr_probability is None or rl_dsr_probability < 0.50:
            return self.min_rl_weight
        # 0.5~1.0 확률 구간을 min_rl_weight~max_rl_weight로 스케일링한다.
        ratio = (rl_dsr_probability - 0.50) / 0.50
        weight = self.min_rl_weight + ratio * (self.max_rl_weight - self.min_rl_weight)
        return round(float(weight), 4)

    def blend(
        self,
        *,
        llm_expected_returns: Mapping[str, float],
        llm_confidences: Mapping[str, float] | None = None,
        llm_risk_scores: Mapping[str, float] | None = None,
        rl_target_weights: Mapping[str, float] | None = None,
        rl_dsr_probability: float | None = None,
        scaling_factor: float = 0.20,
    ) -> dict[str, BlendedSignal]:
        """종목별 LLM 신호와 RL 최적 비중을 결합하여 BlendedSignal 매핑을 반환한다."""
        rl_weight = self.calculate_rl_weight(rl_dsr_probability)
        llm_weight = round(1.0 - rl_weight, 4)

        conf_map = llm_confidences or {}
        risk_map = llm_risk_scores or {}
        rl_weights = rl_target_weights or {}

        # RL 타겟 비중의 평균 계산 (초과 비중을 기대수익률 신호로 전환)
        valid_rl_items = {
            normalize_ticker(k): finite_float(v) or 0.0
            for k, v in rl_weights.items()
            if normalize_ticker(k) != "CASH"
        }
        avg_rl_w = sum(valid_rl_items.values()) / max(1, len(valid_rl_items)) if valid_rl_items else 0.0

        blended: dict[str, BlendedSignal] = {}

        for raw_sym, raw_ret in llm_expected_returns.items():
            sym = normalize_ticker(raw_sym)
            if sym == "CASH":
                continue
            r_llm = finite_float(raw_ret) or 0.0
            c_llm = finite_float(conf_map.get(raw_sym)) or 0.50
            risk = finite_float(risk_map.get(raw_sym)) or 0.50

            # RL 정책 비중으로부터 유도된 상대 기대수익률
            if sym in valid_rl_items:
                # 평균 대비 초과 비중 * 스케일링 팩터 (예: 비중 +5% 초과 -> 기대수익률 +1.0% 상향)
                r_rl = (valid_rl_items[sym] - avg_rl_w) * scaling_factor
                c_rl = max(0.5, float(rl_dsr_probability or 0.5))
            else:
                r_rl = r_llm  # RL 비중이 없으면 LLM과 동일하게 처리
                c_rl = c_llm

            final_ret = round(llm_weight * r_llm + rl_weight * r_rl, 6)
            final_conf = round(llm_weight * c_llm + rl_weight * c_rl, 4)

            blended[sym] = BlendedSignal(
                symbol=sym,
                expected_return=final_ret,
                confidence=final_conf,
                risk_score=round(risk, 4),
                llm_weight=llm_weight,
                rl_weight=rl_weight,
                metadata={
                    "r_llm": r_llm,
                    "r_rl": round(r_rl, 6),
                    "c_llm": c_llm,
                    "c_rl": round(c_rl, 4),
                },
            )

        return blended


__all__ = [
    "BlendedSignal",
    "SignalBlender",
]
