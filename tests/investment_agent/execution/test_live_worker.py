from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from investment_agent.execution.orders.intents import ExecutionIntent
from investment_agent.execution.approval.ledger import ApprovalRequest
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.safety.control import (
    LiveTradingControls,
    ORDER_RISK_INCREASING,
    ORDER_RISK_REDUCING,
    TRADING_STATE_ACTIVE,
    TRADING_STATE_HALTED,
    TRADING_STATE_REDUCING,
    RuntimeRiskState,
    assert_live_order_allowed,
    classify_order_risk,
    resolve_trading_state,
)
from investment_agent.execution.orders.live_worker import (
    LiveExecutionPolicy,
    TossLiveExecutionWorker,
    commands_from_handoff,
    guarded_limit_price,
)
from investment_agent.execution.orders.ledger import OrderAttemptReservation
from investment_agent.execution.orders.planning import (
    FUNDING_PHASE_FULL,
    FUNDING_PHASE_SELLS,
    ExecutionLimits,
    TargetWeightOrderPlanner,
    plan_with_funding,
)
from investment_agent.execution.brokers.toss.client import TossUsRegularSession
from investment_agent.execution.brokers.toss.orders import (
    TossOrderOutcomeUnknown,
    TossOrderReceipt,
)
from investment_agent.execution.orders.toss_manual import (
    TossManualHandoff,
    TossManualSnapshot,
    TossManualTicket,
)

NOW = datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc)  # 월요일 11:00 EDT
ACCOUNT = 7
ORDER_ID = "aix_" + hashlib.sha256(
    b"intent-live-worker|AAPL|buy|5.000000"
).hexdigest()[:20]


def intent() -> ExecutionIntent:
    return ExecutionIntent(
        intent_id="intent-live-worker",
        risk_decision_id="risk-live-worker",
        proposal_id="proposal-live-worker",
        execution_mode="live",
        target_weights={"AAPL": 0.1, "CASH": 0.9},
        input_hash=hashlib.sha256(b"live-worker").hexdigest(),
        not_before=(NOW - timedelta(minutes=5)).isoformat(),
        expires_at=(NOW + timedelta(minutes=30)).isoformat(),
    )


def snapshot(*, price: float = 200.0, cash: float = 10_000.0) -> TossManualSnapshot:
    return TossManualSnapshot(
        captured_at=NOW.isoformat(),
        currency="USD",
        portfolio_value=cash,
        cash_buying_power=cash,
        current_quantities={},
        prices={"AAPL": price},
        price_timestamps={"AAPL": NOW.isoformat()},
    )


def handoff() -> TossManualHandoff:
    value = TossManualHandoff(
        intent_id=intent().intent_id,
        account_seq=ACCOUNT,
        contract_version="toss-manual-v1",
        snapshot=snapshot(),
        tickets=(TossManualTicket(
            intent_id=intent().intent_id,
            client_order_id=ORDER_ID,
            expires_at=intent().expires_at,
            symbol="AAPL",
            side="buy",
            current_quantity=0,
            target_weight=0.1,
            target_quantity=5,
            order_quantity=5,
            reference_price=200,
            price_timestamp=NOW.isoformat(),
            estimated_notional=1_000,
        ),),
        manifest_hash="0" * 64,
    )
    return replace(value, manifest_hash=value.recomputed_manifest_hash())


def two_order_intent() -> ExecutionIntent:
    return replace(
        intent(),
        target_weights={"AAPL": 0.1, "MSFT": 0.1, "CASH": 0.8},
        input_hash=hashlib.sha256(b"live-worker-two-orders").hexdigest(),
    )


def two_order_snapshot() -> TossManualSnapshot:
    return TossManualSnapshot(
        captured_at=NOW.isoformat(),
        currency="USD",
        portfolio_value=10_000,
        cash_buying_power=10_000,
        current_quantities={},
        prices={"AAPL": 200, "MSFT": 100},
        price_timestamps={"AAPL": NOW.isoformat(), "MSFT": NOW.isoformat()},
    )


