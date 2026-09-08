"""실행 의도가 받아들이는 모양. 여기서 막지 못한 것은 주문이 된다."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.execution.orders.intents import (
    CASH_SYMBOL,
    ExecutionIntent,
    IntentError,
    validated_weights,
)

NOW = datetime(2026, 9, 5, 13, 30, tzinfo=timezone.utc)
INPUT_HASH = "a" * 64


def _intent(**overrides: object) -> ExecutionIntent:
    fields = {
        "intent_id": "in1", "risk_decision_id": "rd1", "proposal_id": "p1",
        "execution_mode": "paper", "target_weights": {"AAPL": 0.10, "CASH": 0.90},
        "input_hash": INPUT_HASH,
        "not_before": NOW - timedelta(minutes=5),
        "expires_at": NOW + timedelta(hours=1),
        "status": "approved",
    }
    fields.update(overrides)
    return ExecutionIntent(**fields)  # type: ignore[arg-type]


class WeightContractTest(unittest.TestCase):
    def test_the_total_including_cash_must_be_one(self) -> None:
        """10%만 적힌 의도가 통과하면 나머지 90%를 아무도 말하지 않은 채 계획이 결정한다."""
        with self.assertRaises(IntentError):
            validated_weights({"AAPL": 0.10})

    def test_a_fully_invested_portfolio_needs_no_cash_entry(self) -> None:
        self.assertEqual(
            {"AAPL": 0.5, "CASH": 0.0, "MSFT": 0.5},
            validated_weights({"AAPL": 0.5, "MSFT": 0.5}),
        )

    def test_rounding_noise_is_tolerated(self) -> None:
        self.assertIn("AAPL", validated_weights({"AAPL": 0.1 + 1e-12, "CASH": 0.9}))

    def test_a_negative_weight_is_refused_not_zeroed(self) -> None:
        """0으로 바꾸면 데이터 오류가 매도 주문이 된다."""
        with self.assertRaises(IntentError):
            validated_weights({"AAPL": -0.10, "CASH": 1.10})

    def test_a_weight_above_one_is_refused(self) -> None:
        with self.assertRaises(IntentError):
            validated_weights({"AAPL": 1.5, "CASH": -0.5})

    def test_a_boolean_is_not_a_weight(self) -> None:
        """float(True)는 1.0이라 플래그가 100% 비중이 된다."""
        with self.assertRaises(IntentError):
            validated_weights({"AAPL": True, "CASH": 0.0})

    def test_an_unreadable_symbol_is_refused(self) -> None:
        for symbol in ("aa pl", "TOOLONGTICKER1", "티커"):
            with self.subTest(symbol=symbol), self.assertRaises(IntentError):
                validated_weights({symbol: 1.0})

    def test_symbols_are_normalised_to_upper_case(self) -> None:
        self.assertIn("AAPL", validated_weights({"aapl": 1.0}))

    def test_an_empty_mapping_is_refused(self) -> None:
        with self.assertRaises(IntentError):
            validated_weights({})


class ExecutabilityTest(unittest.TestCase):
    def test_an_approved_intent_in_its_window_is_executable(self) -> None:
        _intent().assert_executable(now=NOW)

    def test_an_expired_intent_is_refused(self) -> None:
        """며칠 전 승인이 오늘 주문으로 나가면 안 된다."""
        with self.assertRaises(IntentError):
            _intent().assert_executable(now=NOW + timedelta(days=2))

    def test_an_intent_before_its_window_is_refused(self) -> None:
        with self.assertRaises(IntentError):
            _intent().assert_executable(now=NOW - timedelta(hours=1))

    def test_a_completed_intent_is_not_executable(self) -> None:
        with self.assertRaises(IntentError):
            _intent(status="completed").assert_executable(now=NOW)

    def test_the_mode_must_match_the_caller(self) -> None:
        """부르는 쪽이 자기가 어느 경로인지 명시해야 한다."""
        with self.assertRaises(IntentError):
            _intent().assert_executable(now=NOW, required_mode="live")

    def test_paper_is_the_default_required_mode(self) -> None:
        """아무것도 안 적으면 종이로 간다."""
        _intent().assert_executable(now=NOW)


class ShapeTest(unittest.TestCase):
    def test_an_expiry_before_the_start_is_refused(self) -> None:
        with self.assertRaises(IntentError):
            _intent(not_before=NOW, expires_at=NOW - timedelta(hours=1))

    def test_a_non_sha256_input_hash_is_refused(self) -> None:
        with self.assertRaises(IntentError):
            _intent(input_hash="not-a-hash")

    def test_an_unknown_mode_is_refused(self) -> None:
        with self.assertRaises(IntentError):
            _intent(execution_mode="real")

    def test_risky_symbols_exclude_cash(self) -> None:
        self.assertEqual(["AAPL"], _intent().risky_symbols)
        self.assertIn(CASH_SYMBOL, _intent().target_weights)

    def test_the_row_serialises_times_as_iso(self) -> None:
        row = _intent().as_row()
        self.assertTrue(row["not_before"].endswith("+00:00"))
        self.assertEqual({"AAPL": 0.10, "CASH": 0.90}, row["target_weights"])


if __name__ == "__main__":
    unittest.main()
