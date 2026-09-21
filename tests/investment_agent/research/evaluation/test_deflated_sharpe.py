"""DeflatedSharpeRatio 단위 테스트."""
from __future__ import annotations

import unittest

from investment_agent.research.evaluation.deflated_sharpe import DeflatedSharpeRatio


class DeflatedSharpeTests(unittest.TestCase):
    def test_genuine_alpha_passes_dsr(self) -> None:
        # 지속적으로 안정적인 플러스 수익률 (압도적인 진짜 알파)
        returns = [0.01, 0.012, 0.009, 0.015, 0.011, 0.013, 0.008, 0.014] * 10
        res = DeflatedSharpeRatio.compute(returns, num_trials=5)
        self.assertTrue(res.is_statistically_significant)
        self.assertGreater(res.dsr_probability, 0.95)
        self.assertGreater(res.observed_sr, res.expected_max_sr)

    def test_overfitted_random_returns_fail_dsr(self) -> None:
        # 방향성 없이 등락하는 수익률이므로 다중 시도 보정을 통과하면 안 된다.
        returns = [-0.03, 0.03, -0.02, 0.02, -0.01, 0.01, -0.04, 0.04] * 5
        res = DeflatedSharpeRatio.compute(returns, num_trials=100)
        # 100번 시도 감안 시 DSR 확률이 0.95에 미달하여 과적합으로 판정되어야 함
        self.assertFalse(res.is_statistically_significant)
        self.assertLess(res.dsr_probability, 0.95)

    @staticmethod
    def _period_returns(count: int, mean: float = 0.02, spread: float = 0.05) -> list[float]:
        """평균 mean, 표준편차가 spread 근처인 결정적 수열."""
        pattern = [spread, -spread, spread * 0.5, -spread * 0.5, spread * 1.5, -spread * 1.5]
        return [mean + pattern[index % len(pattern)] for index in range(count)]

    def test_annualizing_only_changes_the_display_not_the_probability(self) -> None:
        """연환산 샤프를 표준오차 식에 넣으면 표준오차가 √주기수배 작아져 확률이 0/1로 쏠린다(RS-5)."""
        returns = self._period_returns(60, mean=0.002, spread=0.02)
        annual = DeflatedSharpeRatio.compute(returns, num_trials=10, annualize=True)
        period = DeflatedSharpeRatio.compute(returns, num_trials=10, annualize=False)
        self.assertEqual(annual.dsr_probability, period.dsr_probability)
        self.assertAlmostEqual(annual.observed_sr, period.observed_sr * 252 ** 0.5, places=2)

    def test_a_strong_period_sharpe_is_not_rejected_by_a_fixed_constant(self) -> None:
        """기간 샤프가 좋은 정책이 상수 1.11 문턱에 막혀 확률 0이 되던 문제."""
        returns = self._period_returns(30, mean=0.03, spread=0.05)
        result = DeflatedSharpeRatio.compute(returns, num_trials=10, annualize=False)
        self.assertGreater(result.observed_sr, 0.4)
        self.assertLess(result.expected_max_sr, 0.35)
        self.assertGreater(result.dsr_probability, 0.9)

    def test_the_expected_maximum_shrinks_as_the_sample_grows(self) -> None:
        short = DeflatedSharpeRatio.compute(self._period_returns(30), num_trials=10, annualize=False)
        long = DeflatedSharpeRatio.compute(self._period_returns(300), num_trials=10, annualize=False)
        self.assertGreater(short.expected_max_sr, long.expected_max_sr)

    def test_an_explicit_trial_variance_is_respected(self) -> None:
        returns = self._period_returns(60)
        loose = DeflatedSharpeRatio.compute(returns, num_trials=10, variance_trials=0.5, annualize=False)
        tight = DeflatedSharpeRatio.compute(returns, num_trials=10, variance_trials=0.001, annualize=False)
        self.assertGreater(loose.expected_max_sr, tight.expected_max_sr)


if __name__ == "__main__":
    unittest.main()