def two_order_handoff() -> TossManualHandoff:
    second_id = "aix_" + hashlib.sha256(
        b"intent-live-worker|MSFT|buy|10.000000"
    ).hexdigest()[:20]
    value = TossManualHandoff(
        intent_id=intent().intent_id,
        account_seq=ACCOUNT,
        contract_version="toss-manual-v1",
        snapshot=two_order_snapshot(),
        tickets=(
            TossManualTicket(
                intent_id=intent().intent_id,
                client_order_id=ORDER_ID,
                expires_at=intent().expires_at,
                symbol="AAPL",
                side="buy",
                current_quantity=0,
                target_weight=0.1,
                target_quantity=5,
                order_quantity=5,
                reference_price=200,
                price_timestamp=NOW.isoformat(),
                estimated_notional=1_000,
            ),
            TossManualTicket(
                intent_id=intent().intent_id,
                client_order_id=second_id,
                expires_at=intent().expires_at,
                symbol="MSFT",
                side="buy",
                current_quantity=0,
                target_weight=0.1,
                target_quantity=10,
                order_quantity=10,
                reference_price=100,
                price_timestamp=NOW.isoformat(),
                estimated_notional=1_000,
            ),
        ),
        manifest_hash="0" * 64,
    )
    return replace(value, manifest_hash=value.recomputed_manifest_hash())


def approval() -> ApprovalRequest:
    pending = ApprovalRequest.create(
        intent_id=intent().intent_id,
        proposal_id=intent().proposal_id,
        risk_decision_id=intent().risk_decision_id,
        execution_mode="live",
        proposal_hash="a" * 64,
        risk_hash="b" * 64,
        manifest_hash=handoff().manifest_hash,
        account_seq=ACCOUNT,
        allowed_client_order_ids=(ORDER_ID,),
        discord_guild_id="1510267057885941840",
        discord_channel_id="1540628419094642699",
        allowed_approver_user_ids=("1537373837350404146",),
        requested_at=NOW - timedelta(minutes=1),
        latest_expiry=intent().expires_at,
    )
    return replace(
        pending,
        status="approved",
        decision="approved",
        discord_message_id="1540628999999999999",
        decided_at=(NOW - timedelta(seconds=10)).isoformat(),
        decided_by_user_id="1537373837350404146",
    )


class FakeRepository:
    def __init__(self, *, value_intent=None, value_handoff=None):
        self.intent = value_intent or intent()
        self.handoff = value_handoff or handoff()
        self.approval = replace(
            approval(),
            manifest_hash=self.handoff.manifest_hash,
            allowed_client_order_ids=tuple(
                ticket.client_order_id for ticket in self.handoff.tickets
            ),
        )
        self.trace: list[str] = []
        self.events = []
        self.orders = {}
        self.unresolved = []
        self.risk_override = None

    def load_approval(self, approval_id):
        return self.approval if approval_id == self.approval.approval_id else None

    def load_intent(self, intent_id):
        return self.intent if intent_id == self.intent.intent_id else None

    def load_handoff(self, manifest_hash):
        return self.handoff if manifest_hash == self.handoff.manifest_hash else None

    def current_tracked_tickers(self):
        return {ticket.symbol for ticket in self.handoff.tickets}

    def unresolved_orders(self, *, account_seq):
        return list(self.unresolved)

    def consume_approval(self, approval_id, *, manifest_hash):
        self.trace.append("consume")
        if self.approval.status != "approved" or manifest_hash != self.approval.manifest_hash:
            return None
        self.approval = replace(
            self.approval,
            status="consumed",
            consumed_at=NOW.isoformat(),
        )
        return self.approval

    def create_planned_order(self, row):
        self.trace.append("plan")
        self.orders[row["client_order_id"]] = dict(row)

    def reserve_order_attempt(self, attempt):
        self.trace.append("reserve")
        return OrderAttemptReservation(attempt=attempt, reserved_new=True)

    def attach_order_attempt(self, client_order_id, attempt_id):
        self.trace.append("attach")
        self.orders[client_order_id]["attempt_id"] = attempt_id

    def append_order_attempt_event(self, attempt_id, **kwargs):
        self.trace.append(f"event:{kwargs['status']}")
        self.events.append((attempt_id, kwargs))
        return object()

    def update_order_execution(self, client_order_id, **kwargs):
        self.trace.append(f"order:{kwargs['status']}")
        self.orders[client_order_id].update(kwargs)

    def update_intent_status(
        self,
        intent_id,
        status,
        failure_reason=None,
        *,
        expected_status=None,
    ):
        self.trace.append(f"intent:{status}")
        if expected_status is not None and self.intent.status != expected_status:
            return
        self.intent = replace(self.intent, status=status)

    def runtime_risk_state(self, **kwargs):
        self.trace.append("risk")
        if self.risk_override is not None:
            return self.risk_override
        return RuntimeRiskState(
            submitted_order_count=0,
            submitted_notional_usd=0,
            realized_pnl_usd=0,
            drawdown_fraction=0,
            captured_at=NOW.isoformat(),
        )


