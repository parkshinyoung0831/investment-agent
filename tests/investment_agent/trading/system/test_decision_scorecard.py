"""TradingAgents 판단 성적표 — 논지 적중·확률 보정·순위 정보를 날짜 단위로 판정하는가."""
from __future__ import annotations

import random
import unittest

from investment_agent.trading.performance.decision_scorecard import decision_scorecard


def _data(*, informative: bool, days: int = 20, per_day: int = 10, seed: int = 1):
    rng = random.Random(seed)
    cases, evaluations = [], []
    for day in range(days):
        for index in range(per_day):
            key = f"c{day}_{index}"
            expected = rng.gauss(0, 0.02)
            noise = rng.gauss(0, 0.02)
            excess = (expected + 0.3 * noise) if informative else noise
            thesis = "positive" if expected > 0.005 else "negative" if expected < -0.005 else "neutral"
            probability = 0.5 + max(-0.4, min(0.4, expected * 10))
            cases.append({"case_key": key, "as_of_at": f"2026-03-{day + 1:02d}T21:00:00+00:00",
                          "final_decision": {"thesis": thesis, "probability_up": probability,
                                             "expected_excess_return": expected, "engine_version": "v1"}})
            evaluations.append({"case_key": key, "horizon_days": 20, "excess_return": excess,
                                "brier_score": (probability - (1.0 if excess > 0 else 0.0)) ** 2})
    return cases, evaluations


class DecisionScorecardTest(unittest.TestCase):
    def test_an_informative_engine_is_judged_as_helping(self):
        card = decision_scorecard(*_data(informative=True))["horizons"]["20"]["all"]
        self.assertEqual("helped", card["thesis_spread"]["verdict"])
        self.assertEqual("helped", card["expected_return_ic"]["verdict"])
        self.assertGreater(card["brier_skill"], 0.0)
        self.assertEqual(20, card["thesis"]["positive"]["days"])  # t는 판단이 아니라 날짜 단위다

    def test_a_noise_engine_is_not_judged_as_helping(self):
        card = decision_scorecard(*_data(informative=False))["horizons"]["20"]["all"]
        self.assertNotEqual("helped", card["thesis_spread"]["verdict"])
        self.assertNotEqual("helped", card["expected_return_ic"]["verdict"])
        self.assertLess(card["brier_skill"], 0.0)  # 확신만 있는 확률은 기준보다 못하다

    def test_calibration_buckets_compare_said_with_happened(self):
        card = decision_scorecard(*_data(informative=True))["horizons"]["20"]["all"]
        for bucket in card["calibration"]:
            self.assertLessEqual(bucket["range"][0], bucket["said"])
        self.assertEqual(200, sum(bucket["decisions"] for bucket in card["calibration"]))

    def test_old_records_without_a_thesis_field_are_read_from_the_signal_word(self):
        cases = [{"case_key": "a", "as_of_at": "2026-03-01", "final_decision": {"signal": "open"}},
                 {"case_key": "b", "as_of_at": "2026-03-01", "final_decision": {"signal": "exit"}}]
        evaluations = [{"case_key": "a", "horizon_days": 5, "excess_return": 0.01},
                       {"case_key": "b", "horizon_days": 5, "excess_return": -0.01}]
        card = decision_scorecard(cases, evaluations)["horizons"]["5"]["by_engine_version"]["unknown"]
        self.assertEqual({"positive", "negative"}, set(card["thesis"]))
        self.assertAlmostEqual(0.02, card["thesis_spread"]["mean"])


if __name__ == "__main__":
    unittest.main()
