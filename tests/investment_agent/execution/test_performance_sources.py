"""성과 조회는 외부 조회 없이 원장 사실과 보존된 스냅샷을 반환한다."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone

from investment_agent.execution.db import ExecutionRepository
from investment_agent.platform.db.sqlite import runtime_connection


class PerformanceSourcesTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        env = patch.dict("os.environ", {"AI_INVESTOR_RUNTIME_DB_PATH": str(Path(temporary.name) / "runtime.sqlite3")})
        env.start()
        self.addCleanup(env.stop)
        with runtime_connection():
            pass
        self.repository = ExecutionRepository()

    def test_control_initialization_is_closed_and_never_resets_operator_state(self):
        from investment_agent.execution.contracts import ExecutionSafetyError
        initial = self.repository.initialize_control_state()
        self.assertTrue(initial.kill_switch_on)
        self.assertFalse(initial.live_enabled)
        changed = self.repository.set_manual_control_state(expected_version=1, is_enabled=True, reason='운영자 테스트')
        self.assertFalse(changed.live_autonomy_enabled)
        self.assertEqual(self.repository.initialize_control_state(), changed)
        with self.assertRaises(ExecutionSafetyError):
            self.repository.set_manual_control_state(expected_version=1, is_enabled=False, reason='낡은 요청')

    def test_entry_guard_blocks_price_change_and_expired_review(self):
        from datetime import timedelta
        from investment_agent.execution.contracts import ExecutionSafetyError
        now=datetime.now(timezone.utc)
        guard=dict(ticker='AAPL',plan={'lower_price':99,'upper_price':101},review={'decision':'enter','reviewed_at':now.isoformat(),'expires_at':(now+timedelta(minutes=5)).isoformat()})
        with runtime_connection() as connection:
            self.repository._save_record(connection,'entry_guard','batch',guard)
        with patch.object(self.repository,'_decision_row',return_value={'metadata':{'active_batch_id':'batch'}}):
            self.repository.assert_entry_timing('p',prices={'AAPL':100},now=now)
            with self.assertRaises(ExecutionSafetyError):
                self.repository.assert_entry_timing('p',prices={'AAPL':102},now=now)
            with self.assertRaises(ExecutionSafetyError):
                self.repository.assert_entry_timing('p',prices={'AAPL':100},now=now+timedelta(minutes=6))

    def test_detailed_performance_snapshots_survive_risk_retention(self):
        for day in (1, 5):
            self.repository.save_account_snapshot({"execution_mode": "live", "broker_account_hash": "account", "currency": "USD", "equity": 100 + day, "cash": 100 + day, "captured_at": f"2026-09-{day:02d}T12:00:00+00:00", "positions": []})
        sources = self.repository.performance_sources()
        self.assertEqual(len(sources["account_snapshots"]), 2)
        self.assertEqual({row["currency"] for row in sources["account_snapshots"]}, {"USD"})

    def test_only_active_or_executed_live_intents_block_batch(self):
        now = datetime(2026, 9, 13, tzinfo=timezone.utc)
        with runtime_connection() as connection:
            for name, status, expires in (("pending", "approved", "2026-09-14"), ("stale", "approved", "2026-09-12"), ("done", "completed", "2026-09-12"), ("failed", "failed", "2026-09-14")):
                connection.execute("INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?,?)", (name, name, name, "live", status, "2026-09-01", expires + "T00:00:00+00:00", "{}", "2026-09-01", "2026-09-01"))
        for name in ("pending", "done"):
            self.assertTrue(self.repository.has_active_execution_for_proposals([name], as_of_at=now))
        for name in ("stale", "failed", "missing"):
            self.assertFalse(self.repository.has_active_execution_for_proposals([name], as_of_at=now))

    def test_broker_observations_produce_net_realization_without_individual_fills(self):
        from investment_agent.trading.performance.service import update_performance
        from investment_agent.trading.performance.repository import PerformanceRepository
        import json
        with runtime_connection() as connection:
            connection.execute("INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?,?)", ('intent','proposal','risk','live','completed','2026-09-01','2026-09-14',json.dumps({'intent_id':'intent','execution_mode':'live'}),'2026-09-01','2026-09-01'))
            for identity, side in (('buy','buy'),('sell','sell')):
                row = dict(client_order_id=identity, broker_order_id=identity, intent_id='intent', status='filled', account_seq=7, ticker='AAPL', side=side, currency='USD')
                connection.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?)", (identity,identity,'intent','filled',7,'2026-09-01','2026-09-01',json.dumps(row)))
        for identity, price, day in (('buy','100',1),('sell','110',2)):
            self.repository.save_broker_order_snapshot(dict(snapshot_hash=identity,client_order_id=identity,broker_order_id=identity,filled_quantity='2',average_fill_price=price,commission='1',tax='0',observed_at=f'2026-09-0{day}T12:00:00+00:00'))
        performance = PerformanceRepository()
        result = update_performance(source=self.repository, repository=performance, as_of_at=datetime(2026,9,13,tzinfo=timezone.utc))
        self.assertEqual(result['accounts'], 1)
        report = next(row for row in performance.reports() if row['report_kind'] == 'realized')
        self.assertEqual(report['realization']['net_pnl'], 18)
        self.assertEqual(update_performance(source=self.repository, repository=performance, as_of_at=datetime(2026,9,13,tzinfo=timezone.utc))['created'], 0)

    def test_distinct_constructions_cannot_claim_same_signal_batch(self):
        from datetime import timedelta
        from investment_agent.execution.orders.intents import ExecutionIntent
        from investment_agent.execution.contracts import ExecutionSafetyError
        now = datetime.now(timezone.utc)
        def intent(identity):
            return ExecutionIntent(intent_id=identity, proposal_id=identity, risk_decision_id=identity,
                execution_mode='live', target_weights={'CASH':1.0}, input_hash='a'*64,
                not_before=now, expires_at=now+timedelta(hours=1)).as_row()
        with patch.object(self.repository, '_decision_row', return_value={'metadata':{'active_batch_id':'same-batch'}}):
            self.repository.save_intent(intent('first'))
            with self.assertRaisesRegex(ExecutionSafetyError, 'signal batch'):
                self.repository.save_intent(intent('second'))
        with runtime_connection(read_only=True) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM intents').fetchone()[0], 1)

    def test_rejected_entry_review_cannot_create_another_intent(self):
        from datetime import timedelta
        from investment_agent.execution.orders.intents import ExecutionIntent
        from investment_agent.execution.contracts import ExecutionSafetyError
        now = datetime.now(timezone.utc)
        def intent(identity):
            return ExecutionIntent(intent_id=identity, proposal_id=identity, risk_decision_id=identity,
                execution_mode='live', target_weights={'CASH':1.0}, input_hash='a'*64,
                not_before=now, expires_at=now+timedelta(minutes=5)).as_row()
        with runtime_connection() as connection:
            self.repository._save_record(connection,'entry_guard','entry-batch',{'review':{}})
        with patch.object(self.repository,'_decision_row',return_value={'metadata':{'active_batch_id':'entry-batch'}}):
            self.repository.save_intent(intent('first'))
            with runtime_connection() as connection:
                connection.execute("UPDATE intents SET status='failed' WHERE intent_id='first'")
            with self.assertRaisesRegex(ExecutionSafetyError,'already used'):
                self.repository.save_intent(intent('second'))