class FakeApi:
    def __init__(
        self,
        *,
        buying_power: Decimal = Decimal(2000),
        unknown=False,
        enforce_safety=False,
        after_post=None,
        lockdown_state_dir=None,
    ):
        self.buying_power_value = buying_power
        self.unknown = unknown
        self.enforce_safety = enforce_safety
        self.after_post = after_post
        self.lockdown_state_dir = lockdown_state_dir
        self.posts = 0
        self.checked_at = []

    def sellable_quantity(self, *, account_seq, symbol):
        return Decimal(999)

    def commissions(self, *, account_seq):
        return ({"marketCountry": "US", "commissionRate": Decimal("0.001")},)

    def buying_power(self, *, account_seq, currency):
        return self.buying_power_value

    def create_order(self, command, **kwargs):
        self.checked_at.append(kwargs["now"])
        if self.enforce_safety:
            assert_live_order_allowed(
                permit=kwargs["permit"],
                controls=kwargs["controls"],
                state=kwargs["risk_state"],
                order=command,
                manifest_hash=kwargs["manifest_hash"],
                now=kwargs["now"],
                lockdown_state_dir=self.lockdown_state_dir,
            )
        self.posts += 1
        if self.after_post is not None:
            self.after_post(self.posts)
        if self.unknown:
            raise TossOrderOutcomeUnknown(
                client_order_id=command.client_order_id,
                reason="timeout",
            )
        return TossOrderReceipt(
            order_id="broker-live-1",
            client_order_id=command.client_order_id,
            payload_hash=command.payload_hash,
            raw_response={"orderId": "broker-live-1", "clientOrderId": command.client_order_id},
        )


def worker(repository, api, *, fresh=None):
    controls = LiveTradingControls(
        live_enabled=True,
        kill_switch_on=False,
        account_seq=ACCOUNT,
        max_order_notional_usd=5_000,
        max_daily_notional_usd=20_000,
        max_daily_orders=20,
        max_daily_loss_usd=500,
        max_drawdown_fraction=0.05,
        allow_market_orders=False,
    )
    planner = TargetWeightOrderPlanner(ExecutionLimits(
        min_order_notional=10,
        max_order_notional=5_000,
        max_total_notional=20_000,
        quantity_decimals=0,
    ))
    return TossLiveExecutionWorker(
        repository=repository,
        api=api,
        controls=controls,
        planner=planner,
        policy=LiveExecutionPolicy(),
        snapshot_provider=lambda *args, **kwargs: fresh or snapshot(),
        session_provider=lambda market_date: TossUsRegularSession(
            market_date=market_date,
            start_at=NOW - timedelta(hours=1),
            end_at=NOW + timedelta(hours=5),
        ),
    )


