"""진입 조건은 미래·낡은 가격과 과도한 LLM 범위를 거부한다."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.trading.entry.rules import create_plan, trigger_status, validate_review

NOW = datetime(2026, 9, 14, 15, tzinfo=timezone.utc)


class EntryTimingTest(unittest.TestCase):
    def plan(self):
        return create_plan(dict(lower_price=99, upper_price=101, invalidate_below=95, valid_hours=4, reason='눌림 확인'),
            reference_price=100, now=NOW, source_expires_at=NOW+timedelta(hours=5))

    def test_price_range_and_invalidation(self):
        plan = self.plan()
        self.assertEqual(trigger_status(plan, price=100, quoted_at=NOW, now=NOW), 'triggered')
        self.assertEqual(trigger_status(plan, price=102, quoted_at=NOW, now=NOW), 'waiting')
        self.assertEqual(trigger_status(plan, price=94, quoted_at=NOW, now=NOW), 'cancelled')

    def test_stale_and_future_quotes_do_not_trigger(self):
        for delta in (-121, 1):
            self.assertEqual(trigger_status(self.plan(), price=100, quoted_at=NOW+timedelta(seconds=delta), now=NOW), 'stale_quote')

    def test_llm_cannot_extend_ttl_or_expand_unbounded_range(self):
        with self.assertRaises(ValueError):
            create_plan(dict(lower_price=1,upper_price=1000,invalidate_below=.5,valid_hours=24,reason='매수'), reference_price=100,now=NOW,source_expires_at=NOW+timedelta(hours=1))
        self.assertEqual(validate_review(dict(decision='enter',reason='확인',valid_minutes=120), now=NOW, expires_at=NOW+timedelta(hours=1))['expires_at'], (NOW+timedelta(minutes=5)).isoformat())

    def test_unknown_decision_is_not_enter(self):
        with self.assertRaises(ValueError):
            validate_review(dict(decision='buy',reason='확인',valid_minutes=5),now=NOW,expires_at=NOW+timedelta(hours=1))

    def test_plan_trigger_review_and_retries_preserve_original(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from unittest.mock import patch, Mock
        from investment_agent.trading.entry.repository import EntryRepository
        from investment_agent.trading.entry.service import scan
        from investment_agent.trading.portfolio.signal_book import SignalBook, SignalBatch, SignalRecord
        from investment_agent.trading.portfolio.contracts import SecurityProposal
        original=SecurityProposal('AAPL',NOW.isoformat(),'open',.6,.8,.05,.1,('근거',),())
        batch=SignalBatch('batch',NOW.isoformat(),NOW.isoformat(),('AAPL',),('AAPL',),model_artifact_id='llm')
        record=SignalRecord('batch',original,NOW.isoformat(),(NOW+timedelta(hours=4)).isoformat(),'case')
        book=SignalBook((batch,),(record,))
        responses=[dict(lower_price=99,upper_price=101,invalidate_below=95,valid_hours=4,reason='눌림'),dict(decision='enter',reason='새 뉴스 확인',valid_minutes=5)]
        analyze=Mock(side_effect=responses)
        publish=Mock(return_value='ready-batch')
        with TemporaryDirectory() as temp, patch.dict('os.environ',{'AI_INVESTOR_RUNTIME_DB_PATH':str(Path(temp)/'runtime.sqlite3')}):
            store=EntryRepository()
            for minute in (0,2,3):
                now=NOW+timedelta(minutes=minute)
                scan(book=book,store=store,quotes={'AAPL':(100,now.isoformat())},analyze=analyze,publish=publish,now=now)
            self.assertEqual(analyze.call_count,2)
            self.assertEqual(publish.call_count,1)
            self.assertEqual(store.ready(now=NOW+timedelta(minutes=3))[0]['review']['original_decision'],original.to_dict())
            self.assertEqual(store.ready(now=NOW+timedelta(minutes=8)),[])
            from investment_agent.execution.db import ExecutionRepository
            from investment_agent.platform.db.sqlite import runtime_connection
            with runtime_connection() as connection:
                ExecutionRepository._save_record(connection,'signal_batch_execution','ready-batch',{'intent_id':'used'})
            self.assertEqual(store.ready(now=NOW+timedelta(minutes=3)),[])

    def test_successful_batch_publish_copies_only_selected_original(self):
        from tests.investment_agent.fakes import FakeDatabase
        from investment_agent.trading.repository import TradingRepository,SCHEMA,T_SIGNAL_RUNS,T_SIGNALS
        from investment_agent.trading.portfolio.signal_book import SignalRecord
        from investment_agent.trading.portfolio.contracts import SecurityProposal
        original=SecurityProposal('AAPL',NOW.isoformat(),'open',.6,.8,.05,.1,('근거',),())
        record=SignalRecord('source',original,NOW.isoformat(),(NOW+timedelta(hours=4)).isoformat(),'case')
        db=FakeDatabase()
        db.put(SCHEMA,T_SIGNAL_RUNS,[dict(batch_id='source',run_id='run',model_artifact_id='llm')])
        db.put(SCHEMA,T_SIGNALS,[dict(signal_id=record.signal_id,batch_id='source',security_id=1,proposal=original.to_dict(),case_key='case')])
        batch_id=TradingRepository(db).publish_entry_signal(record,review=dict(review_id='review',reviewed_at=NOW.isoformat(),expires_at=(NOW+timedelta(minutes=5)).isoformat()))
        self.assertTrue(batch_id.startswith('signal_batch_'))

    def test_long_analysis_does_not_block_another_stage(self):
        from threading import Event
        from types import SimpleNamespace
        from investment_agent.operations.harness.background import BackgroundStages
        background=BackgroundStages()
        release=Event()
        called=Event()
        def slow(context):
            release.wait(2)
            return 'done'
        try:
            stage=background.wrap(slow)
            context=SimpleNamespace(run_id='analysis',stage_id='analysis')
            self.assertEqual(stage(context).status,'waiting')
            other=background.wrap(lambda context: called.set())
            other(SimpleNamespace(run_id='watch',stage_id='watch'))
            self.assertTrue(called.wait(1))
            self.assertIn(('analysis','analysis'),background.pending)
        finally:
            release.set()
            background.executor.shutdown(wait=True)

    def test_expired_worker_cannot_overwrite_reclaimed_candidate(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from unittest.mock import patch
        from investment_agent.trading.entry.repository import EntryRepository
        with TemporaryDirectory() as temp, patch.dict('os.environ',{'AI_INVESTOR_RUNTIME_DB_PATH':str(Path(temp)/'runtime.sqlite3')}):
            first=EntryRepository()
            old=dict(signal_id='source',ticker='AAPL',status='new',next_check_at=NOW.isoformat())
            self.assertTrue(first.claim(old,now=NOW))
            second=EntryRepository()
            newer=second.candidates()[0]
            self.assertFalse(second.claim(newer,now=NOW+timedelta(minutes=1)))
            self.assertTrue(second.claim(newer,now=NOW+timedelta(minutes=11)))
            with self.assertRaisesRegex(ValueError,'superseded'):
                first.save(old)
