"""자율 지속 재학습 및 챔피언-챌린저(Champion-Challenger) 정책 승격기.

누적된 실매매 경험 데이터셋을 바탕으로 강화학습 정책을 재학습하고,
직전 OOS 검증 구간에서 기존 챔피언 모델 대비 샤프비율 개선 및 DSR 과적합 검정을
통과한 신규 챌린저 모델만을 프로덕션 정책으로 안전하게 자동 승격한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from investment_agent.research.rl.contracts import RewardConfig
from investment_agent.research.rl.environment import FeatureDataset, WeightEnvironmentCore
from investment_agent.research.evaluation.deflated_sharpe import DeflatedSharpeRatio


@dataclass(frozen=True)
class PolicyEvaluationScore:
    """정책 모델의 OOS 검증 성과 지표."""

    sharpe_ratio: float
    total_reward: float
    excess_return: float
    max_drawdown: float
    turnover: float
    dsr_probability: float
    is_statistically_significant: bool
    # 몇 개 구간에서 나온 점수인지 남긴다. 구간 수를 모르면 샤프비율을 읽을 수 없다.
    periods_evaluated: int = 0


@dataclass(frozen=True)
class PromotionDecision:
    """챔피언-챌린저 승격 판정 결과."""

    is_promoted: bool
    challenger_score: PolicyEvaluationScore
    champion_score: PolicyEvaluationScore | None
    improvement_sharpe: float
    reason: str


class ContinuousLearner:
    """지속적 자율 재학습 및 검증 게이트."""

    def __init__(
        self,
        reward_config: RewardConfig | None = None,
        min_sharpe_improvement: float = 0.05,
        min_dsr_probability: float = 0.90,
    ) -> None:
        self.reward_config = reward_config or RewardConfig()
        self.min_sharpe_improvement = float(min_sharpe_improvement)
        self.min_dsr_probability = float(min_dsr_probability)

    def evaluate_model(
        self,
        model: Any,
        dataset: FeatureDataset,
        num_trials: int = 10,
    ) -> PolicyEvaluationScore:
        """주어진 모델을 FeatureDataset 환경에서 롤아웃 시뮬레이션하여 성과 및 DSR을 산출한다."""
        core = WeightEnvironmentCore(dataset, self.reward_config)
        returns: list[float] = []
        rewards: list[float] = []
        benchmark_returns: list[float] = []
        drawdown = 0.0
        turnover = 0.0

        while core.index < len(dataset.as_of_values):
            obs = core.observation()
            # 모델의 행동 예측 (predict 또는 predict_weights)
            if hasattr(model, "predict"):
                action, _ = model.predict(obs, deterministic=True)
            elif callable(model):
                action = model(obs)
            else:
                # 균등 비중 fallback. action 축은 종목 수 + CASH 한 칸이다.
                n_actions = len(dataset.symbols) + 1
                action = np.ones(n_actions, dtype=np.float32) / n_actions

            _, reward, _, info = core.step(action)
            rewards.append(float(reward))
            returns.append(float(info.get("net_return", info.get("portfolio_return", 0.0))))
            benchmark_returns.append(float(info.get("benchmark_return", 0.0)))
            drawdown = max(drawdown, float(info.get("drawdown", 0.0)))
            turnover += float(info.get("turnover", 0.0))

        # DSR 과적합 검정 (연율화 샤프비율)
        dsr_res = DeflatedSharpeRatio.compute(returns, num_trials=num_trials, annualize=True)

        tot_excess = sum(returns) - sum(benchmark_returns)

        return PolicyEvaluationScore(
            sharpe_ratio=round(float(dsr_res.observed_sr), 4),
            total_reward=round(sum(rewards), 4),
            excess_return=round(tot_excess, 4),
            max_drawdown=round(float(drawdown), 4),
            turnover=round(float(turnover), 4),
            dsr_probability=dsr_res.dsr_probability,
            is_statistically_significant=(
                dsr_res.dsr_probability >= self.min_dsr_probability
            ),
            periods_evaluated=len(returns),
        )

    def judge_promotion(
        self,
        challenger_score: PolicyEvaluationScore,
        champion_score: PolicyEvaluationScore | None,
    ) -> PromotionDecision:
        """신규 챌린저 모델과 기존 챔피언 모델의 성과를 대조하여 승격 여부를 결정한다."""
        # 샤프비율은 변동성 대비 성과라 벤치마크를 못 이겨도 높을 수 있다. 초과수익을
        # 따로 요구하지 않으면 "덜 흔들리며 더 못 버는" 정책이 승격된다.
        passes_excess = challenger_score.excess_return > 0

        if champion_score is None:
            # 챔피언이 아직 없으면 양수 샤프비율·양수 초과수익·DSR 통과 시 최초 승격
            is_promoted = (
                challenger_score.sharpe_ratio > 0
                and passes_excess
                and challenger_score.dsr_probability >= self.min_dsr_probability
            )
            if is_promoted:
                reason = "최초 챔피언 정책 승격"
            else:
                fail_first = []
                if challenger_score.sharpe_ratio <= 0:
                    fail_first.append("샤프비율 <= 0")
                if not passes_excess:
                    fail_first.append(
                        f"벤치마크 대비 초과수익 부족 ({challenger_score.excess_return:+.4f} <= 0)"
                    )
                if challenger_score.dsr_probability < self.min_dsr_probability:
                    fail_first.append(
                        f"DSR 불합격 ({challenger_score.dsr_probability:.2f})"
                    )
                reason = "최초 후보 기준 미달: " + ", ".join(fail_first)
            return PromotionDecision(
                is_promoted=is_promoted,
                challenger_score=challenger_score,
                champion_score=None,
                improvement_sharpe=challenger_score.sharpe_ratio,
                reason=reason,
            )

        diff = challenger_score.sharpe_ratio - champion_score.sharpe_ratio
        passes_improvement = diff >= self.min_sharpe_improvement
        passes_dsr = challenger_score.dsr_probability >= self.min_dsr_probability

        if passes_improvement and passes_dsr and passes_excess:
            return PromotionDecision(
                is_promoted=True,
                challenger_score=challenger_score,
                champion_score=champion_score,
                improvement_sharpe=round(diff, 4),
                reason=f"챔피언 대비 샤프비율 향상 (+{diff:.4f} >= {self.min_sharpe_improvement}) 및 DSR 통과 ({challenger_score.dsr_probability:.2f})",
            )

        fail_reasons = []
        if not passes_improvement:
            fail_reasons.append(f"샤프비율 향상 부족 (+{diff:.4f} < {self.min_sharpe_improvement})")
        if not passes_dsr:
            fail_reasons.append(
                f"DSR 통계 유의성 부족 ({challenger_score.dsr_probability:.2f} < {self.min_dsr_probability})"
            )
        if not passes_excess:
            fail_reasons.append(
                f"벤치마크 대비 초과수익 부족 ({challenger_score.excess_return:+.4f} <= 0)"
            )

        return PromotionDecision(
            is_promoted=False,
            challenger_score=challenger_score,
            champion_score=champion_score,
            improvement_sharpe=round(diff, 4),
            reason="승격 반려: " + ", ".join(fail_reasons),
        )


__all__ = [
    "ContinuousLearner",
    "PolicyEvaluationScore",
    "PromotionDecision",
]
