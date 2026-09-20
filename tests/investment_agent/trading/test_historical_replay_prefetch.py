"""과거 재현 입력은 날짜별 일괄 조회 후 기존 종목별 계약에서 재사용한다."""
from __future__ import annotations

import unittest
from threading import Barrier
from datetime import datetime, timezone
from unittest import mock

from investment_agent.trading.supabase_repository import SupabaseRepository


AS_OF = datetime(2025, 1, 17, 23, 30, tzinfo=timezone.utc)


class _Mirror:
    def split_histories(self, tickers):
        return {ticker: [{"ticker": ticker, "action_date": "2024-01-01", "split_ratio": 2.0}]
                for ticker in tickers}


class HistoricalReplayPrefetchTest(unittest.TestCase):
    def test_a_transient_domain_read_is_retried_without_repeating_successful_domains(self):
        repository = SupabaseRepository()
        repository._mirror = lambda as_of_at=None: _Mirror()
        module = __import__("investment_agent.research.evidence.reader", fromlist=["fundamentals_expectations"])
        with (
            mock.patch.object(
                module.fundamentals_expectations, "securities_fundamentals_filed_before",
                side_effect=[ConnectionError("temporary"), []],
            ) as fundamentals,
            mock.patch.object(module.fundamentals_expectations, "observed_consensus_for_tickers_as_of", return_value={}) as consensus,
            mock.patch.object(module.fundamentals_shares, "share_class_snapshots_for_tickers_filed_before", return_value={}) as shares,
            mock.patch.object(module.fundamentals_segments, "segment_snapshots_as_of", return_value={}) as segments,
        ):
            repository.prepare_historical_replay(["AAA"], AS_OF)
        self.assertEqual(fundamentals.call_count, 2)
        consensus.assert_called_once()
        shares.assert_called_once()
        segments.assert_called_once()

    def test_independent_remote_domains_are_prefetched_concurrently(self):
        repository = SupabaseRepository()
        repository._mirror = lambda as_of_at=None: _Mirror()
        module = __import__("investment_agent.research.evidence.reader", fromlist=["fundamentals_expectations"])
        barrier = Barrier(4, timeout=1.0)

        def rows(*args, **kwargs):
            barrier.wait()
            return []

        def mapping(*args, **kwargs):
            barrier.wait()
            return {}

        with (
            mock.patch.object(module.fundamentals_expectations, "securities_fundamentals_filed_before", side_effect=rows),
            mock.patch.object(module.fundamentals_expectations, "observed_consensus_for_tickers_as_of", side_effect=mapping),
            mock.patch.object(module.fundamentals_shares, "share_class_snapshots_for_tickers_filed_before", side_effect=mapping),
            mock.patch.object(module.fundamentals_segments, "segment_snapshots_as_of", side_effect=mapping),
        ):
            repository.prepare_historical_replay(["AAA"], AS_OF)

    def test_prefetch_seeds_all_per_ticker_read_contracts(self):
        repository = SupabaseRepository()
        repository._mirror = lambda as_of_at=None: _Mirror()
        with (
            mock.patch.object(
                __import__("investment_agent.research.evidence.reader", fromlist=["fundamentals_expectations"])
                .fundamentals_expectations,
                "securities_fundamentals_filed_before",
                return_value=[{"ticker": "AAA", "period_end": "2024-12-31"}],
            ) as fundamentals,
            mock.patch.object(
                __import__("investment_agent.research.evidence.reader", fromlist=["fundamentals_expectations"])
                .fundamentals_expectations,
                "observed_consensus_for_tickers_as_of",
                return_value={"AAA": [{"ticker": "AAA", "snapshot_date": "2025-01-01"}]},
            ) as consensus,
            mock.patch.object(
                __import__("investment_agent.research.evidence.reader", fromlist=["fundamentals_shares"])
                .fundamentals_shares,
                "share_class_snapshots_for_tickers_filed_before",
                return_value={"AAA": [{"ticker": "AAA", "shares_outstanding": 10}]},
            ) as shares,
            mock.patch.object(
                __import__("investment_agent.research.evidence.reader", fromlist=["fundamentals_segments"])
                .fundamentals_segments,
                "segment_snapshots_as_of",
                return_value={"AAA": {"filings": [], "metrics": []}},
            ) as segments,
        ):
            repository.prepare_historical_replay(["AAA", "BBB"], AS_OF)
            self.assertEqual(repository.fundamentals_pit("AAA", AS_OF),
                             [{"ticker": "AAA", "period_end": "2024-12-31"}])
            self.assertEqual(repository.estimates("AAA", AS_OF)["consensus"][0]["snapshot_date"], "2025-01-01")
            self.assertEqual(repository.share_class_snapshots_pit("AAA", AS_OF)[0]["shares_outstanding"], 10)
            self.assertEqual(repository.split_history("AAA")[0]["split_ratio"], 2.0)
            self.assertEqual(repository.segment_snapshot("BBB", AS_OF), {"filings": [], "metrics": []})
            fundamentals.assert_called_once()
            consensus.assert_called_once()
            shares.assert_called_once()
            segments.assert_called_once()

    def test_a_new_replay_date_discards_date_scoped_prefetch_entries(self):
        repository = SupabaseRepository()
        repository._mirror = lambda as_of_at=None: _Mirror()
        module = __import__("investment_agent.research.evidence.reader", fromlist=["fundamentals_expectations"])
        empty_batches = (
            mock.patch.object(module.fundamentals_expectations, "securities_fundamentals_filed_before", return_value=[]),
            mock.patch.object(module.fundamentals_expectations, "observed_consensus_for_tickers_as_of", return_value={}),
            mock.patch.object(module.fundamentals_shares, "share_class_snapshots_for_tickers_filed_before", return_value={}),
            mock.patch.object(module.fundamentals_segments, "segment_snapshots_as_of", return_value={}),
        )
        with empty_batches[0], empty_batches[1], empty_batches[2], empty_batches[3]:
            repository.prepare_historical_replay(["AAA"], AS_OF)
            later = AS_OF.replace(day=24)
            repository.prepare_historical_replay(["AAA"], later)
        keys = set(repository._reader_cache().__dict__["_memo_state"]["values"])
        old_point = AS_OF.isoformat()
        self.assertFalse(any(old_point in key for key in keys))
        self.assertTrue(any(later.isoformat() in key for key in keys))


if __name__ == "__main__":
    unittest.main()
