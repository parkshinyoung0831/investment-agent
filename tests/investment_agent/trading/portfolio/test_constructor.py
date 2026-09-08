from __future__ import annotations

import unittest

from investment_agent.trading.contracts import ContractError
from investment_agent.trading.portfolio.constructor import (
    PortfolioConstructionPolicy,
    PortfolioConstructor,
)
from investment_agent.trading.portfolio.contracts import SecurityProposal
from investment_agent.trading.portfolio.signal_book import SignalBatch, SignalBook, SignalRecord
from investment_agent.execution.orders.snapshots import AccountSnapshot, PositionSnapshot

SIGNAL_AS_OF = "2026-08-22T12:00:00+00:00"
RECORDED_AT = "2026-08-22T12:01:00+00:00"
COMPLETED_AT = "2026-08-22T12:02:00+00:00"
DECISION_AT = "2026-08-22T12:05:00+00:00"


def security(ticker: str, signal: str, target: float) -> SecurityProposal:
    return SecurityProposal(
        ticker=ticker,
        as_of_at=SIGNAL_AS_OF,
        signal=signal,
        probability_up=0.7,
        confidence=0.8,
        expected_excess_return=0.03,
        target_weight=target,
        reasoning=("evidence",),
        evidence_ids=(f"EV-{ticker}",),
    )


def book_for(*proposals: SecurityProposal, failed: tuple[str, ...] = ()) -> SignalBook:
    successful = tuple(proposal.ticker for proposal in proposals)
    requested = (*successful, *failed)
    batch = SignalBatch(
        batch_id="batch-active",
        as_of_at=SIGNAL_AS_OF,
        completed_at=COMPLETED_AT,
        requested_symbols=requested,
        successful_symbols=successful,
        failed_symbols=failed,
    )
    records = tuple(
        SignalRecord(
            batch_id=batch.batch_id,
            proposal=proposal,
            recorded_at=RECORDED_AT,
            expires_at="2026-08-22T18:00:00+00:00",
            case_key=f"case-{proposal.ticker}",
        )
        for proposal in proposals
    )
    return SignalBook(batches=(batch,), records=records)


def snapshot(*, captured_at: str = "2026-08-22T12:04:00+00:00") -> AccountSnapshot:
    return AccountSnapshot(
        broker="toss",
        account_id="7",
        captured_at=captured_at,
        cash_value=40.0,
        positions=(
            PositionSnapshot("AAPL", 4.0, 10.0, 40.0),
            PositionSnapshot("OLD", 2.0, 10.0, 20.0),
        ),
    )


def construct(book: SignalBook, account: AccountSnapshot | None = None):
    return PortfolioConstructor().construct(
        run_id="run-1",
        source_version="ta-v1",
        stage="shadow",
        as_of_at=DECISION_AT,
        active_batch_id="batch-active",
        signal_book=book,
        snapshot=account or snapshot(),
        expected_account_id="7",
        tracked_symbols={"AAPL", "MSFT"},
    )