class LiveWorkerTest(unittest.TestCase):
    def test_exhausted_daily_budget_does_not_consume_approval(self):
        for limits in ({"max_daily_orders": 0}, {"max_daily_notional_usd": 500}):
            with self.subTest(limits=limits):
                repository, api = FakeRepository(), FakeApi()
                subject = worker(repository, api)
                # 유효한 운영 한도와 이미 사용한 일일 예산의 조합을 만든다.
                if "max_daily_orders" in limits:
                    original = repository.runtime_risk_state
                    repository.runtime_risk_state = lambda **kw: replace(original(**kw), submitted_order_count=20)
                else:
                    subject.controls = replace(subject.controls, **limits)
                with self.assertRaisesRegex(ExecutionSafetyError, "daily"):
                    subject.execute(repository.approval.approval_id, now=NOW)
                self.assertNotIn("consume", repository.trace)
                self.assertEqual(api.posts, 0)

    def test_approved_plan_reserves_before_exactly_one_post(self):
        repository = FakeRepository()
        api = FakeApi()
        result = worker(repository, api).execute(repository.approval.approval_id, now=NOW)
        self.assertEqual(result.status, "reconciling")
        self.assertEqual(api.posts, 1)
        self.assertLess(repository.trace.index("reserve"), repository.trace.index("event:submitting"))
        self.assertLess(repository.trace.index("event:submitting"), repository.trace.index("event:submitted"))
        self.assertIn("order:submitted", repository.trace)

    def test_changed_order_quantity_requires_new_approval_before_consumption(self):
        repository = FakeRepository()
        api = FakeApi()
        # 가격 변화는 허용 범위 안이지만 목표 whole-share 수량을 5 -> 4로 바꾼다.
        changed = snapshot(price=201.0)
        with self.assertRaisesRegex(ExecutionSafetyError, "reapproval required"):
            worker(repository, api, fresh=changed).execute(
                repository.approval.approval_id, now=NOW,
            )
        self.assertEqual(api.posts, 0)
        self.assertNotIn("consume", repository.trace)

    def test_changed_holdings_require_new_approval_before_consumption(self):
        repository = FakeRepository()
        api = FakeApi()
        changed = replace(snapshot(), current_quantities={"AAPL": 1.0})
        with self.assertRaisesRegex(ExecutionSafetyError, "reapproval required"):
            worker(repository, api, fresh=changed).execute(
                repository.approval.approval_id,
                now=NOW,
            )
        self.assertEqual(api.posts, 0)
        self.assertNotIn("consume", repository.trace)

    def test_price_drift_blocks_even_when_whole_share_quantity_is_unchanged(self):
        repository = FakeRepository()
        api = FakeApi()
        changed = TossManualSnapshot(
            captured_at=NOW.isoformat(),
            currency="USD",
            portfolio_value=10_150,
            cash_buying_power=10_150,
            current_quantities={},
            prices={"AAPL": 203.0},
            price_timestamps={"AAPL": NOW.isoformat()},
        )
        with self.assertRaisesRegex(ExecutionSafetyError, "price drift"):
            worker(repository, api, fresh=changed).execute(
                repository.approval.approval_id,
                now=NOW,
            )
        self.assertEqual(api.posts, 0)
        self.assertNotIn("consume", repository.trace)

    def test_insufficient_cash_does_not_consume_approval(self):
        repository = FakeRepository()
        api = FakeApi(buying_power=Decimal(100))
        with self.assertRaisesRegex(ExecutionSafetyError, "cannot fund"):
            worker(repository, api).execute(repository.approval.approval_id, now=NOW)
        self.assertEqual(api.posts, 0)
        self.assertNotIn("consume", repository.trace)

    def test_timeout_is_recorded_unknown_and_never_retried(self):
        repository = FakeRepository()
        api = FakeApi(buying_power=Decimal(3000), unknown=True)
        with self.assertRaises(TossOrderOutcomeUnknown):
            worker(repository, api).execute(repository.approval.approval_id, now=NOW)
        self.assertEqual(api.posts, 1)
        self.assertIn("event:outcome_unknown", repository.trace)
        self.assertIn("order:outcome_unknown", repository.trace)

    def test_timeout_closes_later_reserved_orders_without_submitting_them(self):
        repository = FakeRepository(
            value_intent=two_order_intent(),
            value_handoff=two_order_handoff(),
        )
        api = FakeApi(buying_power=Decimal(3000), unknown=True)
        with self.assertRaises(TossOrderOutcomeUnknown):
            worker(repository, api, fresh=two_order_snapshot()).execute(
                repository.approval.approval_id,
                now=NOW,
            )
        self.assertEqual(api.posts, 1)
        second_id = repository.handoff.tickets[1].client_order_id
        self.assertEqual(repository.orders[second_id]["status"], "failed")
        failed_events = [
            value for _attempt_id, value in repository.events
            if value["status"] == "failed"
        ]
        self.assertEqual(len(failed_events), 1)
        self.assertEqual(
            failed_events[0]["raw_response"]["reason"],
            "prior_order_outcome_unknown",
        )

    def test_later_order_rechecks_real_time_and_stops_after_permit_expiry(self):
        repository = FakeRepository(
            value_intent=two_order_intent(),
            value_handoff=two_order_handoff(),
        )
        with TemporaryDirectory() as state_dir:
            api = FakeApi(
                buying_power=Decimal(3000),
                enforce_safety=True,
                lockdown_state_dir=Path(state_dir),
            )
            instance = worker(repository, api, fresh=two_order_snapshot())
            times = iter((NOW, NOW, NOW + timedelta(minutes=3)))
            instance.clock = lambda: next(times)

            with self.assertRaisesRegex(ExecutionSafetyError, "permit"):
                instance.execute(repository.approval.approval_id)

        self.assertEqual(api.posts, 1)
        self.assertEqual(api.checked_at, [NOW, NOW + timedelta(minutes=3)])
        second_id = repository.handoff.tickets[1].client_order_id
        self.assertEqual(repository.orders[second_id]["status"], "failed")
        self.assertIn("event:failed", repository.trace)

    def test_submission_does_not_refresh_unobserved_risk_state(self):
        repository = FakeRepository(
            value_intent=two_order_intent(), value_handoff=two_order_handoff(),
        )
        with TemporaryDirectory() as state_dir:
            api = FakeApi(buying_power=Decimal(3000), enforce_safety=True,
                          lockdown_state_dir=Path(state_dir))
            instance = worker(repository, api, fresh=two_order_snapshot())
            times = iter((NOW, NOW + timedelta(seconds=20), NOW + timedelta(seconds=40)))
            instance.clock = lambda: next(times)
            with self.assertRaisesRegex(ExecutionSafetyError, "runtime risk state is stale"):
                instance.execute(repository.approval.approval_id)
        self.assertEqual(api.posts, 1)
        second_id = repository.handoff.tickets[1].client_order_id
        self.assertEqual(repository.orders[second_id]["status"], "failed")

    def test_intent_cancelled_after_first_order_blocks_the_second(self):
        repository = FakeRepository(
            value_intent=two_order_intent(),
            value_handoff=two_order_handoff(),
        )

        def cancel_after_first(post_count):
            if post_count == 1:
                repository.intent = replace(repository.intent, status="cancelled")

        api = FakeApi(
            buying_power=Decimal(3000),
            after_post=cancel_after_first,
        )
        with self.assertRaisesRegex(ExecutionSafetyError, "changed or was cancelled"):
            worker(repository, api, fresh=two_order_snapshot()).execute(
                repository.approval.approval_id,
                now=NOW,
            )
        self.assertEqual(api.posts, 1)
        second_id = repository.handoff.tickets[1].client_order_id
        self.assertEqual(repository.orders[second_id]["status"], "failed")
        self.assertEqual(repository.intent.status, "cancelled")

    def test_kill_switch_blocks_before_reads_consumption_or_submission(self):
        repository = FakeRepository()
        api = FakeApi()
        instance = worker(repository, api)
        instance.controls = replace(instance.controls, kill_switch_on=True)

        with self.assertRaisesRegex(ExecutionSafetyError, "kill switch"):
            instance.execute(repository.approval.approval_id, now=NOW)

        self.assertEqual(repository.trace, [])
        self.assertEqual(api.posts, 0)

    def test_limit_band_and_rounding_never_cross_the_guard(self):
        self.assertEqual(guarded_limit_price(100, side="buy", band_bps=25), Decimal("100.25"))
        self.assertEqual(guarded_limit_price(100, side="sell", band_bps=25), Decimal("99.75"))
        command = commands_from_handoff(handoff(), policy=LiveExecutionPolicy())[0]
        self.assertEqual(command.order_type, "LIMIT")
        self.assertEqual(command.quantity, Decimal(5))

    def test_outside_guarded_session_fails_without_reads_or_posts(self):
        repository = FakeRepository()
        api = FakeApi()
        outside = datetime(2026, 8, 24, 20, 30, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ExecutionSafetyError, "outside"):
            worker(repository, api).execute(repository.approval.approval_id, now=outside)
        self.assertEqual(api.posts, 0)

    def test_official_holiday_fails_before_account_or_order_reads(self):
        repository = FakeRepository()
        api = FakeApi()
        instance = worker(repository, api)
        instance.session_provider = lambda _market_date: None
        with self.assertRaisesRegex(ExecutionSafetyError, "market is closed"):
            instance.execute(repository.approval.approval_id, now=NOW)
        self.assertEqual(repository.trace, [])
        self.assertEqual(api.posts, 0)


