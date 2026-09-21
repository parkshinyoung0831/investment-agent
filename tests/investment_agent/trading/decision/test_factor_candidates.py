"""factor 기반 분석 후보 선정: 품질 기준·보유 붕괴 우선·유효 판단 재분석 금지·횡단면 선택."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.research.features.factors import FactorScore, latest_cross_section
from investment_agent.trading.contracts import ContractError
from investment_agent.trading.decision.candidate_ranker import select_factor_candidates
from investment_agent.trading.decision.universe import NoCandidatesDue, select_tracked_tickers

AS_OF = datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc)


def _score(ticker: str, composite: float | None, *, passes: bool = True) -> FactorScore:
    return FactorScore(ticker, {"quality": 0.8 if passes else 0.1}, composite, passes,
                       None if passes else "quality_below_floor")


class SelectFactorCandidatesTest(unittest.TestCase):
    def test_shortlist_is_ordered_by_composite_and_excludes_gate_failures(self):
        scores = {"A": _score("A", 0.6), "B": _score("B", 0.9), "JUNK": _score("JUNK", 0.99, passes=False)}
        result = select_factor_candidates(scores, held_tickers=[], last_analyzed_at={}, as_of_at=AS_OF)
        self.assertEqual([row.ticker for row in result], ["B", "A"])
        self.assertTrue(all(row.reason == "shortlist_due" for row in result))

    def test_names_outside_the_shortlist_are_not_analyzed(self):
        scores = {name: _score(name, value) for name, value in (("A", 0.9), ("B", 0.8), ("C", 0.1))}
        result = select_factor_candidates(scores, held_tickers=[], last_analyzed_at={}, as_of_at=AS_OF, shortlist_size=2)
        self.assertEqual([row.ticker for row in result], ["A", "B"])

    def test_recently_judged_names_are_not_reanalyzed_even_with_budget_left(self):
        scores = {"A": _score("A", 0.9), "B": _score("B", 0.8)}
        recent = {"A": AS_OF - timedelta(days=3), "B": AS_OF - timedelta(days=40)}
        result = select_factor_candidates(scores, held_tickers=[], last_analyzed_at=recent, as_of_at=AS_OF)
        self.assertEqual([row.ticker for row in result], ["B"])

    def test_held_breakdown_comes_first_and_respects_its_own_review_interval(self):
        scores = {"TOP": _score("TOP", 0.9), "HELD": _score("HELD", 0.2, passes=False)}
        result = select_factor_candidates(
            scores, held_tickers=["held"], last_analyzed_at={"HELD": AS_OF - timedelta(days=6)}, as_of_at=AS_OF,
        )
        self.assertEqual([(row.ticker, row.reason) for row in result][0], ("HELD", "held_factor_breakdown"))
        again = select_factor_candidates(
            scores, held_tickers=["HELD"], last_analyzed_at={"HELD": AS_OF - timedelta(days=2)}, as_of_at=AS_OF,
        )
        self.assertNotIn("HELD", [row.ticker for row in again])

    def test_stale_held_names_outside_the_shortlist_are_still_reviewed(self):
        scores = {"TOP": _score("TOP", 0.9), "HELD": _score("HELD", 0.3)}
        result = select_factor_candidates(
            scores, held_tickers=["HELD"], last_analyzed_at={"HELD": AS_OF - timedelta(days=30)},
            as_of_at=AS_OF, shortlist_size=1,
        )
        self.assertEqual([(row.ticker, row.reason) for row in result], [("TOP", "shortlist_due"), ("HELD", "held_due")])

    def test_a_ticker_appears_once(self):
        scores = {"A": _score("A", 0.9)}
        result = select_factor_candidates(scores, held_tickers=["A"], last_analyzed_at={}, as_of_at=AS_OF)
        self.assertEqual([row.ticker for row in result], ["A"])


class LatestCrossSectionTest(unittest.TestCase):
    def _rows(self, as_of: str, count: int) -> list[dict]:
        return [{"as_of_at": as_of, "ticker": f"t{i}", "features": {"x": i}}
                for i in range(count)]

    def test_partial_latest_day_falls_back_to_the_last_complete_day(self):
        rows = self._rows("2026-09-14T22:00:00+00:00", 3) + self._rows("2026-09-13T22:00:00+00:00", 10)
        as_of, features = latest_cross_section(rows, min_coverage=5)
        self.assertEqual(as_of, "2026-09-13T22:00:00+00:00")
        self.assertEqual(len(features), 10)


class _Repository:
    def __init__(self, candidates):
        self.candidates = candidates

    def current_tracked_tickers(self):
        return ["A", "B"]

    def candidate_tickers(self, limit=50, *, as_of_at):
        return self.candidates


class NoCandidatesDueTest(unittest.TestCase):
    def test_empty_automatic_selection_is_a_distinct_no_work_signal(self):
        with self.assertRaises(NoCandidatesDue):
            select_tracked_tickers(_Repository([]), None, limit=5, as_of_at=AS_OF)

    def test_explicit_empty_request_is_still_a_contract_error(self):
        with self.assertRaises(ContractError) as caught:
            select_tracked_tickers(_Repository(["A"]), [" "], limit=5, as_of_at=AS_OF)
        self.assertNotIsInstance(caught.exception, NoCandidatesDue)


if __name__ == "__main__":
    unittest.main()
