"""Event refresh가 read repository와 Research write use case를 분리해 조립하는지 검증한다."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from investment_agent.operations.commands.event_reanalysis import _refresh_events


AS_OF = datetime(2026, 9, 20, 1, tzinfo=timezone.utc)


class EventRefreshCompositionTest(unittest.TestCase):
    def test_tracked_ticker_reader_is_not_reused_as_the_event_store(self) -> None:
        with (
            patch(
                "investment_agent.trading.supabase_repository.SupabaseRepository"
            ) as repository_factory,
            patch("investment_agent.trading.evidence.cache.LocalEvidenceCache") as cache_factory,
            patch("investment_agent.research.commands.build_events.build_events") as build,
        ):
            repository_factory.return_value.current_tracked_tickers.return_value = ["AAPL"]
            build.return_value = {"events": 0, "snapshots": 0}

            result = _refresh_events(AS_OF)

        self.assertEqual(result, {"events": 0, "snapshots": 0})
        kwargs = build.call_args.kwargs
        self.assertIs(kwargs["cache"], cache_factory.return_value)
        self.assertEqual(kwargs["as_of_at"], AS_OF.isoformat())
        self.assertEqual(kwargs["tickers"], ["AAPL"])
        self.assertNotIn("repository", kwargs)


if __name__ == "__main__":
    unittest.main()
