"""실주문 CLI 배선 계약 — worker 단위 테스트가 통과해도 진입점이 조립 단계에서 죽을 수 있다.

LiveTradingControls에 없는 factory를 부르던 결함이 클래스 단위 테스트를 모두 통과했다.
여기서는 운영과 같은 `main()`을 fake 원장·broker·Discord로 끝까지 태운다.
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import timedelta

from investment_agent.execution.brokers.toss.client import TossUsRegularSession
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.orders.live_worker import LiveExecutionPolicy, TossLiveExecutionWorker
from investment_agent.execution.orders.planning import ExecutionLimits, TargetWeightOrderPlanner
from investment_agent.execution.safety.control import LiveTradingControls
from investment_agent.operations.commands import execute_toss_live
from tests.investment_agent.execution.test_live_worker import (
    ACCOUNT,
    NOW,
    FakeApi,
    FakeRepository,
    snapshot,
)


@dataclass
class _Control:
    is_open: bool = True

    def assert_live_manual_allowed(self) -> None:
        if not self.is_open:
            raise ExecutionSafetyError("durable control closed")


class _Repository(FakeRepository):
    def __init__(self, *, control_open: bool = True):
        super().__init__()
        self.control = _Control(control_open)

    def load_control_state(self):
        self.trace.append("control")
        return self.control


class _Reporter:
    def __init__(self):
        self.errors: list[tuple[str, dict]] = []
        self.events: list[tuple[str, dict]] = []

    def error(self, name, **fields):
        self.errors.append((name, fields))

    def event(self, name, **fields):
        self.events.append((name, fields))


class _Discord:
    def __init__(self):
        self.messages: list[str] = []

    def __call__(self, guild_id):
        return self

    def set_status_text(self, *, channel_id, message_id, content):
        self.messages.append(content)


def _offline_worker(**kwargs):
    """운영 worker 그대로에 시각·세션·계좌 snapshot만 고정한다."""
    worker = TossLiveExecutionWorker(
        **kwargs,
        planner=TargetWeightOrderPlanner(ExecutionLimits(
            min_order_notional=10, max_order_notional=5_000, max_total_notional=20_000, quantity_decimals=0,
        )),
        policy=LiveExecutionPolicy(),
        snapshot_provider=lambda *args, **inner: snapshot(),
        session_provider=lambda market_date: TossUsRegularSession(
            market_date=market_date, start_at=NOW - timedelta(hours=1), end_at=NOW + timedelta(hours=5),
        ),
        clock=lambda: NOW,
    )
    return worker


LIVE_ENV = {"TOSS_LIVE_ENABLED": "true", "TRADING_KILL_SWITCH": "off", "TOSS_ACCOUNT_SEQ": str(ACCOUNT)}


class ExecuteTossLiveCliTest(unittest.TestCase):
    def _run(self, repository, api, *, environ=LIVE_ENV, locked=False, factory=_offline_worker):
        reporter, discord = _Reporter(), _Discord()
        code = execute_toss_live.main(
            ["--approval-id", repository.approval.approval_id],
            repository=repository, api=api, reporter=reporter, discord_client=discord,
            is_locked_down=lambda: locked, worker_factory=factory, environ=environ,
        )
        return code, reporter, discord

    def test_default_controls_are_built_from_config_and_order_reaches_the_broker(self):
        repository, api = _Repository(), FakeApi()
        code, reporter, discord = self._run(repository, api)
        self.assertEqual(code, 0, reporter.errors)
        self.assertEqual(api.posts, 1)
        self.assertEqual(reporter.events[0][0], "toss_live_orders_submitted")
        self.assertIn("접수", discord.messages[-1])

    def test_controls_passed_to_the_worker_come_from_the_process_config(self):
        seen = {}

        def capture(**kwargs):
            seen["controls"] = kwargs["controls"]
            return _offline_worker(**kwargs)

        self._run(_Repository(), FakeApi(), factory=capture)
        self.assertIsInstance(seen["controls"], LiveTradingControls)
        self.assertEqual(seen["controls"].account_seq, ACCOUNT)
        self.assertTrue(seen["controls"].live_enabled)

    def test_env_without_live_flag_stops_before_any_post(self):
        repository, api = _Repository(), FakeApi()
        code, reporter, discord = self._run(
            repository, api, environ={**LIVE_ENV, "TOSS_LIVE_ENABLED": "false"},
        )
        self.assertEqual(code, 1)
        self.assertEqual(api.posts, 0)
        self.assertEqual(reporter.errors[0][0], "toss_live_execution_stopped")
        self.assertIn("중단", discord.messages[-1])

    def test_closed_durable_control_stops_before_building_the_worker(self):
        repository, api = _Repository(control_open=False), FakeApi()
        built = []
        code, _, _ = self._run(repository, api, factory=lambda **kwargs: built.append(kwargs))
        self.assertEqual(code, 1)
        self.assertEqual(built, [])
        self.assertEqual(api.posts, 0)

    def test_lockdown_stops_before_reading_durable_control(self):
        repository, api = _Repository(), FakeApi()
        code, reporter, _ = self._run(repository, api, locked=True)
        self.assertEqual(code, 1)
        self.assertNotIn("control", repository.trace)
        self.assertEqual(reporter.errors[0][0], "execution_locked_down")



class DurableControlPerOrderTest(unittest.TestCase):
    """운영자가 배치 도중 DB control을 닫으면 다음 주문은 브로커로 가지 않는다."""

    def test_control_closed_after_the_first_post_blocks_the_second_order(self):
        from tests.investment_agent.execution.test_live_worker import two_order_handoff, two_order_intent, two_order_snapshot

        repository = _Repository()
        repository.intent = two_order_intent()
        repository.handoff = two_order_handoff()
        from dataclasses import replace as _replace
        repository.approval = _replace(
            repository.approval, manifest_hash=repository.handoff.manifest_hash,
            allowed_client_order_ids=tuple(ticket.client_order_id for ticket in repository.handoff.tickets),
        )
        api = FakeApi(buying_power=__import__("decimal").Decimal(5000),
                      after_post=lambda posts: setattr(repository.control, "is_open", False))

        def factory(**kwargs):
            worker = _offline_worker(**kwargs)
            worker.snapshot_provider = lambda *args, **inner: two_order_snapshot()
            return worker

        code, reporter, _ = ExecuteTossLiveCliTest._run(self, repository, api, factory=factory)
        self.assertEqual(code, 1)
        self.assertEqual(api.posts, 1)
        self.assertEqual(reporter.errors[0][0], "toss_live_execution_stopped")


if __name__ == "__main__":
    unittest.main()
