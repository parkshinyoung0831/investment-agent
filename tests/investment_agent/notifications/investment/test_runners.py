"""자동매매 보고서 러너 — 원장을 거쳐 한 번씩 닿는지 DB·네트워크 없이 검증한다."""
from __future__ import annotations

import unittest
from unittest import mock

from investment_agent.notifications.investment import run_candidates, run_portfolio, run_trades
from tests.investment_agent.notifications.fakes import memory_context

_PORTFOLIO = {
    "proposal": {
        "proposal_id": "proposal_abc", "run_id": "run_abc",
        "as_of_at": "2026-09-03T00:00:00+00:00",
        "weights": {"AAPL": 0.06, "CASH": 0.94}, "confidence": 0.6,
        "reasoning": ["근거"], "case_keys": ["case_a"], "metadata": {},
    },
    "risk": {"risk_decision_id": "risk_abc", "is_approved": True,
             "violations": [], "metrics": {}, "decided_at": "2026-09-03T00:05:00+00:00"},
    "run": {"run_id": "run_abc", "status": "completed",
            "candidate_tickers": ["AAPL"], "failure_reason": None},
}
_CANDIDATE = {
    "case_key": "case_a", "ticker": "AAPL", "as_of_at": "2026-09-03T00:00:00+00:00",
    "status": "completed", "final_decision": {
        "signal": "open", "probability_up": 0.6, "confidence": 0.72,
        "expected_excess_return": 0.03, "target_weight": 0.06,
        "reasoning": ["근거"], "evidence_ids": ["EV-1"], "missing_data": [],
    },
}


def _trade(status: str = "submitted", fills: list | None = None) -> dict:
    return {
        "order": {"client_order_id": "order_1", "intent_id": "intent_1", "approval_id": "approval_1",
                  "ticker": "AAPL", "side": "buy", "quantity": 3, "reference_price": 200.0,
                  "notional": 600.0, "status": status, "submitted_at": "2026-09-03T13:31:00+00:00"},
        "fills": fills or [],
        "execution_mode": "paper",
    }


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.context, self.ledger, self.channel = memory_context()
        for module in (run_portfolio, run_candidates, run_trades):
            patcher = mock.patch.object(module, "load_config", return_value=None)
            patcher.start()
            self.addCleanup(patcher.stop)


class PortfolioRunnerTest(_Base):
    def test_the_latest_proposal_is_reported_once(self):
        with mock.patch.object(run_portfolio.db, "latest_portfolio", return_value=_PORTFOLIO):
            self.assertEqual(run_portfolio.run(target="111", context=self.context), 1)
            self.assertEqual(run_portfolio.run(target="111", context=self.context), 0)
        self.assertEqual(self.channel.created[0]["target"], "111")

    def test_nothing_to_report_sends_nothing(self):
        with mock.patch.object(run_portfolio.db, "latest_portfolio", return_value=None):
            self.assertEqual(run_portfolio.run(target="111", context=self.context), 0)
        self.assertEqual(self.channel.created, [])


class CandidateRunnerTest(_Base):
    def test_each_candidate_gets_its_own_card_once(self):
        second = {**_CANDIDATE, "case_key": "case_b", "ticker": "MSFT"}
        with mock.patch.object(run_candidates.db, "latest_analysis_run_id", return_value="run_1"), \
             mock.patch.object(run_candidates.db, "top_candidates", return_value=[_CANDIDATE, second]):
            self.assertEqual(run_candidates.run(target="111", context=self.context), 2)
            self.assertEqual(run_candidates.run(target="111", context=self.context), 0)

    def test_top_n_limit_is_passed_to_the_query(self):
        queried = mock.Mock(return_value=[])
        with mock.patch.dict("os.environ", {"AI_INVESTOR_REPORT_TOP_N": "3"}, clear=False), \
             mock.patch.object(run_candidates.db, "latest_analysis_run_id", return_value="run_1"), \
             mock.patch.object(run_candidates.db, "top_candidates", queried):
            self.assertEqual(run_candidates.run(target="111", context=self.context), 0)
        self.assertEqual(queried.call_args.kwargs["limit"], 3)


class TradeRunnerTest(_Base):
    def test_an_order_is_one_card_that_is_edited_as_fills_arrive(self):
        filled = [{"quantity": 3, "price": 201.0, "commission": 0.1, "filled_at": "2026-09-03T13:31:05+00:00"}]
        with mock.patch.object(run_trades.db, "recent_orders", return_value=[_trade()]):
            self.assertEqual(run_trades.run(target="222", context=self.context), 1)
        with mock.patch.object(run_trades.db, "recent_orders", return_value=[_trade("filled", filled)]):
            self.assertEqual(run_trades.run(target="222", context=self.context), 1)
            self.assertEqual(run_trades.run(target="222", context=self.context), 0)

        self.assertEqual((len(self.channel.created), len(self.channel.edited)), (1, 1))
        self.assertEqual(self.channel.created[0]["target"], "222")

    def test_quiet_day_sends_nothing(self):
        with mock.patch.object(run_trades.db, "recent_orders", return_value=[]):
            self.assertEqual(run_trades.run(context=self.context), 0)


if __name__ == "__main__":
    unittest.main()
