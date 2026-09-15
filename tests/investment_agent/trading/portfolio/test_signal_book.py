from __future__ import annotations

import unittest

from investment_agent.trading.contracts import ContractError
from investment_agent.trading.portfolio.contracts import SecurityProposal
from investment_agent.trading.portfolio.signal_book import SignalBatch, SignalRecord


def proposal(ticker: str, as_of_at: str) -> SecurityProposal:
    return SecurityProposal(
        ticker=ticker, as_of_at=as_of_at, signal="open", probability_up=0.7, confidence=0.8,
        expected_excess_return=0.03, target_weight=0.1, reasoning=("evidence",), evidence_ids=(f"EV-{ticker}",),
    )


class SignalBatchTest(unittest.TestCase):
    def test_failed_symbol_makes_the_batch_incomplete(self):
        partial = SignalBatch(
            batch_id="batch-partial", as_of_at="2026-08-22T11:00:00+00:00", completed_at="2026-08-22T11:02:00+00:00",
            requested_symbols=("AAPL", "MSFT"), successful_symbols=("AAPL",), failed_symbols=("MSFT",),
        )
        self.assertFalse(partial.is_complete)

    def test_outcomes_must_be_requested_symbols(self):
        with self.assertRaises(ContractError):
            SignalBatch(batch_id="b", as_of_at="2026-08-22T11:00:00+00:00", completed_at="2026-08-22T11:02:00+00:00",
                        requested_symbols=("AAPL",), successful_symbols=("MSFT",))


class SignalRecordTest(unittest.TestCase):
    def test_record_identity_is_content_based_and_time_ordered(self):
        item = SignalRecord(batch_id="batch-1", proposal=proposal("AAPL", "2026-08-22T10:00:00+00:00"),
                            recorded_at="2026-08-22T10:01:00+00:00", expires_at="2026-08-22T14:00:00+00:00")
        again = SignalRecord(batch_id="batch-1", proposal=proposal("AAPL", "2026-08-22T10:00:00+00:00"),
                             recorded_at="2026-08-22T10:01:00+00:00", expires_at="2026-08-22T14:00:00+00:00")
        self.assertEqual(item.signal_id, again.signal_id)
        with self.assertRaises(ContractError):
            SignalRecord(batch_id="batch-1", proposal=proposal("AAPL", "2026-08-22T10:00:00+00:00"),
                         recorded_at="2026-08-22T09:59:00+00:00", expires_at="2026-08-22T14:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
