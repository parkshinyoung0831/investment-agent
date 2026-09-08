from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest.mock import patch

from investment_agent.trading.portfolio.construct import construct_portfolio
from investment_agent.trading.portfolio.contracts import SecurityProposal
from investment_agent.trading.portfolio.signal_book import SignalBatch, SignalBook, SignalRecord
from investment_agent.execution.orders.snapshots import AccountSnapshot


def _signal_book() -> SignalBook:
    proposal = SecurityProposal(
        ticker="AAPL",
        as_of_at="2026-08-22T12:00:00+00:00",
        signal="open",
        probability_up=0.7,
        confidence=0.8,
        expected_excess_return=0.03,
        target_weight=0.1,
        reasoning=("evidence",),
        evidence_ids=("evidence-aapl",),
    )
    batch = SignalBatch(
        batch_id="batch-stable",
        as_of_at="2026-08-22T12:00:00+00:00",
        completed_at="2026-08-22T12:02:00+00:00",
        requested_symbols=("AAPL",),
        successful_symbols=("AAPL",),
        failed_symbols=(),
        model_artifact_id="artifact-1",
    )
    record = SignalRecord(
        batch_id=batch.batch_id,
        proposal=proposal,
        recorded_at="2026-08-22T12:01:00+00:00",
        expires_at="2026-08-22T18:00:00+00:00",
        case_key="case-aapl",
    )
    return SignalBook(batches=(batch,), records=(record,))


def _snapshot() -> AccountSnapshot:
    return AccountSnapshot(
        broker="toss",
        account_id="7",
        captured_at="2026-08-22T12:04:00+00:00",
        cash_value=100.0,
    )


class _Repository:
    def __init__(self):
        self.writes = []
        self.loaded_as_of = None

    def latest_signal_batch_id(self, *, as_of_at):
        raise AssertionError("an explicit batch_id must not fall back to latest")

    def load_signal_book(self, *, as_of_at):
        self.loaded_as_of = as_of_at
        return _signal_book()

    def current_tracked_tickers(self):
        return ["AAPL"]

    def sp500_sector_map(self, tickers):
        return {"AAPL": "Technology"}

    def save_policy(self, row):
        self.writes.append(("policy", row))

    def save_portfolio_snapshot(self, snapshot):
        self.writes.append(("snapshot", snapshot.snapshot_id))
        return "execution_snapshot_1"

    def save_decision_run(self, row):
        self.writes.append(("run", row))

    def save_portfolio_proposal(self, row):
        self.writes.append(("proposal", row))

    def save_risk_decision(self, row):
        self.writes.append(("risk", row))

    def save_portfolio_decision(self, row):
        self.writes.append(("decision", row))

    def finish_decision_run(self, run_id, *, status):
        self.writes.append(("finish", {"run_id": run_id, "status": status}))


class _PricedRepository(_Repository):
    def has_approved_promotion(self, artifact_id, stage):
        return artifact_id == "artifact-1" and stage == "paper"

    def market_prices(self, ticker, as_of_at, limit=260):
        value = 100.0
        origin = date(2026, 5, 1)
        rows = [{"trade_date": origin.isoformat(), "close": value}]
        for offset in range(1, 81):
            value *= 1.0 + (0.001 + (offset % 5 - 2) * 0.0002)
            rows.append({"trade_date": (origin + timedelta(days=offset)).isoformat(), "close": value})
        return rows


class ConstructPortfolioEntryTest(unittest.TestCase):
    def test_returns_stable_ids_without_ops_raw_query(self):
        repository = _Repository()
        with (
            patch(
                "investment_agent.trading.portfolio.construct.resolve_account_seq",
                return_value=7,
            ),
            patch(
                "investment_agent.trading.portfolio.construct.capture_toss_account_snapshot",
                return_value=_snapshot(),
            ),
        ):
            outcome = construct_portfolio(
                batch_id="batch-stable",
                account_seq=7,
                as_of_at="2026-08-22T12:03:00+00:00",
                repository=repository,
            )
        self.assertEqual(outcome.active_batch_id, "batch-stable")
        self.assertTrue(outcome.run_id.startswith("portfolio_run_"))
        self.assertTrue(outcome.proposal_id.startswith("proposal_"))
        self.assertTrue(outcome.risk_decision_id.startswith("risk_"))
        self.assertTrue(outcome.is_approved)
        self.assertTrue(outcome.persisted)
        self.assertEqual(outcome.account_snapshot_id, "execution_snapshot_1")
        self.assertEqual(repository.loaded_as_of.isoformat(), "2026-08-22T12:03:00+00:00")
        decision = next(row for kind, row in repository.writes if kind == "decision")
        self.assertEqual(decision["run_id"], outcome.run_id)
        self.assertEqual(decision["proposal_id"], outcome.proposal_id)
        self.assertEqual(decision["risk_decision_id"], outcome.risk_decision_id)
        self.assertEqual(decision["champion_policy"]["source_type"], "optimizer")
        proposal = next(row for kind, row in repository.writes if kind == "proposal")
        self.assertEqual(proposal["account_snapshot_id"], "execution_snapshot_1")

    def test_dry_run_returns_ids_but_performs_no_writes(self):
        repository = _Repository()
        with (
            patch(
                "investment_agent.trading.portfolio.construct.resolve_account_seq",
                return_value=7,
            ),
            patch(
                "investment_agent.trading.portfolio.construct.capture_toss_account_snapshot",
                return_value=_snapshot(),
            ),
        ):
            outcome = construct_portfolio(
                batch_id="batch-stable",
                account_seq=7,
                as_of_at="2026-08-22T12:03:00+00:00",
                dry_run=True,
                repository=repository,
            )
        self.assertTrue(outcome.is_approved)
        self.assertFalse(outcome.persisted)
        self.assertFalse(repository.writes)

    def test_paper_stage_receives_calculated_market_risk_inputs(self):
        repository = _PricedRepository()
        with (
            patch(
                "investment_agent.trading.portfolio.construct.resolve_account_seq",
                return_value=7,
            ),
            patch(
                "investment_agent.trading.portfolio.construct.capture_toss_account_snapshot",
                return_value=_snapshot(),
            ),
        ):
            outcome = construct_portfolio(
                batch_id="batch-stable",
                account_seq=7,
                as_of_at="2026-08-22T12:03:00+00:00",
                stage="paper",
                repository=repository,
            )
        self.assertTrue(outcome.is_approved)
        policy = next(row for kind, row in repository.writes if kind == "policy")
        self.assertEqual(policy["stage"], "paper")
        proposal = next(row for kind, row in repository.writes if kind == "proposal")
        covariance = proposal["metadata"]["optimizer"]["covariance"]
        self.assertEqual(covariance["method"], "sample_covariance")
        self.assertEqual(covariance["symbols"], ["AAPL"])


if __name__ == "__main__":
    unittest.main()
