"""AI 판단 universe가 현재 S&P 500 밖으로 벗어나지 않는지 검증한다."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from investment_agent.trading.contracts import ContractError
from investment_agent.trading.decision.universe import rotate_after_latest_cases, select_tracked_tickers

_AS_OF = datetime(2026, 8, 21, 21, 0, tzinfo=timezone.utc)


class _Repository:
    def __init__(self, members=("AAPL", "MSFT"), candidates=("MSFT",)):
        self.members = list(members)
        self.candidates = list(candidates)

    def current_tracked_tickers(self):
        return self.members

    def candidate_tickers(self, limit=50, *, as_of_at):
        self.as_of_at = as_of_at
        return self.candidates[:limit]


class UniverseSelectionTest(unittest.TestCase):
    def test_implicit_selection_uses_only_repository_candidates(self):
        repository = _Repository()
        selection = select_tracked_tickers(
            repository, None, limit=1, as_of_at=_AS_OF
        )
        self.assertEqual(selection.selected, ("MSFT",))
        self.assertEqual(selection.members, frozenset({"AAPL", "MSFT"}))
        self.assertEqual(repository.as_of_at, _AS_OF)

    def test_explicit_non_member_fails_closed(self):
        with self.assertRaises(ContractError):
            select_tracked_tickers(
                _Repository(), ["NVDA"], limit=5, as_of_at=_AS_OF
            )

    def test_explicit_share_class_ticker_uses_universe_dash_notation(self):
        selection = select_tracked_tickers(
            _Repository(members=("BRK-B",), candidates=()),
            ["brk.b"],
            limit=1,
            as_of_at=_AS_OF,
        )
        self.assertEqual(selection.selected, ("BRK-B",))

    def test_candidate_outside_universe_fails_closed(self):
        with self.assertRaises(ContractError):
            select_tracked_tickers(
                _Repository(candidates=("AAPL", "TSLA")),
                None,
                limit=5,
                as_of_at=_AS_OF,
            )

    def test_empty_current_universe_fails_closed(self):
        with self.assertRaises(ContractError):
            select_tracked_tickers(
                _Repository(members=(), candidates=()),
                None,
                limit=5,
                as_of_at=_AS_OF,
            )

    def test_naive_candidate_cutoff_fails_closed(self):
        with self.assertRaisesRegex(ContractError, "timezone"):
            select_tracked_tickers(
                _Repository(), None, limit=1, as_of_at=datetime(2026, 8, 21)
            )

    def test_rotation_continues_after_last_ticker_in_latest_run(self):
        selected = rotate_after_latest_cases(
            ["AAPL", "AMZN", "MSFT", "NVDA"],
            [
                {"ticker": "AMZN", "as_of_at": "2026-08-21T00:00:00+00:00"},
                {"ticker": "AAPL", "as_of_at": "2026-08-21T00:00:00+00:00"},
                {"ticker": "NVDA", "as_of_at": "2026-08-20T00:00:00+00:00"},
            ],
            limit=2,
        )
        self.assertEqual(selected, ["MSFT", "NVDA"])

    def test_rotation_handles_wraparound_batch_without_repeating_aaa(self):
        selected = rotate_after_latest_cases(
            ["AAA", "BBB", "CCC", "YYY", "ZZZ"],
            [
                {"ticker": "YYY", "as_of_at": "2026-08-21T00:00:00+00:00"},
                {"ticker": "ZZZ", "as_of_at": "2026-08-21T00:00:00+00:00"},
                {"ticker": "AAA", "as_of_at": "2026-08-21T00:00:00+00:00"},
            ],
            limit=2,
        )
        self.assertEqual(selected, ["BBB", "CCC"])


if __name__ == "__main__":
    unittest.main()