def rotation_intent() -> ExecutionIntent:
    """AAPL 전량 매도 후 MSFT로 갈아타는 목표. 현재 현금만으로는 MSFT를 못 산다."""
    return replace(
        intent(),
        target_weights={"AAPL": 0.0, "MSFT": 0.5, "CASH": 0.5},
        input_hash=hashlib.sha256(b"live-worker-rotation").hexdigest(),
    )


def rotation_snapshot(*, cash: float = 500.0) -> TossManualSnapshot:
    return TossManualSnapshot(
        captured_at=NOW.isoformat(),
        currency="USD",
        portfolio_value=cash + 20 * 200.0,
        cash_buying_power=cash,
        current_quantities={"AAPL": 20.0},
        prices={"AAPL": 200.0, "MSFT": 100.0},
        price_timestamps={"AAPL": NOW.isoformat(), "MSFT": NOW.isoformat()},
    )


def rotation_planner() -> TargetWeightOrderPlanner:
    return TargetWeightOrderPlanner(ExecutionLimits(
        min_order_notional=10, max_order_notional=5_000, max_total_notional=20_000, quantity_decimals=0,
    ))


def funding_handoff() -> TossManualHandoff:
    plans, phase = plan_with_funding(
        rotation_planner(), rotation_intent(),
        portfolio_value=rotation_snapshot().portfolio_value,
        current_quantities=rotation_snapshot().current_quantities,
        prices=rotation_snapshot().prices,
        available_cash=rotation_snapshot().cash_buying_power,
        eligible_buy_symbols={"AAPL", "MSFT"}, required_mode="live", now=NOW,
    )
    value = TossManualHandoff(
        intent_id=intent().intent_id,
        account_seq=ACCOUNT,
        contract_version="toss-manual-v1",
        snapshot=rotation_snapshot(),
        tickets=tuple(
            TossManualTicket(
                intent_id=intent().intent_id, client_order_id=plan.client_order_id,
                expires_at=intent().expires_at, symbol=plan.symbol, side=plan.side,
                current_quantity=rotation_snapshot().current_quantities.get(plan.symbol, 0.0),
                target_weight=rotation_intent().target_weights[plan.symbol], target_quantity=0.0,
                order_quantity=plan.quantity, reference_price=plan.reference_price,
                price_timestamp=NOW.isoformat(), estimated_notional=plan.notional,
            )
            for plan in plans
        ),
        manifest_hash="0" * 64,
        funding_phase=phase,
    )
    return replace(value, manifest_hash=value.recomputed_manifest_hash())


