"""ml_rl_lab 대시보드 페이지 단위 테스트."""
from __future__ import annotations

import unittest
from investment_agent.dashboard.app_pages.ml_rl_lab import (
    _load_real_active_policy,
    render_dsr_gauge,
)


class MlRlLabDashboardTests(unittest.TestCase):
    def test_load_real_active_policy(self) -> None:
        policy = _load_real_active_policy()
        if policy is not None:
            self.assertIn("score", policy)
            self.assertIn("sharpe_ratio", policy["score"])
            self.assertIn("dsr_probability", policy["score"])
            self.assertNotIn("dsr_pvalue", policy["score"])

    def test_a_corrupt_policy_file_is_not_reported_as_no_champion(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest import mock
        from investment_agent.dashboard.app_pages import ml_rl_lab

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "active_policy.json"
            with mock.patch.object(ml_rl_lab, "ACTIVE_POLICY_PATH", path):
                self.assertIsNone(_load_real_active_policy(), "파일이 없으면 아직 챔피언이 없는 것")
                path.write_text("{not json", encoding="utf-8")
                with self.assertRaises(ml_rl_lab.ActivePolicyUnreadable):
                    _load_real_active_policy()
                path.write_text("[1, 2]", encoding="utf-8")
                with self.assertRaises(ml_rl_lab.ActivePolicyUnreadable):
                    _load_real_active_policy()
                path.write_text('{"score": {"dsr_probability": 0.5}}', encoding="utf-8")
                self.assertEqual(0.5, _load_real_active_policy()["score"]["dsr_probability"])

    def test_plotly_chart_builders(self) -> None:
        fig_dsr = render_dsr_gauge(0.96)
        self.assertIsNotNone(fig_dsr)
        self.assertEqual(len(fig_dsr.data), 1)


if __name__ == "__main__":
    unittest.main()
