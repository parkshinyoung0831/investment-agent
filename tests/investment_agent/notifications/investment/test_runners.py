"""자동매매 보고서 러너 — v1 outbox 등록·디스패치 경계를 DB 없이 검증한다."""
from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest import mock

from investment_agent.notifications.investment import run_candidates, run_portfolio, run_trades

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
_TRADE = {
    "order": {"client_order_id": "order_1", "intent_id": "intent_1", "approval_id": "approval_1",
              "ticker": "AAPL", "side": "buy", "quantity": 3, "reference_price": 200.0,
              "notional": 600.0, "status": "filled", "submitted_at": "2026-09-03T13:31:00+00:00"},
    "fills": [{"quantity": 3, "price": 201.0, "commission": 0.1,
               "filled_at": "2026-09-03T13:31:05+00:00"}],
    "execution_mode": "paper",
}
_ENV = {"DISCORD_CHANNEL_AI_REPORTS": "111", "DISCORD_CHANNEL_AI_TRADES": "222"}


def _service(*, statuses=("sent",)):
    service = mock.Mock()
    keys: list[str] = []
    service.enqueue.side_effect = lambda **kwargs: (
        keys.append(kwargs["notification_key"]), SimpleNamespace(status="enqueued")
    )[1]
    service.run_pending.side_effect = lambda: [
        SimpleNamespace(producer="ai_investor", notification_key=keys[-1], status=status)
        for status in statuses
    ] if keys else []
    service._keys = keys
    return service


class PortfolioRunnerTest(unittest.TestCase):
    def test_sends_one_card_for_the_latest_proposal(self):
        service = _service()
        with mock.patch.dict("os.environ", _ENV, clear=False), \
             mock.patch.object(run_portfolio.db, "latest_portfolio", return_value=_PORTFOLIO):
            self.assertEqual(run_portfolio.run(service=service, target="111"), 1)
        self.assertEqual(service.enqueue.call_args.kwargs["notification_key"], "portfolio:proposal_abc")
        self.assertEqual(service.enqueue.call_args.kwargs["target"], "111")

    def test_nothing_to_report_sends_nothing(self):
        service = _service()
        with mock.patch.object(run_portfolio.db, "latest_portfolio", return_value=None):
            self.assertEqual(run_portfolio.run(service=service, target="111"), 0)
        service.enqueue.assert_not_called()

    def test_duplicate_outbox_item_is_not_counted_as_new_send(self):
        service = _service(statuses=("skipped",))
        service.enqueue.side_effect = lambda **kwargs: (
            service._keys.append(kwargs["notification_key"]), SimpleNamespace(status="duplicate")
        )[1]
        with mock.patch.dict("os.environ", _ENV, clear=False), \
             mock.patch.object(run_portfolio.db, "latest_portfolio", return_value=_PORTFOLIO):
            self.assertEqual(run_portfolio.run(service=service, target="111"), 0)

    def test_dispatch_failure_is_propagated_for_operations_alerting(self):
        service = _service()
        service.run_pending.side_effect = RuntimeError("dispatch failed")
        with mock.patch.dict("os.environ", _ENV, clear=False), \
             mock.patch.object(run_portfolio.db, "latest_portfolio", return_value=_PORTFOLIO), \
             self.assertRaises(RuntimeError):
            run_portfolio.run(service=service, target="111")


class CandidateRunnerTest(unittest.TestCase):
    def test_each_candidate_gets_its_own_outbox_snapshot(self):
        second = {**_CANDIDATE, "case_key": "case_b", "ticker": "MSFT"}
        service = _service()
        with mock.patch.dict("os.environ", _ENV, clear=False), \
             mock.patch.object(run_candidates.db, "latest_portfolio", return_value=_PORTFOLIO), \
             mock.patch.object(run_candidates.db, "top_candidates", return_value=[_CANDIDATE, second]):
            self.assertEqual(run_candidates.run(service=service, target="111"), 2)
        keys = [call.kwargs["notification_key"] for call in service.enqueue.call_args_list]
        self.assertEqual(keys, ["candidate:case_a", "candidate:case_b"])

    def test_top_n_limit_is_passed_to_the_query(self):
        service = _service()
        queried = mock.Mock(return_value=[])
        with mock.patch.dict("os.environ", {**_ENV, "AI_INVESTOR_REPORT_TOP_N": "3"}, clear=False), \
             mock.patch.object(run_candidates.db, "latest_portfolio", return_value=_PORTFOLIO), \
             mock.patch.object(run_candidates.db, "top_candidates", queried):
            self.assertEqual(run_candidates.run(service=service, target="111"), 0)
        self.assertEqual(queried.call_args.kwargs["limit"], 3)

    def test_no_run_to_report_sends_nothing(self):
        service = _service()
        with mock.patch.object(run_candidates.db, "latest_portfolio", return_value=None):
            self.assertEqual(run_candidates.run(service=service), 0)
        service.enqueue.assert_not_called()


class TradeRunnerTest(unittest.TestCase):
    def test_each_order_gets_one_card_in_the_trade_channel(self):
        service = _service()
        with mock.patch.dict("os.environ", _ENV, clear=False), \
             mock.patch.object(run_trades.db, "recent_orders", return_value=[_TRADE]):
            self.assertEqual(run_trades.run(service=service, target="222"), 1)
        call = service.enqueue.call_args
        self.assertEqual(call.kwargs["notification_key"], "trade:order_1")
        self.assertEqual(call.kwargs["target"], "222")

    def test_quiet_day_sends_nothing(self):
        service = _service()
        with mock.patch.object(run_trades.db, "recent_orders", return_value=[]):
            self.assertEqual(run_trades.run(service=service), 0)
        service.enqueue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
