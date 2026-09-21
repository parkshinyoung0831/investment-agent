"""승인 요청과 실행 재검증이 같은 한도로 주문표를 계획하는지 묻는다.

재검증은 다시 계획한 주문표를 승인 주문표와 완전히 비교한다. 두 진입점이 한도를 각자 읽으면
env 하나만 바뀌어도 주문표가 갈라져 "계좌·시세가 바뀌었다"는 잘못된 이유로 영구히 막힌다.
"""
from __future__ import annotations

import unittest

from investment_agent.execution.orders.live_worker import TossLiveExecutionWorker
from investment_agent.execution.safety.control import LiveTradingControls, planning_notionals
from investment_agent.operations.commands.request_toss_approval import _whole_share_planner

# 기본값과 모두 다른 값이라 어느 한도든 기본값으로 새면 어긋난다.
ENV = {
    "TOSS_ACCOUNT_SEQ": "7",
    "TOSS_MIN_ORDER_NOTIONAL_USD": "50",
    "TOSS_MAX_ORDER_NOTIONAL_USD": "3000",
    "TOSS_MAX_DAILY_NOTIONAL_USD": "12000",
}


class PlannerParityTest(unittest.TestCase):
    def test_approval_and_worker_plan_with_the_same_limits(self) -> None:
        controls = LiveTradingControls.from_config(ENV)
        worker = TossLiveExecutionWorker(repository=object(), api=object(), controls=controls)
        approval = _whole_share_planner(ENV)
        self.assertEqual(approval.limits, worker.planner.limits)
        self.assertEqual(
            (50.0, 3000.0, 12000.0),
            (approval.limits.min_order_notional, approval.limits.max_order_notional,
             approval.limits.max_total_notional),
        )

    def test_the_batch_total_is_the_daily_limit_not_a_separate_setting(self) -> None:
        self.assertEqual(12000.0, planning_notionals(ENV).max_total_notional_usd)
        # 옛 별도 설정은 더 이상 아무것도 바꾸지 못한다.
        with_old = {**ENV, "TOSS_MAX_TOTAL_NOTIONAL_USD": "999"}
        self.assertEqual(planning_notionals(ENV), planning_notionals(with_old))


class CashBufferContractTest(unittest.TestCase):
    """계획 단계 현금 여유가 실행 preflight의 band·수수료 여유를 항상 덮는다."""

    def test_default_policy_fits_inside_the_planning_buffer(self) -> None:
        from investment_agent.execution.orders.live_worker import LiveExecutionPolicy

        LiveExecutionPolicy()

    def test_a_policy_wider_than_the_planning_buffer_is_refused(self) -> None:
        from investment_agent.execution.orders.live_worker import LiveExecutionPolicy

        # (1+0.0025)(1+0.0060) = 1.0085 > 1.0050 — 승인은 통과하고 실행은 항상 막히는 조합
        with self.assertRaisesRegex(ValueError, "planning cash buffer"):
            LiveExecutionPolicy(limit_band_bps=25, commission_buffer_bps=60)


if __name__ == "__main__":
    unittest.main()