class FundingPhaseTest(unittest.TestCase):
    def test_short_cash_turns_the_plan_into_sells_only(self):
        handoff_value = funding_handoff()
        self.assertEqual(handoff_value.funding_phase, FUNDING_PHASE_SELLS)
        self.assertEqual([(t.symbol, t.side) for t in handoff_value.tickets], [("AAPL", "sell")])

    def test_enough_cash_keeps_sells_and_buys_together(self):
        snap = rotation_snapshot(cash=5_000.0)
        plans, phase = plan_with_funding(
            rotation_planner(), rotation_intent(),
            portfolio_value=snap.portfolio_value, current_quantities=snap.current_quantities,
            prices=snap.prices, available_cash=snap.cash_buying_power,
            eligible_buy_symbols={"AAPL", "MSFT"}, required_mode="live", now=NOW,
        )
        self.assertEqual(phase, FUNDING_PHASE_FULL)
        self.assertEqual([plan.side for plan in plans], ["sell", "buy"])

    def test_unfundable_buys_with_nothing_to_sell_fail_closed(self):
        with self.assertRaisesRegex(ExecutionSafetyError, "nothing to sell first"):
            plan_with_funding(
                rotation_planner(), intent(),
                portfolio_value=10_000.0, current_quantities={}, prices={"AAPL": 200.0},
                available_cash=100.0, eligible_buy_symbols={"AAPL"}, required_mode="live", now=NOW,
            )

    def test_sell_first_manifest_executes_without_the_buy_cash(self):
        # 예전에는 MSFT 매수 자금 부족 때문에 위험을 줄이는 AAPL 매도까지 막혔다.
        repository = FakeRepository(value_intent=rotation_intent(), value_handoff=funding_handoff())
        api = FakeApi(buying_power=Decimal(500))
        runner = worker(repository, api, fresh=rotation_snapshot())
        runner.planner = rotation_planner()
        repository.current_tracked_tickers = lambda: {"AAPL", "MSFT"}
        result = runner.execute(repository.approval.approval_id, now=NOW)
        self.assertEqual(api.posts, 1)
        self.assertEqual(result.status, "reconciling")

    def test_cash_change_that_flips_the_phase_requires_reapproval(self):
        repository = FakeRepository(value_intent=rotation_intent(), value_handoff=funding_handoff())
        api = FakeApi(buying_power=Decimal(5_000))
        runner = worker(repository, api, fresh=rotation_snapshot(cash=5_000.0))
        runner.planner = rotation_planner()
        repository.current_tracked_tickers = lambda: {"AAPL", "MSFT"}
        with self.assertRaisesRegex(ExecutionSafetyError, "whether buys can be funded"):
            runner.execute(repository.approval.approval_id, now=NOW)
        self.assertEqual(api.posts, 0)
        self.assertNotIn("consume", repository.trace)

    def test_phase_is_bound_to_the_manifest_but_full_hashes_are_unchanged(self):
        full = handoff()
        self.assertNotIn("funding_phase", full.identity())
        funding = funding_handoff()
        self.assertEqual(funding.identity()["funding_phase"], FUNDING_PHASE_SELLS)
        relabeled = replace(funding, funding_phase=FUNDING_PHASE_FULL)
        with self.assertRaisesRegex(ExecutionSafetyError, "contents changed"):
            relabeled.validate_manifest()
        restored = TossManualHandoff.from_private_dict(funding.to_dict(), account_seq=ACCOUNT)
        self.assertEqual(restored.funding_phase, FUNDING_PHASE_SELLS)
        with self.assertRaisesRegex(ExecutionSafetyError, "sells only"):
            replace(full, funding_phase=FUNDING_PHASE_SELLS)


