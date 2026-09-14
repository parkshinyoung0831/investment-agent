from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.trading.decision.candidate_ranker import (
    PriorityCandidate,
    merge_priority_lane,
    priority_candidates,
)

AS_OF = datetime(2026, 9, 14, 15, tzinfo=timezone.utc)
UNIVERSE = ("AAPL", "MSFT", "NVDA", "META", "AMZN")


def _event(ticker: str, *, available: datetime, importance: float = 0.8, high: int = 1) -> dict:
    return {
        "ticker": ticker, "available_at": available.isoformat(),
        "event_importance": importance, "high_impact_event_count": high,
    }


class PriorityCandidateTest(unittest.TestCase):
    def rank(self, **overrides):
        values = dict(
            tickers=UNIVERSE, held_tickers=("AAPL", "MSFT"),
            last_analyzed_at={symbol: AS_OF - timedelta(hours=2) for symbol in UNIVERSE},
            latest_filed_at={}, event_features=(), as_of_at=AS_OF,
        )
        values.update(overrides)
        return priority_candidates(**values)

    def test_nothing_new_means_no_priority(self):
        self.assertEqual(self.rank(), ())

    def test_held_position_with_a_filing_after_its_last_analysis_jumps_the_queue(self):
        result = self.rank(
            last_analyzed_at={"AAPL": AS_OF - timedelta(days=2), "MSFT": AS_OF - timedelta(hours=2)},
            latest_filed_at={"AAPL": (AS_OF - timedelta(days=1)).date().isoformat(), "NVDA": AS_OF.date().isoformat()},
        )
        self.assertEqual([(item.ticker, item.reason) for item in result], [("AAPL", "held_new_filing")])

    def test_filing_already_seen_by_the_last_analysis_is_not_new(self):
        result = self.rank(latest_filed_at={"AAPL": (AS_OF - timedelta(days=3)).date().isoformat()})
        self.assertEqual(result, ())

    def test_held_events_outrank_unheld_events_and_unpublished_events_are_ignored(self):
        result = self.rank(event_features=(
            _event("NVDA", available=AS_OF - timedelta(minutes=30), importance=0.95),
            _event("MSFT", available=AS_OF - timedelta(minutes=30), importance=0.5),
            _event("META", available=AS_OF + timedelta(minutes=5), importance=0.99),
            _event("AMZN", available=AS_OF - timedelta(minutes=30), importance=0.6),
        ))
        self.assertEqual(
            [(item.ticker, item.tier) for item in result],
            [("MSFT", 0), ("NVDA", 1)],
        )

    def test_low_impact_news_does_not_trigger(self):
        result = self.rank(event_features=(_event("AAPL", available=AS_OF - timedelta(minutes=10), high=0),))
        self.assertEqual(result, ())

    def test_held_position_never_analyzed_is_covered_first(self):
        result = self.rank(last_analyzed_at={})
        self.assertEqual([item.reason for item in result], ["held_never_analyzed", "held_never_analyzed"])

    def test_positions_outside_the_tracked_universe_are_not_selected(self):
        result = self.rank(held_tickers=("TSLA",), last_analyzed_at={})
        self.assertEqual(result, ())


    def test_lane_fills_first_then_regular_ranking_without_duplicates(self):
        lane = (PriorityCandidate("MSFT", 0, "held_new_filing", 1.0), PriorityCandidate("NVDA", 1, "event", 0.9))
        self.assertEqual(merge_priority_lane(lane, ["AAPL", "MSFT", "META"], limit=3), ["MSFT", "NVDA", "AAPL"])
        self.assertEqual(
            merge_priority_lane(lane, ["AAPL", "MSFT", "META"], limit=10), ["MSFT", "NVDA", "AAPL", "META"],
        )
        self.assertEqual(merge_priority_lane((), ["AAPL", "MSFT"], limit=5), ["AAPL", "MSFT"])


if __name__ == "__main__":
    unittest.main()
