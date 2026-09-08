"""재학습 진입점의 종료 코드가 "무엇이 잘못됐나"만 말하게 한다.

실측 2026-09-04: `continuous_learning` 잡이 매일 `failed`로 기록됐다. 원인은 둘이고
둘 다 정상 상태를 실패로 부른 것이다.

1. 승격하지 않는 것이 정상 결과인데 `return 0 if is_promoted else 1`이었다.
   챌린저가 챔피언을 못 이기는 날이 대부분이므로, 이대로면 게이트가 제대로 거를수록
   실패 보고가 늘어난다.
2. `rl_training_labels`는 forward 구간(5거래일)이 끝나야 채워진다. 그 전에는 원장이
   비어 RLSafetyError가 났는데, 이건 "데이터가 틀렸다"가 아니라 "아직 안 익었다"다.

둘을 실패로 부르면 `#시스템-로그`가 무해한 오류로 덮여 진짜 오류가 묻힌다.
"""
from __future__ import annotations

import unittest
from unittest import mock

from investment_agent.research.commands import continuous_retrain
from investment_agent.research.rl.contracts import RLDataNotReadyError, RLSafetyError
from investment_agent.research.rl.continuous_learner import (
    PolicyEvaluationScore,
    PromotionDecision,
)

SCORE = PolicyEvaluationScore(
    sharpe_ratio=0.4,
    total_reward=0.1,
    excess_return=0.01,
    max_drawdown=-0.05,
    turnover=0.2,
    dsr_probability=0.95,
    is_statistically_significant=True,
    periods_evaluated=40,
)


def _decision(*, is_promoted: bool, reason: str) -> PromotionDecision:
    return PromotionDecision(
        is_promoted=is_promoted,
        challenger_score=SCORE,
        champion_score=None,
        improvement_sharpe=0.0,
        reason=reason,
    )


class ExitCodeTest(unittest.TestCase):
    def _run_with(self, outcome):
        with mock.patch.object(
            continuous_retrain, "run_continuous_retrain", side_effect=outcome
        ):
            return continuous_retrain.main([])

    def test_a_completed_run_that_does_not_promote_is_not_a_failure(self):
        decision = _decision(is_promoted=False, reason="challenger did not beat champion")
        self.assertEqual(self._run_with(lambda **kwargs: decision), 0)

    def test_a_promotion_also_exits_zero(self):
        decision = _decision(is_promoted=True, reason="promoted")
        self.assertEqual(self._run_with(lambda **kwargs: decision), 0)

    def test_an_unripe_ledger_is_a_wait_not_a_failure(self):
        def not_ready(**kwargs):
            raise RLDataNotReadyError("no forward label is confirmed before the cutoff")

        self.assertEqual(self._run_with(not_ready), 0)

    def test_a_real_safety_violation_still_fails_loudly(self):
        def leaked(**kwargs):
            raise RLSafetyError("feature spec contains future-label fields: future_return")

        with self.assertRaises(RLSafetyError):
            self._run_with(leaked)


class NotReadyIsASafetyErrorTest(unittest.TestCase):
    """기존 호출부가 RLSafetyError로 잡고 있으므로 하위 타입이어야 한다."""

    def test_it_is_a_subclass(self):
        self.assertTrue(issubclass(RLDataNotReadyError, RLSafetyError))


class EmptyLedgerRaisesNotReadyTest(unittest.TestCase):
    """원장 세 갈래가 비었을 때만 '아직'이라고 부른다."""

    def _repository(self, *, features, labels, membership):
        return mock.Mock(
            rl_feature_snapshot_rows=mock.Mock(return_value=features),
            rl_training_label_rows=mock.Mock(return_value=labels),
            rl_historical_membership_rows=mock.Mock(return_value=membership),
        )

    def _load(self, repository):
        from investment_agent.research.rl.features import load_training_set

        return load_training_set(
            repository,
            symbols=("AAPL",),
            start_as_of="2026-01-01T00:00:00+00:00",
            end_as_of="2026-08-01T00:00:00+00:00",
            label_cutoff_at="2026-09-01T00:00:00+00:00",
            spec=continuous_retrain.default_spec(),
        )

    def test_missing_features_is_not_ready(self):
        with self.assertRaises(RLDataNotReadyError):
            self._load(self._repository(features=[], labels=[], membership=[]))

    def test_missing_labels_is_not_ready(self):
        repository = self._repository(features=[{"as_of_at": "x"}], labels=[], membership=[])
        with self.assertRaises(RLDataNotReadyError):
            self._load(repository)

    def test_missing_membership_is_not_ready(self):
        repository = self._repository(
            features=[{"as_of_at": "x"}], labels=[{"as_of_at": "x"}], membership=[],
        )
        with self.assertRaises(RLDataNotReadyError):
            self._load(repository)


if __name__ == "__main__":
    unittest.main()