def sell_only_handoff() -> TossManualHandoff:
    """보유 20주 중 10주를 파는, 노출을 줄이기만 하는 주문표."""
    snap = replace(rotation_snapshot(cash=5_000.0), current_quantities={"AAPL": 20.0})
    order_id = "aix_" + hashlib.sha256(b"intent-live-worker|AAPL|sell|10.000000").hexdigest()[:20]
    value = TossManualHandoff(
        intent_id=intent().intent_id, account_seq=ACCOUNT, contract_version="toss-manual-v1",
        snapshot=snap,
        tickets=(TossManualTicket(
            intent_id=intent().intent_id, client_order_id=order_id, expires_at=intent().expires_at,
            symbol="AAPL", side="sell", current_quantity=20.0, target_weight=0.2222222222,
            target_quantity=10.0, order_quantity=10.0, reference_price=200.0,
            price_timestamp=NOW.isoformat(), estimated_notional=2_000.0,
        ),),
        manifest_hash="0" * 64,
    )
    return replace(value, manifest_hash=value.recomputed_manifest_hash())


def reducing_state() -> RuntimeRiskState:
    return RuntimeRiskState(
        submitted_order_count=0, submitted_notional_usd=0, realized_pnl_usd=-900,
        drawdown_fraction=0.01, captured_at=NOW.isoformat(),
    )


