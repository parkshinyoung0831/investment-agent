from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import requests

from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.approval.ledger import LiveExecutionPermit
from investment_agent.execution.safety.control import (
    LiveCancellationPermit,
    LiveTradingControls,
    RuntimeRiskState,
)
from investment_agent.execution.brokers.toss.orders import (
    TossOrderApi,
    TossOrderApiError,
    TossOrderCommand,
    TossOrderModification,
    TossOrderOutcomeUnknown,
    TossOrderRejected,
    TossOrderSnapshot,
    parse_personal_order_event,
)

NOW = datetime(2026, 8, 22, 1, 0, tzinfo=timezone.utc)
PLAN_HASH = "a" * 64


def command(**changes) -> TossOrderCommand:
    values = {
        "client_order_id": "intent1-AAPL-buy",
        "symbol": "AAPL",
        "side": "BUY",
        "order_type": "LIMIT",
        "quantity": "2",
        "limit_price_usd": "101.25",
        "reference_price_usd": "100",
    }
    values.update(changes)
    return TossOrderCommand(**values)


def permit(**changes) -> LiveExecutionPermit:
    values = {
        "approval_id": "approval-1",
        "intent_id": "intent-1",
        "manifest_hash": PLAN_HASH,
        "account_seq": 7,
        "approved_by_user_id": "discord-user",
        "approval_message_id": "discord-message",
        "issued_at": "2026-08-22T00:59:00+00:00",
        "expires_at": "2026-08-22T01:05:00+00:00",
        "allowed_client_order_ids": ("intent1-AAPL-buy",),
    }
    values.update(changes)
    return LiveExecutionPermit(**values)


def controls(**changes) -> LiveTradingControls:
    values = {
        "live_enabled": True,
        "kill_switch_on": False,
        "account_seq": 7,
        "allow_market_orders": False,
    }
    values.update(changes)
    return LiveTradingControls(**values)


def risk_state(**changes) -> RuntimeRiskState:
    values = {
        "submitted_order_count": 0,
        "submitted_notional_usd": 0,
        "realized_pnl_usd": 0,
        "drawdown_fraction": 0,
        "captured_at": "2026-08-22T01:00:00+00:00",
    }
    values.update(changes)
    return RuntimeRiskState(**values)


def remote_order(**changes) -> dict:
    value = {
        "orderId": "broker-order-1",
        "symbol": "AAPL",
        "side": "BUY",
        "orderType": "LIMIT",
        "timeInForce": "DAY",
        "status": "PENDING",
        "price": "101.25",
        "quantity": "2",
        "currency": "USD",
        "orderedAt": "2026-08-22T10:00:00+09:00",
        "execution": {
            "filledQuantity": "0",
            "averageFilledPrice": None,
            "commission": None,
            "tax": None,
        },
    }
    value.update(changes)
    return value


class FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class TossOrderCommandTest(unittest.TestCase):
    def test_official_payload_and_hash_are_deterministic(self):
        order = command()
        self.assertEqual(order.payload()["quantity"], "2")
        self.assertEqual(order.payload()["price"], "101.25")
        self.assertFalse(order.payload()["confirmHighValueOrder"])
        self.assertEqual(len(order.payload_hash), 64)

    def test_fractional_buy_uses_amount_not_quantity(self):
        with self.assertRaises(ExecutionSafetyError):
            command(quantity="0.5")
        amount = command(
            order_type="MARKET", quantity=None, limit_price_usd=None,
            order_amount_usd="50.25",
        )
        self.assertEqual(amount.payload()["orderAmount"], "50.25")

    def test_fractional_market_sell_supports_six_decimals(self):
        order = command(
            side="SELL", order_type="MARKET", quantity="0.123456",
            limit_price_usd=None,
        )
        self.assertEqual(order.payload()["quantity"], "0.123456")
        with self.assertRaises(ExecutionSafetyError):
            command(
                side="SELL", order_type="MARKET", quantity="0.1234567",
                limit_price_usd=None,
            )


