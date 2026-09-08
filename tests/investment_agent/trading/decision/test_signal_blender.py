"""SignalBlender 단위 테스트."""
from __future__ import annotations

import unittest

from investment_agent.trading.decision.signal_blender import (
    BlendedSignal,
    SignalBlender,
)


class SignalBlenderTests(unittest.TestCase):
    def test_dynamic_rl_weight_scaling(self) -> None:
        blender = SignalBlender(base_rl_weight=0.20, max_rl_weight=0.50, min_rl_weight=0.10)

        # DSR 확률이 미달(<0.5)이면 최소 비중(0.10)
        self.assertEqual(blender.calculate_rl_weight(0.40), 0.10)
        # DSR 확률이 0.75면 중간 비중 (0.10 + 0.5 * 0.40 = 0.30)
        self.assertAlmostEqual(blender.calculate_rl_weight(0.75), 0.30)
        # DSR 확률이 1.0이면 최대 비중 (0.50)
        self.assertAlmostEqual(blender.calculate_rl_weight(1.0), 0.50)

    def test_blend_combines_signals(self) -> None:
        blender = SignalBlender(base_rl_weight=0.30, max_rl_weight=0.50, min_rl_weight=0.0)

        llm_returns = {"AAPL": 0.05, "MSFT": 0.02}
        llm_conf = {"AAPL": 0.80, "MSFT": 0.70}
        # RL은 MSFT에 더 높은 가중치를 배분한 상태 (평균 0.20 대비 초과 0.35)
        rl_weights = {"AAPL": 0.05, "MSFT": 0.35}

        # DSR 0.90 -> RL weight = 0.8 * 0.50 = 0.40 (LLM 0.60)
        signals = blender.blend(
            llm_expected_returns=llm_returns,
            llm_confidences=llm_conf,
            rl_target_weights=rl_weights,
            rl_dsr_probability=0.90,
            scaling_factor=0.20,
        )

        self.assertIn("AAPL", signals)
        self.assertIn("MSFT", signals)
        self.assertEqual(signals["AAPL"].llm_weight, 0.60)
        self.assertEqual(signals["AAPL"].rl_weight, 0.40)

        # MSFT는 RL의 긍정적 가중치가 반영되어 LLM 단독보다 기대수익률이 상향되어야 함
        self.assertGreater(signals["MSFT"].expected_return, 0.02)

    def test_without_rl_target_weights_the_blend_returns_the_llm_signal_unchanged(self) -> None:
        """RL 목표비중이 없으면 융합은 아무것도 바꾸지 않는다.

        실측 2026-09-04: 판단 경로(`portfolio_shadow`)는 `rl_target_weights`를 넘기지
        않는다. 그러면 `r_rl = r_llm`, `c_rl = c_llm`으로 대체되어 어떤 DSR 확률에서도
        기대수익률·확신도가 입력과 같다 — 즉 승격된 RL 정책이 이 경로로는 배분을 바꾸지
        못한다. 이 사실을 테스트로 못박아 둔다. 동작을 바꾸려면 이 테스트를 함께 고쳐야
        하고, 그때 그것이 판단 변경임을 의식하게 된다.
        """
        blender = SignalBlender(base_rl_weight=0.25, max_rl_weight=0.50)
        llm_returns = {"AAPL": 0.05, "MSFT": 0.02}
        llm_conf = {"AAPL": 0.80, "MSFT": 0.70}

        for dsr in (0.0, 0.5, 0.9, 0.99):
            with self.subTest(dsr=dsr):
                signals = blender.blend(
                    llm_expected_returns=llm_returns,
                    llm_confidences=llm_conf,
                    rl_dsr_probability=dsr,
                )
                for ticker in llm_returns:
                    self.assertAlmostEqual(llm_returns[ticker], signals[ticker].expected_return)
                    self.assertAlmostEqual(llm_conf[ticker], signals[ticker].confidence)

        # 바뀌는 것은 가중치 분해뿐이고, 그 가중치가 곱해지는 두 값이 같아서 결과가 같다.
        low = blender.blend(llm_expected_returns=llm_returns, rl_dsr_probability=0.0)["AAPL"]
        high = blender.blend(llm_expected_returns=llm_returns, rl_dsr_probability=0.99)["AAPL"]
        self.assertGreater(high.rl_weight, low.rl_weight)


if __name__ == "__main__":
    unittest.main()
