"""융합 차트가 실제 규칙과 어긋나지 않는지.

실측 2026-09-04: 이 화면은 "실제 SignalBlender 엔진을 호출"한다고 적어 놓고 종목별
입력을 상수로 지어내 넣었고, 실제 판단 경로가 쓰지 않는 `rl_target_weights`까지
넘겨 화면만 다른 규칙을 보여줬다. 지금은 판단 경로와 같은 인자로 부르고, 입력이
예시임을 이름과 캡션에 밝힌다.
"""
from __future__ import annotations

import unittest

from investment_agent.dashboard.app_pages import ml_rl_lab
from investment_agent.trading.decision.signal_blender import SignalBlender


class BlendingRuleChartTest(unittest.TestCase):
    def test_chart_shows_the_example_input_and_the_fused_result(self) -> None:
        figure = ml_rl_lab.render_blending_rule_chart({"score": {"dsr_probability": 0.9}})
        names = [trace.name for trace in figure.data]
        self.assertEqual(["예시 LLM 기대수익률 (%)", "융합 결과 기대수익률 (%)"], names)
        # 입력이 예시임을 이름이 말한다 — 원장 값처럼 보이면 안 된다.
        self.assertIn("예시", names[0])

    def test_fused_values_match_the_engine_called_the_way_production_calls_it(self) -> None:
        policy = {"score": {"dsr_probability": 0.9}}
        figure = ml_rl_lab.render_blending_rule_chart(policy)
        blender = SignalBlender(base_rl_weight=0.40, max_rl_weight=0.50, min_rl_weight=0.10)
        expected = blender.blend(
            llm_expected_returns=ml_rl_lab._BLEND_EXAMPLE_RETURNS,
            llm_confidences=ml_rl_lab._BLEND_EXAMPLE_CONFIDENCES,
            rl_dsr_probability=0.9,
        )
        tickers = list(ml_rl_lab._BLEND_EXAMPLE_RETURNS)
        self.assertEqual(
            [round(expected[t].expected_return * 100, 6) for t in tickers],
            [round(value, 6) for value in figure.data[1].y],
        )

    def test_weights_move_with_dsr_and_sum_to_one(self) -> None:
        low = ml_rl_lab.blending_weights({"score": {"dsr_probability": 0.0}})
        high = ml_rl_lab.blending_weights({"score": {"dsr_probability": 0.99}})
        assert low is not None and high is not None
        self.assertAlmostEqual(1.0, sum(low))
        self.assertAlmostEqual(1.0, sum(high))
        # DSR이 높을수록 RL 쪽 가중치가 커진다.
        self.assertGreater(high[1], low[1])

    def test_no_promoted_policy_yields_no_weights(self) -> None:
        """승격된 정책이 없는데 기본값으로 'RL 가중치 46%'를 만들어 내지 않는다.

        실측 2026-09-04: `artifacts/trading/rl_policies/`에 active_policy.json이 없고
        retired 폴더만 있다. 그런데 화면은 DSR 기본값 0.95로 가중치를 그려 강화학습이
        배분에 관여하는 것처럼 보였다.
        """
        self.assertIsNone(ml_rl_lab.blending_weights(None))
        self.assertIsNone(ml_rl_lab.blending_weights({}))
        self.assertIsNone(ml_rl_lab.blending_weights({"score": {}}))
