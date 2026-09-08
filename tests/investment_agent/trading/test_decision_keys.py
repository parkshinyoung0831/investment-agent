"""같은 판단은 같은 키로 모이고, 입력이 달라지면 지문이 달라져야 한다."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.trading.run_context import ContractViolation, RunContext, shadow_context
from investment_agent.trading.decision.keys import (
    case_key,
    context_hash,
    is_reproducible,
    truncate_to_second,
)

AS_OF = datetime(2026, 9, 5, 13, 30, 0, tzinfo=timezone.utc)
BASE = dict(security_id=1, as_of_at=AS_OF, horizon_days=20,
            policy_key="default", policy_version=1)


class CaseKeyTest(unittest.TestCase):
    def test_the_same_question_gives_the_same_key(self) -> None:
        self.assertEqual(case_key(**BASE), case_key(**BASE))

    def test_sub_second_noise_does_not_change_the_key(self) -> None:
        """마이크로초까지 쓰면 재실행이 매번 새 행을 만든다."""
        noisy = {**BASE, "as_of_at": AS_OF + timedelta(microseconds=7)}
        self.assertEqual(case_key(**BASE), case_key(**noisy))

    def test_every_component_changes_the_key(self) -> None:
        for field, value in (
            ("security_id", 2),
            ("as_of_at", AS_OF + timedelta(seconds=1)),
            ("horizon_days", 5),
            ("policy_key", "aggressive"),
            ("policy_version", 2),
        ):
            with self.subTest(field=field):
                self.assertNotEqual(case_key(**BASE), case_key(**{**BASE, field: value}))

    def test_the_key_is_readable_at_a_glance(self) -> None:
        """로그에서 어느 종목·어느 날인지 바로 보여야 한다."""
        key = case_key(**BASE)
        self.assertTrue(key.startswith("1:2026-09-05:h20:"))

    def test_a_naive_timestamp_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            case_key(**{**BASE, "as_of_at": datetime(2026, 9, 5, 13, 30)})

    def test_a_zero_horizon_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            case_key(**{**BASE, "horizon_days": 0})

    def test_truncation_keeps_the_timezone(self) -> None:
        self.assertEqual(timezone.utc, truncate_to_second(AS_OF).tzinfo)


class ContextHashTest(unittest.TestCase):
    def test_key_order_does_not_change_the_hash(self) -> None:
        self.assertEqual(
            context_hash({"price": 100.0, "rsi": 55.0}),
            context_hash({"rsi": 55.0, "price": 100.0}),
        )

    def test_a_changed_input_changes_the_hash(self) -> None:
        self.assertNotEqual(
            context_hash({"price": 100.0}), context_hash({"price": 100.5})
        )

    def test_reproducibility_check_reads_the_recorded_hash(self) -> None:
        context = {"price": 100.0, "rsi": 55.0}
        recorded = context_hash(context)
        self.assertTrue(is_reproducible(recorded, context))
        self.assertFalse(is_reproducible(recorded, {**context, "rsi": 56.0}))

    def test_the_hash_is_sha256_hex(self) -> None:
        self.assertEqual(64, len(context_hash({"a": 1})))


class RunContextTest(unittest.TestCase):
    def test_the_default_is_shadow_on_paper(self) -> None:
        context = shadow_context()
        self.assertFalse(context.is_live_money)
        self.assertEqual("live_shadow", context.source_kind)

    def test_a_backtest_cannot_use_live_input(self) -> None:
        """과거 검증에 실시간 입력을 섞으면 그 성적은 재현되지 않는다."""
        with self.assertRaises(ContractViolation):
            RunContext(stage="backtest", execution_mode="paper", source_kind="live_shadow")

    def test_live_money_needs_a_promoted_model(self) -> None:
        """승격되지 않은 모델의 주문이 실계좌로 나가는 길을 막는다."""
        with self.assertRaises(ContractViolation):
            RunContext(stage="shadow", execution_mode="live", source_kind="live_shadow")

    def test_a_promoted_model_may_still_run_on_paper(self) -> None:
        context = RunContext(stage="live", execution_mode="paper", source_kind="live_shadow")
        self.assertFalse(context.is_live_money)

    def test_unknown_values_are_refused(self) -> None:
        for field, value in (
            ("stage", "production"),
            ("execution_mode", "real"),
            ("source_kind", "replay"),
        ):
            base = {"stage": "shadow", "execution_mode": "paper", "source_kind": "live_shadow"}
            with self.subTest(field=field), self.assertRaises(ContractViolation):
                RunContext(**{**base, field: value})

    def test_the_row_carries_all_three_axes(self) -> None:
        self.assertEqual(
            {"stage", "execution_mode", "source_kind"}, set(shadow_context().as_row())
        )


if __name__ == "__main__":
    unittest.main()
