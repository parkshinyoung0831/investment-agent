"""System 추종 계좌 스냅샷은 Operations가 Execution 원장과 Data identity를 조립한다."""
from __future__ import annotations

import hashlib
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from investment_agent.execution.orders.snapshots import AccountSnapshot, PositionSnapshot
from investment_agent.operations.adapters.trading import follow_system_target, save_follow_snapshot


class _Execution:
    def __init__(self) -> None:
        self.account_rows: list[dict] = []
        self.position_rows: list[list[dict]] = []

    def save_account_snapshot(self, row: dict) -> str:
        self.account_rows.append(row)
        return "execution_snapshot_1"

    def save_position_snapshots(self, rows: list[dict]) -> None:
        self.position_rows.append(rows)


class FollowSnapshotTest(unittest.TestCase):
    def test_harness_wires_execution_snapshot_writer_into_trading_plan(self) -> None:
        target = SimpleNamespace(target_id="system-1", model_artifact_id="artifact-1")
        store = SimpleNamespace(latest_target=lambda *, approved_only: target)
        repository = SimpleNamespace(has_approved_promotion=lambda artifact_id, stage: True)
        snapshot = AccountSnapshot(
            broker="toss", account_id="7", captured_at="2026-09-16T15:00:00+00:00",
            cash_value=5000.0,
        )
        with (
            patch("investment_agent.execution.brokers.toss.client.resolve_account_seq", return_value=7),
            patch("investment_agent.execution.orders.toss_snapshot.capture_toss_account_snapshot", return_value=snapshot),
            patch("investment_agent.trading.my_portfolio.plan_follow", return_value="planned") as planned,
        ):
            result = follow_system_target(
                target_id="system-1", store=store, repository=repository,
                now=datetime(2026, 9, 16, 15, tzinfo=timezone.utc),
            )
        self.assertEqual(result, "planned")
        self.assertIs(planned.call_args.kwargs["save_snapshot"], save_follow_snapshot)

    def test_persists_hashed_account_and_identified_positions(self) -> None:
        snapshot = AccountSnapshot(
            broker="toss", account_id="7", captured_at="2026-09-16T15:00:00+00:00",
            cash_value=4000.0,
            positions=(PositionSnapshot("TSLA", 2.0, 500.0, 1000.0),),
            open_order_ids=(),
        )
        execution = _Execution()
        snapshot_id = save_follow_snapshot(
            snapshot, execution_repository=execution,
            security_ids_by_ticker=lambda tickers: {"TSLA": 42},
        )
        self.assertEqual(snapshot_id, "execution_snapshot_1")
        account = execution.account_rows[0]
        self.assertEqual(account["broker_account_hash"], hashlib.sha256(b"toss|7").hexdigest())
        self.assertEqual(account["execution_mode"], "live")
        self.assertEqual(account["raw_snapshot"]["source"], "portfolio_construction")
        self.assertEqual(execution.position_rows[0][0]["security_id"], 42)
        self.assertAlmostEqual(execution.position_rows[0][0]["weight"], 0.2)
        self.assertNotIn("account_id", account)

    def test_missing_security_identity_does_not_write_position(self) -> None:
        snapshot = AccountSnapshot(
            broker="toss", account_id="7", captured_at="2026-09-16T15:00:00+00:00",
            cash_value=4000.0,
            positions=(PositionSnapshot("TSLA", 2.0, 500.0, 1000.0),),
        )
        execution = _Execution()
        with self.assertRaisesRegex(RuntimeError, "unknown universe securities"):
            save_follow_snapshot(snapshot, execution_repository=execution, security_ids_by_ticker=lambda tickers: {})
        self.assertEqual(len(execution.account_rows), 1)
        self.assertEqual(execution.position_rows, [])
