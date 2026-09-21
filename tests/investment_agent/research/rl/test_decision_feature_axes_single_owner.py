"""판단 feature의 축(이름·순서)은 `decision_dataset` 한 곳이 소유하고, 생산자는 그것을 그대로 쓴다.

생산자(`build_decision_experiences`)가 `ACTIONS`와 feature 조립을 자기 손으로 복제해 두었고, 소비자가 축을
검사(`set(row["features"]) != set(FEATURE_NAMES)`)하는 정의는 다른 파일에 있었다. 한쪽만 고치면 학습 입력이
"decision feature axes mismatch"로 통째로 거부된다.
"""
from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from investment_agent.research.commands import build_decision_experiences as producer
from investment_agent.research.rl import decision_dataset as consumer


class _Prices:
    def price_path(self, ticker, start_date, limit=80):
        return [dict(trade_date=str(date(2026, 1, 2) + timedelta(days=i)), close=100 + i, div_amount=0) for i in range(6)]


def _case(action: str) -> dict:
    return dict(
        case_key="c", ticker="ABC", as_of_at="2026-01-01T22:00:00+00:00",
        final_decision=dict(signal=action, confidence=0.8, probability_up=0.2, expected_excess_return=-0.03),
    )


class DecisionFeatureAxesTest(unittest.TestCase):
    def test_the_producer_does_not_redeclare_the_action_list(self):
        self.assertIs(producer.ACTIONS, consumer.ACTIONS)

    def test_every_action_produces_exactly_the_consumer_axes(self):
        for action in consumer.ACTIONS:
            with self.subTest(action=action):
                row = producer.build_experience(
                    _Prices(), _case(action), as_of_at=datetime(2026, 1, 8, tzinfo=timezone.utc), horizon_days=5,
                )
                self.assertEqual(set(row["features"]), set(consumer.FEATURE_NAMES))

    def test_the_produced_features_equal_the_shared_conversion(self):
        row = producer.build_experience(
            _Prices(), _case("open"), as_of_at=datetime(2026, 1, 8, tzinfo=timezone.utc), horizon_days=5,
        )
        expected = consumer.decision_features(
            {"signal": "open", "confidence": 0.8, "probability_up": 0.2, "expected_excess_return": -0.03}
        )
        self.assertEqual(row["features"], expected)


if __name__ == "__main__":
    unittest.main()
