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


if __name__ == "__main__":
    unittest.main()
