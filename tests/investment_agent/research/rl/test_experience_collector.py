"""ExperienceCollector 단위 테스트."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from investment_agent.research.rl.contracts import RewardConfig
from investment_agent.research.rl.experience_collector import (
    ExperienceCollector,
    ExperienceRecord,
)


class ExperienceCollectorTests(unittest.TestCase):
    def test_calculate_reward_positive_alpha(self) -> None:
        cfg = RewardConfig(
            return_weight=1.0,
            alpha_weight=0.5,
            turnover_penalty=0.05,
            transaction_cost_rate=0.001,
        )
        collector = ExperienceCollector(cfg)
        # 50:50 비중, 각 2%, 4% 수익 -> 포트폴리오 수익 3% (0.03)
        # 벤치마크 1% (0.01) -> 알파 2% (0.02)
        # 턴오버 10% (0.10), 슬리피지 5 bps (0.0005)
        reward = collector.calculate_reward(
            action_weights=[0.5, 0.5],
            realized_returns=[0.02, 0.04],
            benchmark_return=0.01,
            turnover=0.10,
            slippage_cost=0.0005,
        )
        # 기대 보상 = 1.0 * 0.03 + 0.5 * 0.02 - 0.05 * 0.10 - (0.001 * 0.10 + 0.0005)
        # = 0.03 + 0.01 - 0.005 - 0.0006 = 0.0344
        self.assertAlmostEqual(reward, 0.0344, places=4)

    def test_create_record_and_export_dataset(self) -> None:
        collector = ExperienceCollector()
        rec1 = collector.create_record(
            as_of_at="2026-09-01T20:00:00+00:00",
            symbols=["AAPL", "MSFT"],
            features_matrix=[[1.0, 2.0], [3.0, 4.0]],
            action_weights=[0.6, 0.4],
            realized_returns=[0.01, -0.005],
            benchmark_return=0.002,
        )
        rec2 = collector.create_record(
            as_of_at="2026-09-02T20:00:00+00:00",
            symbols=["AAPL", "MSFT"],
            features_matrix=[[1.1, 2.1], [3.1, 4.1]],
            action_weights=[0.5, 0.5],
            realized_returns=[0.015, 0.02],
            benchmark_return=0.01,
        )

        dataset = collector.to_feature_dataset([rec1, rec2], feature_names=["f1", "f2"])
        self.assertEqual(dataset.symbols, ("AAPL", "MSFT"))
        self.assertEqual(dataset.feature_names, ("f1", "f2"))
        self.assertEqual(dataset.features.shape, (2, 2, 2))
        self.assertEqual(dataset.forward_returns.shape, (2, 2))
        self.assertEqual(len(dataset.as_of_values), 2)


if __name__ == "__main__":
    unittest.main()
