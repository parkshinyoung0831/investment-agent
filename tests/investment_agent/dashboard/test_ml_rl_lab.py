"""ml_rl_lab 대시보드 페이지 단위 테스트."""
from __future__ import annotations

import unittest
from investment_agent.dashboard.app_pages.ml_rl_lab import (
    _load_real_active_policy,
    render_dsr_gauge,
    render_blending_rule_chart,
)


class MlRlLabDashboardTests(unittest.TestCase):
    def test_load_real_active_policy(self) -> None:
        policy = _load_real_active_policy()
        if policy is not None:
            self.assertIn("score", policy)
            self.assertIn("sharpe_ratio", policy["score"])
            self.assertIn("dsr_probability", policy["score"])
            self.assertNotIn("dsr_pvalue", policy["score"])

    def test_plotly_chart_builders(self) -> None:
        fig_dsr = render_dsr_gauge(0.96)
        self.assertIsNotNone(fig_dsr)
        self.assertEqual(len(fig_dsr.data), 1)

        policy = _load_real_active_policy()
        fig_blend = render_blending_rule_chart(policy)
        self.assertIsNotNone(fig_blend)
        # 예시 입력과 융합 결과 둘. 규칙 자체는 실제 엔진이 계산한다.
        self.assertEqual(len(fig_blend.data), 2)


if __name__ == "__main__":
    unittest.main()
