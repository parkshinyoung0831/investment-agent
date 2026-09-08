from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.db import ExecutionRepository
from investment_agent.execution.orders.intents import ExecutionIntent
from investment_agent.platform.db.sqlite import runtime_connection

_ACCOUNT_SEQ = 7
_ACCOUNT_HASH = hashlib.sha256(f"toss|{_ACCOUNT_SEQ}".encode("utf-8")).hexdigest()


class RuntimeRiskRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "runtime.sqlite3"
        env = patch.dict("os.environ", {"AI_INVESTOR_RUNTIME_DB_PATH": str(self.path)})
        env.start()
        self.addCleanup(env.stop)
        self.repo = ExecutionRepository()

    def _seed_order(self, *, client_order_id: str, notional: float, submitted_at: str) -> None:
        now = datetime.now(timezone.utc)
        intent = ExecutionIntent(
            intent_id=f"intent-{client_order_id}", proposal_id="proposal-1", risk_decision_id=f"risk-{client_order_id}",
            execution_mode="live", target_weights={"AAPL": .1, "CASH": .9}, input_hash="a" * 64,
            not_before=now - timedelta(days=1), expires_at=now + timedelta(days=1),
        )
        self.repo.save_intent(intent.as_row())
        payload = {
            "client_order_id": client_order_id, "intent_id": intent.intent_id, "account_seq": _ACCOUNT_SEQ,
            "status": "submitted", "notional": notional, "submitted_at": submitted_at,
        }
        with runtime_connection() as connection:
            connection.execute(
                "INSERT INTO orders(client_order_id,broker_order_id,intent_id,status,account_seq,submitted_at,updated_at,payload_json) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (client_order_id, None, intent.intent_id, "submitted", _ACCOUNT_SEQ, submitted_at,
                 now.isoformat(), json.dumps(payload)),
            )

    def test_missing_preopen_or_prior_baseline_fails_before_write(self):
        with self.assertRaisesRegex(ExecutionSafetyError, "baseline is missing"):
            self.repo.runtime_risk_state(
                account_seq=_ACCOUNT_SEQ,
                current_equity=1_000.0,
                broker_daily_pnl_usd=0.0,
                captured_at=datetime(2026, 8, 21, 14, tzinfo=timezone.utc),
            )
        with runtime_connection(read_only=True) as connection:
            self.assertIsNone(connection.execute("SELECT 1 FROM runtime_records LIMIT 1").fetchone())

    def test_uses_worse_of_broker_daily_pnl_and_equity_change(self):
        # 프리마켓 기준점(장 시작 전, 09:30 ET = 13:30 UTC 이전).
        self.repo.save_account_snapshot({
            "execution_mode": "live", "broker_account_hash": _ACCOUNT_HASH,
            "equity": 1000.0, "cash": 0.0, "captured_at": "2026-08-21T13:20:00+00:00",
        })
        # 장중 관측점. 당일 peak/drawdown 계산에 들어간다.
        self.repo.save_account_snapshot({
            "execution_mode": "live", "broker_account_hash": _ACCOUNT_HASH,
            "equity": 950.0, "cash": 0.0, "captured_at": "2026-08-21T14:00:00+00:00",
        })
        self._seed_order(client_order_id="one", notional=100, submitted_at="2026-08-21T13:40:00+00:00")
        self._seed_order(client_order_id="two", notional=200, submitted_at="2026-08-21T13:50:00+00:00")

        state = self.repo.runtime_risk_state(
            account_seq=_ACCOUNT_SEQ,
            current_equity=950.0,
            broker_daily_pnl_usd=-75.0,
            captured_at=datetime(2026, 8, 21, 14, tzinfo=timezone.utc),
        )
        self.assertEqual(state.realized_pnl_usd, -75.0)
        self.assertAlmostEqual(state.drawdown_fraction, 0.05)
        self.assertEqual(state.submitted_order_count, 2)
        self.assertEqual(state.submitted_notional_usd, 300.0)
        with runtime_connection(read_only=True) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM runtime_records WHERE record_type='account_snapshot'"
            ).fetchall()
        self.assertEqual(3, len(rows), "베이스라인 2개 + 이번 호출이 남긴 새 스냅샷 1개")


if __name__ == "__main__":
    unittest.main()
