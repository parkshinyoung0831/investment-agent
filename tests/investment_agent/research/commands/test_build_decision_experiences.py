"""Decision experience producer가 read source와 ResearchStore를 분리하는지 검증한다."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from investment_agent.research.commands.build_decision_experiences import run


class _Reader:
    def decision_cases_for_experiences(self):
        return [{
            "case_key": "case-1", "ticker": "AAPL",
            "as_of_at": "2026-01-01T00:00:00+00:00",
            "final_decision": {
                "signal": "open", "confidence": 0.8,
                "probability_up": 0.6, "expected_excess_return": 0.03,
            },
        }]

    def price_path(self, ticker, start_date, limit=80):
        return [
            {"trade_date": str(date(2026, 1, 2) + timedelta(days=index)),
             "close": 100 + index, "div_amount": 0}
            for index in range(25)
        ]


class _Store:
    def __init__(self):
        self.rows: list[dict] = []

    def decision_experience_rows(self):
        return list(self.rows)

    def save_decision_experiences(self, rows):
        self.rows.extend(rows)


class BuildDecisionExperiencesTest(unittest.TestCase):
    def test_reads_and_writes_experiences_through_research_store(self):
        store = _Store()
        saved = run(
            _Reader(), store=store,
            as_of_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(saved, 1)
        self.assertEqual([row["case_key"] for row in store.rows], ["case-1"])

    def test_existing_experience_is_not_recomputed(self):
        store = _Store()
        store.rows.append({"case_key": "case-1", "provenance": {"version": "decision_experience_v1"}})
        self.assertEqual(run(
            _Reader(), store=store,
            as_of_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        ), 0)
        self.assertEqual(len(store.rows), 1)


if __name__ == "__main__":
    unittest.main()
