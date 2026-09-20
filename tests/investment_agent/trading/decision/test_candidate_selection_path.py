"""SupabaseRepository.candidate_tickers가 factor 횡단면이 있으면 factor로, 없으면 예전 랭커로 고르는지."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from investment_agent.research.features.factors import FactorScore
from investment_agent.trading.decision.candidate_ranker import PriorityCandidate
from investment_agent.trading.supabase_repository import SupabaseRepository

AS_OF = datetime.now(timezone.utc) - timedelta(minutes=1)


def _repository(factor_scores):
    repository = object.__new__(SupabaseRepository)
    repository.current_tracked_tickers = lambda: ["AAA", "BBB", "CCC", "EVT"]
    repository._last_attempted = lambda tickers, as_of_at: {}
    repository._candidate_fundamental_rows = lambda tickers, as_of_at: []
    repository._candidate_held_tickers = lambda: []
    repository._candidate_event_features = lambda as_of_at: []
    repository._candidate_factor_scores = lambda tickers, as_of_at: factor_scores
    repository._candidate_market_rows = lambda tickers, as_of_at: []
    repository._candidate_technical_rows = lambda tickers, as_of_at: []
    repository._candidate_segment_signals = lambda tickers, as_of_at: {}
    repository._candidate_guru_signals = lambda tickers, as_of_at: {}
    return repository


class CandidateSelectionPathTest(unittest.TestCase):
    def test_factor_path_puts_priority_first_then_composite_order(self):
        scores = {
            "AAA": FactorScore("AAA", {"quality": 0.9}, 0.4, True, None),
            "BBB": FactorScore("BBB", {"quality": 0.9}, 0.8, True, None),
            "CCC": FactorScore("CCC", {"quality": 0.1}, 0.95, False, "quality_below_floor"),
        }
        priority = (PriorityCandidate("EVT", 1, "high_impact_event", 0.9),)
        with mock.patch("investment_agent.trading.decision.candidates.priority_candidates", return_value=priority):
            selected = _repository(("2026-09-14T22:00:00+00:00", scores)).candidate_tickers(10, as_of_at=AS_OF)
        self.assertEqual(selected, ["EVT", "BBB", "AAA"])

    def test_missing_cross_section_falls_back_to_the_rotation_ranker(self):
        with mock.patch("investment_agent.trading.decision.candidates.priority_candidates", return_value=()):
            selected = _repository(None).candidate_tickers(10, as_of_at=AS_OF)
        self.assertEqual(sorted(selected), ["AAA", "BBB", "CCC", "EVT"])


if __name__ == "__main__":
    unittest.main()
