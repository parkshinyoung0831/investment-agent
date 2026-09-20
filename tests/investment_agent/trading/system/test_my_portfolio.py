"""My Portfolio: 현재 System 목표 − 최신 실제 계좌 = 주문. 과거 거절을 복구하지 않는다."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.execution.orders.snapshots import AccountSnapshot, PositionSnapshot
from investment_agent.trading.contracts import ContractError
from investment_agent.trading.my_portfolio import follow_weights, order_gaps, plan_follow
from investment_agent.trading.system.store import SystemTargetRecord

NOW = datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc)
TARGET_WEIGHTS = {"NVDA": 0.08, "MSFT": 0.07, "CASH": 0.85}


def _target(**changes) -> SystemTargetRecord:
    values = dict(target_id="system_target_" + "a" * 24, decided_at=(NOW - timedelta(days=1)).isoformat(),
                  factor_snapshot_as_of="S1", proposal_id="proposal_1", risk_decision_id="risk_" + "b" * 24,
                  model_artifact_id="artifact_1", is_approved=True, weights=dict(TARGET_WEIGHTS),
                  applied_session=None, detail={})
    values.update(changes)
    return SystemTargetRecord(**values)


def _snapshot(cash: float, positions: dict[str, tuple[float, float]] | None = None, **changes) -> AccountSnapshot:
    return AccountSnapshot(
        broker="toss", account_id="7", captured_at=NOW.isoformat(), cash_value=cash,
        positions=tuple(PositionSnapshot(ticker, quantity, price, quantity * price)
                        for ticker, (quantity, price) in (positions or {}).items()),
        **changes,
    )


def _save_snapshot(snapshot: AccountSnapshot) -> str:
    return "execution_snapshot_1"


class _Ledger:
    def __init__(self):
        self.rows: dict[str, list[dict]] = {}

    def __getattr__(self, name):
        if name.startswith("save_") or name == "finish_decision_run":
            return lambda *args, **kwargs: self.rows.setdefault(name, []).append(args[0] if args else kwargs)
        raise AttributeError(name)


class FollowWeightsTest(unittest.TestCase):
    def test_holdings_outside_the_system_target_are_sold(self):
        """직접 산 종목도 System 목표에 없으면 0이다 — 실행 계층이 전량 매도한다."""
        weights = follow_weights(TARGET_WEIGHTS, _snapshot(4_000.0, {"TSLA": (2.0, 500.0)}))
        self.assertEqual(weights["TSLA"], 0.0)
        self.assertEqual(weights["NVDA"], 0.08)

    def test_an_all_cash_account_catches_up_to_the_current_target_at_once(self):
        """한 달 동안 거절했어도 과거 주문을 복구하지 않고 지금 목표와의 차이만 산다."""
        gaps = order_gaps(follow_weights(TARGET_WEIGHTS, _snapshot(5_000.0)), _snapshot(5_000.0))
        self.assertAlmostEqual(gaps["NVDA"], 400.0)
        self.assertAlmostEqual(gaps["MSFT"], 350.0)

    def test_gaps_use_the_whole_account_not_only_cash(self):
        snapshot = _snapshot(1_000.0, {"NVDA": (40.0, 100.0)})  # 총 5,000, NVDA 4,000(80%)
        gaps = order_gaps(follow_weights(TARGET_WEIGHTS, snapshot), snapshot)
        self.assertAlmostEqual(gaps["NVDA"], 400.0 - 4_000.0)


class PlanFollowTest(unittest.TestCase):
    def test_plan_records_a_live_proposal_that_follows_exactly_the_system_target(self):
        ledger = _Ledger()
        outcome = plan_follow(ledger, target=_target(), snapshot=_snapshot(4_000.0, {"TSLA": (2.0, 500.0)}), now=NOW, save_snapshot=_save_snapshot)
        self.assertEqual(outcome.status, "planned")
        proposal = ledger.rows["save_portfolio_proposal"][0]
        self.assertEqual(proposal["stage"], "live")
        self.assertEqual(proposal["metadata"]["system_target_id"], _target().target_id)
        self.assertEqual(proposal["account_snapshot_id"], "execution_snapshot_1")
        self.assertEqual(proposal["metadata"]["sold_outside_target"], ["TSLA"])
        risk = ledger.rows["save_risk_decision"][0]
        self.assertTrue(risk["is_approved"])
        self.assertEqual(risk["approved_weights"], proposal["weights"])
        for symbol, weight in TARGET_WEIGHTS.items():
            self.assertAlmostEqual(risk["approved_weights"][symbol], weight)
        self.assertEqual(risk["risk_decision_id"], outcome.risk_decision_id)

    def test_an_account_that_already_matches_the_target_asks_nothing(self):
        snapshot = _snapshot(4_250.0, {"NVDA": (4.0, 100.0), "MSFT": (1.0, 350.0)})  # 총 5,000 = 8% / 7% / 85%
        ledger = _Ledger()
        writes: list[AccountSnapshot] = []

        def save_snapshot(value: AccountSnapshot) -> str:
            writes.append(value)
            return "execution_snapshot_1"

        outcome = plan_follow(ledger, target=_target(), snapshot=snapshot, now=NOW, save_snapshot=save_snapshot)
        self.assertEqual((outcome.status, outcome.reason), ("skipped", "already_following"))
        self.assertEqual(ledger.rows, {})
        self.assertEqual(writes, [])

    def test_a_manual_external_trade_shows_up_in_the_next_snapshot(self):
        """사용자가 Toss에서 직접 판 종목은 다음 스냅샷의 차이로 다시 계산된다."""
        matched = _snapshot(4_250.0, {"NVDA": (4.0, 100.0), "MSFT": (1.0, 350.0)})
        sold_by_hand = _snapshot(4_650.0, {"MSFT": (1.0, 350.0)})
        self.assertEqual(plan_follow(_Ledger(), target=_target(), snapshot=matched, now=NOW, save_snapshot=_save_snapshot).status, "skipped")
        outcome = plan_follow(_Ledger(), target=_target(), snapshot=sold_by_hand, now=NOW, save_snapshot=_save_snapshot)
        self.assertEqual(outcome.status, "planned")

    def test_stale_or_unapproved_targets_and_open_orders_are_not_followed(self):
        old = _target(decided_at=(NOW - timedelta(days=11)).isoformat())
        self.assertEqual(plan_follow(_Ledger(), target=old, snapshot=_snapshot(5_000.0), now=NOW, save_snapshot=_save_snapshot).reason,
                         "system_target_stale")
        busy = _snapshot(5_000.0, open_order_ids=("order-1",))
        self.assertEqual(plan_follow(_Ledger(), target=_target(), snapshot=busy, now=NOW, save_snapshot=_save_snapshot).reason,
                         "account_has_open_orders")
        with self.assertRaises(ContractError):
            plan_follow(_Ledger(), target=_target(is_approved=False, weights={}), snapshot=_snapshot(5_000.0), now=NOW, save_snapshot=_save_snapshot)

    def test_the_same_target_and_account_plan_the_same_identity(self):
        first = plan_follow(_Ledger(), target=_target(), snapshot=_snapshot(5_000.0), now=NOW, save_snapshot=_save_snapshot)
        second = plan_follow(_Ledger(), target=_target(), snapshot=_snapshot(5_000.0), now=NOW, save_snapshot=_save_snapshot)
        self.assertEqual((first.proposal_id, first.risk_decision_id), (second.proposal_id, second.risk_decision_id))


if __name__ == "__main__":
    unittest.main()
