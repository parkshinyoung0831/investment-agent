"""실적 속보 서프라이즈 정의(NT-02·NT-03): 적자 컨센서스 방향, 축이 엇갈릴 때의 판정."""
from __future__ import annotations

import unittest

from investment_agent.notifications.earnings_flash.embeds import build_flash_embed
from investment_agent.notifications.earnings_flash.quickchart import flash_performance_chart_url
from investment_agent.notifications.earnings_flash.surprise import compute_surprise, judge


def _flash(**over):
    base = {"ticker": "TST", "fiscal_year": 2026, "fiscal_period": "Q2"}
    base.update(over)
    return {"flash": base}


class SurpriseDirectionTest(unittest.TestCase):
    def test_smaller_loss_than_expected_is_a_beat(self) -> None:
        self.assertGreater(compute_surprise(-0.5, -1.0), 0)
        self.assertLess(compute_surprise(-1.5, -1.0), 0)

    def test_chart_rate_uses_the_same_definition_for_negative_estimate(self) -> None:
        import json, urllib.parse

        url = flash_performance_chart_url(
            {"ticker": "TST", "eps_actual": -0.5, "eps_estimate": -1.0}
        )
        config = json.loads(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["c"][0])
        actual_rate = config["data"]["datasets"][1]["data"][0]
        self.assertEqual(actual_rate, 150.0)  # 손실이 절반으로 줄었으니 100% 위

    def test_positive_estimate_rate_is_unchanged(self) -> None:
        import json, urllib.parse

        url = flash_performance_chart_url({"ticker": "T", "eps_actual": 1.1, "eps_estimate": 1.0})
        config = json.loads(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["c"][0])
        self.assertEqual(config["data"]["datasets"][1]["data"][0], 110.0)


class JudgeTest(unittest.TestCase):
    def test_disagreeing_axes_are_neutral(self) -> None:
        self.assertEqual(judge([-20.0, 0.01]), "inline")
        self.assertEqual(judge([15.0, -5.0]), "inline")

    def test_agreeing_axes_decide(self) -> None:
        self.assertEqual(judge([5.0, 1.0]), "beat")
        self.assertEqual(judge([-5.0, -3.0]), "miss")
        self.assertEqual(judge([None, 4.0]), "beat")
        self.assertEqual(judge([None, None]), "inline")

    def test_embed_does_not_call_a_big_eps_miss_a_surprise(self) -> None:
        embed = build_flash_embed(_flash(
            eps_actual=0.8, eps_estimate=1.0, revenue_actual=100.01, revenue_estimate=100.0,
        ))
        self.assertNotIn("서프라이즈", embed["description"] + str(embed.get("title", "")) + str(embed))


if __name__ == "__main__":
    unittest.main()
