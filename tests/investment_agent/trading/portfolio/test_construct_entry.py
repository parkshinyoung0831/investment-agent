from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest.mock import patch

from investment_agent.trading.decision.constants import SIGNAL_HORIZON_DAYS
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
        rows = [{"trade_date": origin.isoformat(), "close": value, "volume": 50_000_000}]
        for offset in range(1, 81):
            value *= 1.0 + (0.001 + (offset % 5 - 2) * 0.0002)
            rows.append({"trade_date": (origin + timedelta(days=offset)).isoformat(), "close": value, "volume": 50_000_000})
        return rows


class ConstructPortfolioEntryTest(unittest.TestCase):
    def setUp(self):
        # 실행 원장(로컬 SQLite)의 실제 체결 기록을 읽지 않는다.
        costs = patch("investment_agent.trading.portfolio.construct._filled_order_costs", return_value=[])
        costs.start()
        self.addCleanup(costs.stop)

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
        # 위험은 기대수익과 같은 기간으로 잰다.
        self.assertEqual(covariance["horizon_days"], SIGNAL_HORIZON_DAYS)
        optimizer = proposal["metadata"]["optimizer"]
        self.assertEqual(set(optimizer["trading_costs"]), {"AAPL"})
        self.assertGreater(optimizer["trading_costs"]["AAPL"]["adv_usd"], 0.0)
        self.assertGreaterEqual(optimizer["transaction_cost"], 0.0)


class HorizonContractTest(unittest.TestCase):
    def test_covariance_on_another_horizon_is_rejected(self):
        from investment_agent.trading.contracts import ContractError
        from investment_agent.trading.portfolio.proposals import from_optimized_security_proposals

        proposal = _signal_book().records[0].proposal
        with self.assertRaisesRegex(ContractError, "horizon"):
            from_optimized_security_proposals(
                [proposal], run_id="run", source_version="v", current_weights={"CASH": 1.0},
                case_keys=("case-aapl",), covariance=[[0.01]], covariance_symbols=("AAPL",),
                covariance_metadata={"horizon_days": 5},
            )


class RegimeFailClosedTest(unittest.TestCase):
    """regime 계산만 실패시키고 나머지 시장 입력은 정상으로 둔다 — 다른 fail-closed가 대신 막지 않게."""

    def setUp(self):
        costs = patch("investment_agent.trading.portfolio.construct._filled_order_costs", return_value=[])
        costs.start()
        self.addCleanup(costs.stop)
        from investment_agent.trading.contracts import ContractError

        regime = patch(
            "investment_agent.trading.portfolio.construct.regime_from_benchmark_prices",
            side_effect=ContractError("insufficient benchmark history for a market regime"),
        )
        regime.start()
        self.addCleanup(regime.stop)

    def _run(self, repository, stage):
        with (
            patch("investment_agent.trading.portfolio.construct.resolve_account_seq", return_value=7),
            patch("investment_agent.trading.portfolio.construct.capture_toss_account_snapshot", return_value=_snapshot()),
        ):
            return construct_portfolio(
                batch_id="batch-stable", account_seq=7, as_of_at="2026-08-22T12:03:00+00:00",
                stage=stage, repository=repository,
            )

    def test_trading_stage_stops_when_the_market_regime_is_unknown(self):
        """regime을 모르는 날 평상시 한도로 주문하면 위험 예산이 가장 필요할 때 꺼진다."""
        from investment_agent.trading.contracts import ContractError

        with self.assertRaisesRegex(ContractError, "market regime"):
            self._run(_PricedRepository(), "paper")

    def test_shadow_keeps_observing_without_a_regime(self):
        repository = _PricedRepository()
        outcome = self._run(repository, "shadow")
        self.assertTrue(outcome.persisted)
        proposal = next(row for kind, row in repository.writes if kind == "proposal")
        self.assertIsNone(proposal["metadata"]["market_regime"])


if __name__ == "__main__":
    unittest.main()
