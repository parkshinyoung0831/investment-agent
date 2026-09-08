"""차단기는 신규 매수만 얼리고, 근거가 없으면 막지 않는다."""
from __future__ import annotations

import unittest

from investment_agent.execution.safety.circuit_breaker import (
    CircuitBreakerPolicy,
    CircuitBreakerStatus,
    evaluate,
)

POLICY = CircuitBreakerPolicy(
    vix_halt_threshold=35.0, max_daily_drawdown=0.03, max_consecutive_failures=3
)


class PolicyShapeTest(unittest.TestCase):
    def test_an_absurdly_low_vix_threshold_is_refused(self) -> None:
        """설정 오타로 0이 들어오면 모든 날이 차단된다."""
        with self.assertRaises(ValueError):
            CircuitBreakerPolicy(vix_halt_threshold=0.0)

    def test_a_zero_drawdown_limit_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            CircuitBreakerPolicy(max_daily_drawdown=0.0)

    def test_a_zero_failure_limit_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            CircuitBreakerPolicy(max_consecutive_failures=0)


class EvaluateTest(unittest.TestCase):
    def test_a_calm_day_is_allowed(self) -> None:
        status = evaluate(POLICY, current_vix=15.0, daily_pnl_fraction=0.004)
        self.assertTrue(status.is_allowed)
        self.assertEqual("NORMAL", status.state)
        self.assertIsNone(status.reason)

    def test_our_own_failures_are_checked_first(self) -> None:
        """주문이 계속 거부되는데 시장 지표를 따지는 것은 순서가 뒤바뀐 것이다."""
        status = evaluate(
            POLICY, current_vix=99.0, daily_pnl_fraction=-0.50,
            consecutive_order_failures=3,
        )
        self.assertEqual("FAILURE_LOCKOUT", status.state)

    def test_a_vix_spike_halts(self) -> None:
        status = evaluate(POLICY, current_vix=40.0)
        self.assertFalse(status.is_allowed)
        self.assertEqual("VOLATILITY_HALT", status.state)

    def test_the_threshold_itself_halts(self) -> None:
        self.assertFalse(evaluate(POLICY, current_vix=35.0).is_allowed)

    def test_a_deep_intraday_loss_halts(self) -> None:
        status = evaluate(POLICY, daily_pnl_fraction=-0.05)
        self.assertEqual("DRAWDOWN_HALT", status.state)

    def test_a_gain_never_halts(self) -> None:
        self.assertTrue(evaluate(POLICY, daily_pnl_fraction=0.05).is_allowed)


class MissingDataTest(unittest.TestCase):
    def test_unknown_market_data_does_not_halt(self) -> None:
        """지표 수집이 실패한 날마다 거래가 멈추면 안 된다."""
        self.assertTrue(evaluate(POLICY).is_allowed)
        self.assertTrue(evaluate(POLICY, current_vix=None, daily_pnl_fraction=None).is_allowed)

    def test_a_nan_reading_is_treated_as_unknown(self) -> None:
        self.assertTrue(evaluate(POLICY, current_vix=float("nan")).is_allowed)

    def test_our_own_failure_count_is_always_checked(self) -> None:
        """시장 지표를 몰라도 우리가 아는 사실은 검사한다."""
        self.assertFalse(evaluate(POLICY, consecutive_order_failures=5).is_allowed)


class StatusShapeTest(unittest.TestCase):
    def test_a_halt_must_explain_itself(self) -> None:
        """이유 없는 차단은 운영자가 풀 수 없다."""
        with self.assertRaises(ValueError):
            CircuitBreakerStatus(is_allowed=False, state="VOLATILITY_HALT", reason=None)

    def test_an_unknown_state_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            CircuitBreakerStatus(is_allowed=True, state="PANIC", reason=None)

    def test_every_halt_names_the_number_that_tripped_it(self) -> None:
        for kwargs in (
            {"current_vix": 40.0},
            {"daily_pnl_fraction": -0.05},
            {"consecutive_order_failures": 3},
        ):
            with self.subTest(**kwargs):
                status = evaluate(POLICY, **kwargs)
                self.assertFalse(status.is_allowed)
                self.assertTrue(any(char.isdigit() for char in status.reason or ""))


if __name__ == "__main__":
    unittest.main()
