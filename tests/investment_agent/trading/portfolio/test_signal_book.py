from __future__ import annotations

import unittest

from investment_agent.trading.contracts import ContractError
from investment_agent.trading.portfolio.contracts import SecurityProposal
from investment_agent.trading.portfolio.signal_book import SignalBatch, SignalBook, SignalRecord


def proposal(ticker: str, as_of_at: str, *, target: float = 0.1) -> SecurityProposal:
    return SecurityProposal(
        ticker=ticker,
        as_of_at=as_of_at,
        signal="open",
        probability_up=0.7,
        confidence=0.8,
        expected_excess_return=0.03,
        target_weight=target,
        reasoning=("evidence",),
        evidence_ids=(f"EV-{ticker}",),
    )


def complete_batch(batch_id: str, ticker: str, as_of_at: str, completed_at: str) -> SignalBatch:
    return SignalBatch(
        batch_id=batch_id,
        as_of_at=as_of_at,
        completed_at=completed_at,
        requested_symbols=(ticker,),
        successful_symbols=(ticker,),
    )


def record(batch_id: str, ticker: str, as_of_at: str, recorded_at: str, expires_at: str) -> SignalRecord:
    return SignalRecord(
        batch_id=batch_id,
        proposal=proposal(ticker, as_of_at),
        recorded_at=recorded_at,
        expires_at=expires_at,
        case_key=f"case-{batch_id}-{ticker}",
    )


class SignalBookTest(unittest.TestCase):
    def test_latest_valid_uses_only_complete_batches(self):
        old_batch = complete_batch(
            "batch-old", "AAPL", "2026-08-22T10:00:00+00:00", "2026-08-22T10:02:00+00:00"
        )
        old_record = record(
            "batch-old", "AAPL", "2026-08-22T10:00:00+00:00",
            "2026-08-22T10:01:00+00:00", "2026-08-22T14:00:00+00:00",
        )
        partial_batch = SignalBatch(
            batch_id="batch-partial",
            as_of_at="2026-08-22T11:00:00+00:00",
            completed_at="2026-08-22T11:02:00+00:00",
            requested_symbols=("AAPL", "MSFT"),
            successful_symbols=("AAPL",),
            failed_symbols=("MSFT",),
        )
        partial_record = record(
            "batch-partial", "AAPL", "2026-08-22T11:00:00+00:00",
            "2026-08-22T11:01:00+00:00", "2026-08-22T14:00:00+00:00",
        )
        book = SignalBook(
            batches=(partial_batch, old_batch),
            records=(partial_record, old_record),
        )
        latest = book.latest_valid(as_of_at="2026-08-22T12:00:00+00:00")
        self.assertEqual(latest["AAPL"].batch_id, "batch-old")
        with self.assertRaisesRegex(ContractError, "partial or failed"):
            book.assert_batch_execution_ready(
                "batch-partial", as_of_at="2026-08-22T12:00:00+00:00"
            )

    def test_expiry_is_exclusive_and_complete_batch_requires_fresh_record(self):
        batch = complete_batch(
            "batch-1", "AAPL", "2026-08-22T10:00:00+00:00", "2026-08-22T10:02:00+00:00"
        )
        item = record(
            "batch-1", "AAPL", "2026-08-22T10:00:00+00:00",
            "2026-08-22T10:01:00+00:00", "2026-08-22T12:00:00+00:00",
        )
        book = SignalBook(batches=(batch,), records=(item,))
        self.assertTrue(item.is_valid_at("2026-08-22T11:59:59+00:00"))
        self.assertFalse(item.is_valid_at("2026-08-22T12:00:00+00:00"))
        with self.assertRaisesRegex(ContractError, "missing or expired"):
            book.assert_batch_execution_ready(
                "batch-1", as_of_at="2026-08-22T12:00:00+00:00"
            )

    def test_append_returns_a_new_book_without_mutating_the_original(self):
        batch = complete_batch(
            "batch-1", "AAPL", "2026-08-22T10:00:00+00:00", "2026-08-22T10:02:00+00:00"
        )
        item = record(
            "batch-1", "AAPL", "2026-08-22T10:00:00+00:00",
            "2026-08-22T10:01:00+00:00", "2026-08-22T14:00:00+00:00",
        )
        original = SignalBook()
        updated = original.append(batch, (item,))
        self.assertEqual(original.batches, ())
        self.assertEqual(updated.batch("batch-1"), batch)
        self.assertEqual(
            updated.assert_batch_execution_ready(
                "batch-1", as_of_at="2026-08-22T12:00:00+00:00"
            ),
            batch,
        )

    def test_record_must_belong_to_a_successful_symbol_in_same_as_of_batch(self):
        batch = complete_batch(
            "batch-1", "MSFT", "2026-08-22T10:00:00+00:00", "2026-08-22T10:02:00+00:00"
        )
        item = record(
            "batch-1", "AAPL", "2026-08-22T10:00:00+00:00",
            "2026-08-22T10:01:00+00:00", "2026-08-22T14:00:00+00:00",
        )
        with self.assertRaisesRegex(ContractError, "successful batch outcome"):
            SignalBook(batches=(batch,), records=(item,))


if __name__ == "__main__":
    unittest.main()