class TossOrderApiTest(unittest.TestCase):
    def setUp(self):
        self.state_dir = TemporaryDirectory()
        self.addCleanup(self.state_dir.cleanup)
        self.session = mock.Mock()
        self.api = TossOrderApi(
            token_provider=lambda: "token",
            session=self.session,
            lockdown_state_dir=Path(self.state_dir.name),
        )

    def test_gate_failure_makes_no_network_request(self):
        with self.assertRaises(ExecutionSafetyError):
            self.api.create_order(
                command(), permit=permit(), controls=controls(kill_switch_on=True),
                risk_state=risk_state(), manifest_hash=PLAN_HASH, now=NOW,
            )
        self.session.post.assert_not_called()

    def test_durable_lockdown_in_injected_state_dir_blocks_network(self):
        (Path(self.state_dir.name) / "EXECUTION_LOCKDOWN").write_text(
            "{}", encoding="utf-8"
        )

        with self.assertRaisesRegex(ExecutionSafetyError, "durable lockdown"):
            self.api.create_order(
                command(),
                permit=permit(),
                controls=controls(),
                risk_state=risk_state(),
                manifest_hash=PLAN_HASH,
                now=NOW,
            )

        self.session.post.assert_not_called()

    def test_create_order_requires_matching_approval_and_parses_receipt(self):
        self.session.post.return_value = FakeResponse(
            200,
            {"result": {"orderId": "broker-1", "clientOrderId": "intent1-AAPL-buy"}},
        )
        receipt = self.api.create_order(
            command(), permit=permit(), controls=controls(), risk_state=risk_state(),
            manifest_hash=PLAN_HASH, now=NOW,
        )
        self.assertEqual(receipt.order_id, "broker-1")
        sent = self.session.post.call_args.kwargs["json"]
        self.assertEqual(sent["symbol"], "AAPL")

    def test_timeout_and_5xx_are_unknown_not_retryable_rejections(self):
        self.session.post.side_effect = requests.Timeout("lost response")
        with self.assertRaises(TossOrderOutcomeUnknown):
            self.api.create_order(
                command(), permit=permit(), controls=controls(), risk_state=risk_state(),
                manifest_hash=PLAN_HASH, now=NOW,
            )
        self.assertEqual(self.session.post.call_count, 1)

        self.session.post.reset_mock(side_effect=True)
        self.session.post.return_value = FakeResponse(503, {"error": {"code": "internal"}})
        with self.assertRaises(TossOrderOutcomeUnknown):
            self.api.create_order(
                command(), permit=permit(), controls=controls(), risk_state=risk_state(),
                manifest_hash=PLAN_HASH, now=NOW,
            )

    def test_explicit_4xx_is_rejected(self):
        self.session.post.return_value = FakeResponse(
            422,
            {"error": {"requestId": "r1", "code": "order-hours-closed", "message": "closed"}},
        )
        with self.assertRaises(TossOrderRejected) as caught:
            self.api.create_order(
                command(), permit=permit(), controls=controls(), risk_state=risk_state(),
                manifest_hash=PLAN_HASH, now=NOW,
            )
        self.assertEqual(caught.exception.code, "order-hours-closed")

    def test_list_preserves_unknown_status(self):
        self.session.get.return_value = FakeResponse(
            200,
            {"result": {"orders": [remote_order(status="NEW_FUTURE_STATUS")],
                        "nextCursor": None, "hasNext": False}},
        )
        rows, cursor, has_next = self.api.list_orders(account_seq=7, lifecycle="OPEN")
        self.assertEqual(rows[0].status, "NEW_FUTURE_STATUS")
        self.assertIsNone(cursor)
        self.assertFalse(has_next)

    def test_401_refreshes_once_without_enabling_other_automatic_retries(self):
        refresher = mock.Mock(return_value="new-token")
        api = TossOrderApi(
            token_provider=lambda: "old-token",
            token_refresher=refresher,
            session=self.session,
        )
        self.session.get.side_effect = [
            FakeResponse(401, {"error": {"code": "expired"}}),
            FakeResponse(
                200,
                {"result": {"orders": [], "nextCursor": None, "hasNext": False}},
            ),
        ]

        rows, _cursor, _has_next = api.list_orders(account_seq=7, lifecycle="OPEN")

        self.assertEqual(rows, ())
        self.assertEqual(self.session.get.call_count, 2)
        refresher.assert_called_once_with("old-token")
        first_headers = self.session.get.call_args_list[0].kwargs["headers"]
        second_headers = self.session.get.call_args_list[1].kwargs["headers"]
        self.assertEqual(first_headers["Authorization"], "Bearer old-token")
        self.assertEqual(second_headers["Authorization"], "Bearer new-token")

    def test_modify_requires_a_fresh_covered_approval(self):
        modification = TossOrderModification(
            client_order_id="modify-broker-1", order_type="LIMIT",
            existing_quantity="2", reference_price_usd="100", limit_price_usd="99.5",
        )
        modification_permit = permit(allowed_client_order_ids=("modify-broker-1",))
        self.session.post.return_value = FakeResponse(200, {"result": {"orderId": "replacement"}})
        result = self.api.modify_order(
            account_seq=7, order_id="broker-1", modification=modification,
            permit=modification_permit, controls=controls(), risk_state=risk_state(),
            manifest_hash=PLAN_HASH, now=NOW,
        )
        self.assertEqual(result, "replacement")
        self.assertFalse(self.session.post.call_args.kwargs["json"]["confirmHighValueOrder"])

    def test_order_info_queries_validate_zero_sellable_and_commissions(self):
        self.session.get.side_effect = [
            FakeResponse(200, {"result": {"currency": "USD", "cashBuyingPower": "100.25"}}),
            FakeResponse(200, {"result": {"sellableQuantity": "0"}}),
            FakeResponse(200, {"result": [{"marketCountry": "US", "commissionRate": "0.001",
                                            "startDate": None, "endDate": None}]}),
        ]
        self.assertEqual(str(self.api.buying_power(account_seq=7)), "100.25")
        self.assertEqual(str(self.api.sellable_quantity(account_seq=7, symbol="AAPL")), "0")
        self.assertEqual(str(self.api.commissions(account_seq=7)[0]["commissionRate"]), "0.001")

    def test_cancel_requires_exact_consumed_permit_even_when_kill_switch_on(self):
        cancel_permit = LiveCancellationPermit(
            approval_id="cancel-approval", broker_order_id="broker-1", account_seq=7,
            approved_by_user_id="discord-user", issued_at="2026-08-22T00:59:00+00:00",
            expires_at="2026-08-22T01:05:00+00:00", reason="emergency stop",
        )
        self.session.post.return_value = FakeResponse(200, {"result": {"orderId": "cancel-1"}})
        result = self.api.cancel_order(
            account_seq=7, order_id="broker-1", permit=cancel_permit,
            controls=controls(kill_switch_on=True), now=NOW,
        )
        self.assertEqual(result, "cancel-1")
        with self.assertRaises(ExecutionSafetyError):
            self.api.cancel_order(
                account_seq=7, order_id="other", permit=cancel_permit,
                controls=controls(), now=NOW,
            )


class TossOrderEventTest(unittest.TestCase):
    def test_personal_order_frame_is_account_bound(self):
        event, order = parse_personal_order_event(
            {"type": "message", "topic": "personal:order:7",
             "data": {"event": "FILL", "accountSeq": "7", "order": remote_order()}},
            expected_account_seq=7,
        )
        self.assertEqual(event, "FILL")
        self.assertIsInstance(order, TossOrderSnapshot)
        with self.assertRaises(TossOrderApiError):
            parse_personal_order_event(
                {"type": "message", "topic": "personal:order:8",
                 "data": {"event": "FILL", "accountSeq": "8", "order": remote_order()}},
                expected_account_seq=7,
            )


if __name__ == "__main__":
    unittest.main()