class TradingStateTest(unittest.TestCase):
    def controls(self, **overrides):
        values = dict(
            live_enabled=True, kill_switch_on=False, account_seq=ACCOUNT,
            max_daily_loss_usd=500, max_drawdown_fraction=0.05,
        )
        values.update(overrides)
        return LiveTradingControls(**values)

    def test_state_resolution(self):
        healthy = RuntimeRiskState(0, 0, 0, 0.0, NOW.isoformat())
        self.assertEqual(resolve_trading_state(self.controls(), healthy), TRADING_STATE_ACTIVE)
        self.assertEqual(resolve_trading_state(self.controls(), reducing_state()), TRADING_STATE_REDUCING)
        deep = RuntimeRiskState(0, 0, 0, 0.08, NOW.isoformat())
        self.assertEqual(resolve_trading_state(self.controls(), deep), TRADING_STATE_REDUCING)
        self.assertEqual(
            resolve_trading_state(self.controls(kill_switch_on=True), healthy), TRADING_STATE_HALTED,
        )

    def test_order_risk_classification_is_fail_closed(self):
        self.assertEqual(classify_order_risk(side="BUY", quantity=1, position_quantity=10), ORDER_RISK_INCREASING)
        self.assertEqual(classify_order_risk(side="SELL", quantity=5, position_quantity=10), ORDER_RISK_REDUCING)
        # 보유 수량을 모르면 줄인다고 증명할 수 없다.
        self.assertEqual(classify_order_risk(side="SELL", quantity=5, position_quantity=None), ORDER_RISK_INCREASING)
        with self.assertRaisesRegex(ExecutionSafetyError, "short selling"):
            classify_order_risk(side="SELL", quantity=11, position_quantity=10)

    def test_reducing_state_lets_a_position_reducing_sell_through(self):
        repository = FakeRepository(value_handoff=sell_only_handoff())
        repository.intent = replace(intent(), target_weights={"AAPL": 10 * 200 / 9_000, "CASH": 1 - 10 * 200 / 9_000})
        repository.risk_override = reducing_state()
        api = FakeApi(buying_power=Decimal(5_000))
        runner = worker(repository, api, fresh=sell_only_handoff().snapshot)
        runner.execute(repository.approval.approval_id, now=NOW)
        self.assertEqual(api.posts, 1)

    def test_reducing_state_blocks_buys_before_the_approval_is_consumed(self):
        repository = FakeRepository()
        repository.risk_override = reducing_state()
        api = FakeApi()
        with self.assertRaisesRegex(ExecutionSafetyError, "REDUCING"):
            worker(repository, api).execute(repository.approval.approval_id, now=NOW)
        self.assertEqual(api.posts, 0)
        self.assertNotIn("consume", repository.trace)

    def test_broker_gate_rejects_buy_but_not_reducing_sell_in_reducing_state(self):
        permit = type("Permit", (), {
            "account_seq": ACCOUNT, "manifest_hash": "m" * 64, "allowed_client_order_ids": ("c1",),
            "issued_at": (NOW - timedelta(seconds=5)).isoformat(),
            "expires_at": (NOW + timedelta(seconds=60)).isoformat(),
        })()

        def order(side):
            return type("Order", (), {
                "client_order_id": "c1", "order_type": "LIMIT", "side": side,
                "quantity": Decimal(5), "estimated_notional_usd": 1_000.0,
            })()

        with TemporaryDirectory() as state_dir:
            common = dict(
                permit=permit, controls=self.controls(), state=reducing_state(),
                manifest_hash="m" * 64, now=NOW, lockdown_state_dir=Path(state_dir),
            )
            assert_live_order_allowed(order=order("SELL"), position_quantity=10, **common)
            with self.assertRaisesRegex(ExecutionSafetyError, "daily loss limit"):
                assert_live_order_allowed(order=order("BUY"), position_quantity=10, **common)
            with self.assertRaisesRegex(ExecutionSafetyError, "daily loss limit"):
                assert_live_order_allowed(order=order("SELL"), position_quantity=None, **common)

    def test_superseded_intent_stops_before_the_approval_is_consumed(self):
        # 대체된 intent는 cancelled다. 계획 단계의 intent 검증이 승인 소비 전에 막는다.
        repository = FakeRepository()
        repository.intent = replace(intent(), status="cancelled")
        api = FakeApi()
        with self.assertRaises(ExecutionSafetyError):
            worker(repository, api).execute(repository.approval.approval_id, now=NOW)
        self.assertNotIn("consume", repository.trace)
        self.assertEqual(api.posts, 0)

    def test_unreconciled_orders_block_new_live_orders(self):
        repository = FakeRepository()
        repository.unresolved = [{"client_order_id": "aix_old", "status": "outcome_unknown"}]
        api = FakeApi()
        with self.assertRaisesRegex(ExecutionSafetyError, "await reconciliation"):
            worker(repository, api).execute(repository.approval.approval_id, now=NOW)
        self.assertEqual(api.posts, 0)
        self.assertNotIn("consume", repository.trace)


if __name__ == "__main__":
    unittest.main()
