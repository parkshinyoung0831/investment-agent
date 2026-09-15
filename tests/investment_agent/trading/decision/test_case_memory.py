"""다음 판단에 넘기는 기억: 평가된 사례와, 결과를 모르는 직전 판단을 섞지 않는다."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from investment_agent.trading.decision.memory import CaseMemory

AS_OF = datetime(2026, 9, 14, 15, tzinfo=timezone.utc)


class _Repository:
    def __init__(self, *, evaluated=(), previous=None):
        self.evaluated = list(evaluated)
        self.previous = previous
        self.asked = []

    def evaluated_memories(self, ticker, limit=5, as_of_at=None):
        return list(self.evaluated)

    def previous_decision(self, ticker, *, as_of_at):
        self.asked.append(as_of_at)
        return self.previous


PREVIOUS = {
    "case_key": "AAPL__prev",
    "as_of_at": "2026-09-13T15:00:00+00:00",
    "final_decision": {"signal": "increase", "expected_excess_return": 0.02, "probability_up": 0.6,
                       "confidence": 0.7, "evidence_ids": ["EV-1"], "reasoning": ["a", "b", "c", "d"],
                       "target_weight": 0.3},
}


class CaseMemoryTest(unittest.TestCase):
    def test_no_history_keeps_the_plain_message(self):
        self.assertEqual(CaseMemory(_Repository()).render("AAPL", as_of_at=AS_OF), "평가가 완료된 과거 사례 없음")

    def test_previous_decision_is_labelled_unevaluated_and_carries_the_continuity_rule(self):
        repository = _Repository(previous=PREVIOUS)
        payload = json.loads(CaseMemory(repository).render("AAPL", as_of_at=AS_OF))
        previous = payload["previous_decision"]
        self.assertEqual(previous["signal"], "increase")
        self.assertIn("평가되지 않음", previous["outcome"])
        self.assertEqual(previous["reasoning"], ["a", "b", "c"])
        self.assertNotIn("target_weight", previous)
        # 그날 번들의 ID를 넘기면 오늘 판단이 인용해 계약 위반으로 종목 전체가 실패한다.
        self.assertNotIn("evidence_ids", previous)
        self.assertIn("근거 ID", payload["continuity_rule"])
        self.assertEqual(repository.asked, [AS_OF])

    def test_evaluated_cases_stay_separate_from_the_previous_view(self):
        payload = json.loads(CaseMemory(_Repository(evaluated=[{"case_key": "old"}], previous=PREVIOUS))
                             .render("AAPL", as_of_at=AS_OF))
        self.assertEqual(payload["evaluated_cases"], [{"case_key": "old"}])
        self.assertEqual(payload["previous_decision"]["case_key"], "AAPL__prev")

    def test_without_as_of_the_previous_decision_is_not_read(self):
        repository = _Repository(previous=PREVIOUS)
        CaseMemory(repository).render("AAPL")
        self.assertEqual(repository.asked, [])


if __name__ == "__main__":
    unittest.main()