class PortfolioConstructorTest(unittest.TestCase):
    def test_optimized_construction_ignores_llm_target_weight_and_preserves_unanalyzed(self):
        low = PortfolioConstructor().construct_optimized(
            run_id="run-1",
            source_version="ta-v1",
            stage="live",
            as_of_at=DECISION_AT,
            active_batch_id="batch-active",
            signal_book=book_for(security("MSFT", "open", 0.01)),
            snapshot=snapshot(),
            expected_account_id="7",
            tracked_symbols={"AAPL", "MSFT"},
        )
        high = PortfolioConstructor().construct_optimized(
            run_id="run-1",
            source_version="ta-v1",
            stage="live",
            as_of_at=DECISION_AT,
            active_batch_id="batch-active",
            signal_book=book_for(security("MSFT", "open", 0.99)),
            snapshot=snapshot(),
            expected_account_id="7",
            tracked_symbols={"AAPL", "MSFT"},
        )
        self.assertEqual(low.weights, high.weights)
        self.assertEqual(low.source_type, "optimizer")
        self.assertFalse(low.metadata["llm_target_weight_used"])
        self.assertEqual(low.metadata["target_weight_source"], "cvxpy_optimizer")
        self.assertAlmostEqual(low.weights["AAPL"], 0.4)
        self.assertAlmostEqual(low.weights["OLD"], 0.2)

    def test_preserves_unanalyzed_holdings_and_opens_only_tracked_symbol(self):
        result = construct(book_for(security("MSFT", "open", 0.1)))
        self.assertEqual(result.metadata["coverage"], "full_portfolio")
        self.assertTrue(result.metadata["execution_eligible"])
        self.assertAlmostEqual(result.weights["AAPL"], 0.4)
        self.assertAlmostEqual(result.weights["OLD"], 0.2)
        self.assertAlmostEqual(result.weights["MSFT"], 0.1)
        self.assertAlmostEqual(result.weights["CASH"], 0.3)
        self.assertEqual(result.metadata["preserved_unanalyzed_symbols"], ["AAPL", "OLD"])

    def test_standard_constructor_cannot_build_paper_or_live_proposals(self):
        with self.assertRaisesRegex(ContractError, "requires construct_optimized"):
            PortfolioConstructor().construct(
                run_id="run-1",
                source_version="ta-v1",
                stage="paper",
                as_of_at=DECISION_AT,
                active_batch_id="batch-active",
                signal_book=book_for(security("MSFT", "open", 0.1)),
                snapshot=snapshot(),
                expected_account_id="7",
                tracked_symbols={"AAPL", "MSFT"},
            )

    def test_only_explicit_exit_sets_existing_position_to_zero(self):
        watch = construct(book_for(security("AAPL", "watch", 0.0)))
        self.assertAlmostEqual(watch.weights["AAPL"], 0.4)
        exited = construct(book_for(security("AAPL", "exit", 0.0)))
        self.assertEqual(exited.weights["AAPL"], 0.0)
        self.assertAlmostEqual(exited.weights["CASH"], 0.8)
        with self.assertRaisesRegex(ContractError, "use an explicit exit"):
            construct(book_for(security("AAPL", "reduce", 0.0)))

    def test_untracked_existing_position_can_reduce_but_cannot_increase(self):
        reduced = construct(book_for(security("OLD", "reduce", 0.1)))
        self.assertAlmostEqual(reduced.weights["OLD"], 0.1)
        self.assertAlmostEqual(reduced.weights["CASH"], 0.5)
        with self.assertRaisesRegex(ContractError, "tracked is false"):
            construct(book_for(security("OLD", "increase", 0.3)))

    def test_untracked_new_position_is_rejected(self):
        with self.assertRaisesRegex(ContractError, "tracked is false"):
            construct(book_for(security("NVDA", "open", 0.1)))

    def test_hold_uses_snapshot_weight_and_never_silently_resizes(self):
        result = construct(book_for(security("AAPL", "hold", 0.9)))
        self.assertAlmostEqual(result.weights["AAPL"], 0.4)
        self.assertAlmostEqual(sum(result.weights.values()), 1.0)

    def test_partial_batch_cannot_become_full_portfolio(self):
        partial = book_for(security("MSFT", "open", 0.1), failed=("AAPL",))
        with self.assertRaisesRegex(ContractError, "partial or failed"):
            construct(partial)

    def test_snapshot_account_and_freshness_are_checked_before_construction(self):
        book = book_for(security("MSFT", "open", 0.1))
        with self.assertRaisesRegex(ContractError, "account does not match"):
            PortfolioConstructor().construct(
                run_id="run-1",
                source_version="ta-v1",
                stage="shadow",
                as_of_at=DECISION_AT,
                active_batch_id="batch-active",
                signal_book=book,
                snapshot=snapshot(),
                expected_account_id="99",
                tracked_symbols={"AAPL", "MSFT"},
            )
        with self.assertRaisesRegex(ContractError, "stale"):
            construct(book, snapshot(captured_at="2026-08-22T11:59:59+00:00"))

    def test_snapshot_must_follow_analysis_and_have_no_open_orders(self):
        book = book_for(security("MSFT", "open", 0.1))
        with self.assertRaisesRegex(ContractError, "captured after"):
            construct(book, snapshot(captured_at="2026-08-22T12:01:59+00:00"))
        with self.assertRaisesRegex(ContractError, "open orders"):
            construct(
                book,
                AccountSnapshot(
                    broker="toss",
                    account_id="7",
                    captured_at="2026-08-22T12:04:00+00:00",
                    cash_value=100.0,
                    open_order_ids=("open-order-1",),
                ),
            )

    def test_overallocated_absolute_targets_fail_instead_of_resizing_holds(self):
        account = AccountSnapshot(
            broker="toss",
            account_id="7",
            captured_at="2026-08-22T12:04:00+00:00",
            cash_value=10.0,
            positions=(PositionSnapshot("AAPL", 9.0, 10.0, 90.0),),
        )
        policy = PortfolioConstructionPolicy(max_snapshot_age_seconds=300)
        with self.assertRaisesRegex(ContractError, "exceed 1"):
            PortfolioConstructor(policy).construct(
                run_id="run-1",
                source_version="ta-v1",
                stage="shadow",
                as_of_at=DECISION_AT,
                active_batch_id="batch-active",
                signal_book=book_for(security("MSFT", "open", 0.2)),
                snapshot=account,
                expected_account_id="7",
                tracked_symbols={"AAPL", "MSFT"},
            )


if __name__ == "__main__":
    unittest.main()
