from __future__ import annotations
import unittest
from investment_agent.trading.repository import TradingRepository, SCHEMA, T_SECURITY_DECISIONS, T_EVALUATIONS, T_PROPOSALS
from tests.investment_agent.fakes import FakeDatabase

class QueueTest(unittest.TestCase):
    def test_completed_two_hundred_do_not_starve_next_case(self):
        db=FakeDatabase(); repo=TradingRepository(db)
        db.put(SCHEMA,T_SECURITY_DECISIONS,[dict(case_key=f"c{i:03}",security_id=1,as_of_at="2026-01-01",status="completed") for i in range(201)])
        db.put(SCHEMA,T_EVALUATIONS,[dict(case_key=f"c{i:03}",horizon_days=h) for i in range(200) for h in (5,20,60)])
        self.assertEqual(["c200"],[r["case_key"] for r in repo.evaluation_candidates(200)])

    def test_local_queue_filters_before_limit(self):
        import sqlite3
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from investment_agent.trading.local_store import LocalTradingDatabase
        with TemporaryDirectory() as temp:
            path=Path(temp)/"ledger.sqlite3"
            with sqlite3.connect(path) as connection:
                connection.execute("CREATE TABLE security_decisions(case_key TEXT,as_of_at TEXT,status TEXT,final_decision JSON)")
                connection.execute("CREATE TABLE decision_evaluations(case_key TEXT,horizon_days INTEGER,PRIMARY KEY(case_key,horizon_days))")
                connection.executemany("INSERT INTO security_decisions VALUES(?,'2026-01-01','completed','{}')",[(f"c{i:03}",) for i in range(201)])
                connection.executemany("INSERT INTO decision_evaluations VALUES(?,?)",[(f"c{i:03}",h) for i in range(200) for h in (5,20,60)])
            connection.close()
            rows=TradingRepository(LocalTradingDatabase(path)).evaluation_candidates(200)
            self.assertEqual(["c200"],[row["case_key"] for row in rows])

    def test_batch_is_construction_metadata_not_analysis_run(self):
        db=FakeDatabase(); repo=TradingRepository(db)
        db.put(SCHEMA,T_PROPOSALS,[dict(proposal_id="p",stage="live",run_id="construction",metadata={"active_batch_id":"batch"})])
        self.assertEqual(["p"],repo.live_proposal_ids_for_batch("batch"))

class ExperienceTest(unittest.TestCase):
    def test_unbought_original_and_flat_actions_and_future_exclusion(self):
        from copy import deepcopy
        from datetime import datetime, timezone, date, timedelta
        from investment_agent.research.commands.build_decision_experiences import build_experience
        class Prices:
            def price_path(self,ticker,start_date,limit=80):
                return [dict(trade_date=str(date(2026,1,2)+timedelta(days=i)),close=100+i,div_amount=0) for i in range(6)]
        proposal=dict(signal="avoid",confidence=.8,probability_up=.2,expected_excess_return=-.03)
        case=dict(case_key="c",ticker="ABC",as_of_at="2026-01-01T22:00:00+00:00",final_decision=proposal)
        original=deepcopy(case)
        row=build_experience(Prices(),case,as_of_at=datetime(2026,1,8,tzinfo=timezone.utc))
        self.assertEqual(case,original)
        self.assertEqual(row["net_reward"],0)
        self.assertEqual(row["features"]["decision_action_avoid"],1)
        self.assertAlmostEqual(row["asset_return"],.05)
        self.assertIsNone(build_experience(Prices(),case,as_of_at=datetime(2026,1,7,tzinfo=timezone.utc)))
        case["final_decision"]["signal"]="open"
        self.assertAlmostEqual(build_experience(Prices(),case,as_of_at=datetime(2026,1,8,tzinfo=timezone.utc))["net_reward"],.048)

    def test_store_preserves_first_observation_and_reader_cuts_future_labels(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from unittest.mock import patch
        from datetime import datetime, timezone
        from investment_agent.research.storage.repository import ResearchStore
        from investment_agent.trading.supabase_repository import SupabaseRepository
        with TemporaryDirectory() as temp:
            store=ResearchStore(Path(temp)/"research.duckdb")
            first=dict(record_key="c",case_key="c",ticker="ABC",as_of_at="2026-01-01T00:00:00+00:00",available_at="2026-01-08T00:00:00+00:00",net_reward=.04)
            with patch("investment_agent.trading.supabase_repository.ResearchStore",return_value=store):
                repo=SupabaseRepository()
                repo.save_decision_experiences([first])
                repo.save_decision_experiences([{**first,"net_reward":99}])
                self.assertEqual(repo.decision_experience_rows(),[first])
                self.assertEqual(repo.decision_experience_rows(as_of_at=datetime(2026,1,7,tzinfo=timezone.utc)),[])
            store.upsert_records("decision_experiences",[{**first,"net_reward":99}],key="record_key",ignore_existing=True)
            self.assertEqual(store.records("decision_experiences"),[first])

    def test_split_does_not_create_fake_loss(self):
        from datetime import date, datetime, timedelta, timezone
        from investment_agent.research.commands.build_decision_experiences import build_experience
        class Prices:
            def price_path(self,ticker,start_date,limit=80):
                return [dict(trade_date=str(date(2026,1,2)+timedelta(days=i)),close=100 if i==0 else 50,split_ratio=2 if i==1 else None,div_amount=0) for i in range(6)]
        case=dict(case_key="c",ticker="ABC",as_of_at="2026-01-01T00:00:00+00:00",final_decision=dict(signal="hold",confidence=.8,probability_up=.5,expected_excess_return=0))
        row=build_experience(Prices(),case,as_of_at=datetime(2026,1,8,tzinfo=timezone.utc))
        self.assertAlmostEqual(row["asset_return"],0)
