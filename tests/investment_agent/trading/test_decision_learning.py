from __future__ import annotations
import unittest
from investment_agent.trading.repository import TradingRepository, SCHEMA, T_SECURITY_DECISIONS, T_EVALUATIONS
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

    def test_cases_waiting_only_for_long_horizons_do_not_starve_recent_cases(self):
        """60일을 기다리는 오래된 판단이 limit을 채워도 5일이 찬 최근 판단이 먼저 나온다."""
        from datetime import datetime, timezone
        db=FakeDatabase(); repo=TradingRepository(db)
        waiting=[dict(case_key=f"old{i:03}",security_id=1,as_of_at="2026-08-01T00:00:00+00:00",status="completed") for i in range(250)]
        db.put(SCHEMA,T_SECURITY_DECISIONS,[*waiting,dict(case_key="recent",security_id=1,as_of_at="2026-09-10T00:00:00+00:00",status="completed")])
        db.put(SCHEMA,T_EVALUATIONS,[dict(case_key=row["case_key"],horizon_days=h) for row in waiting for h in (5,20)])
        rows=repo.evaluation_candidates(200, now=datetime(2026,9,23,tzinfo=timezone.utc))
        self.assertEqual(["recent"],[r["case_key"] for r in rows])

    def test_a_case_whose_horizon_has_not_passed_is_not_a_candidate(self):
        from datetime import datetime, timezone
        db=FakeDatabase(); repo=TradingRepository(db)
        db.put(SCHEMA,T_SECURITY_DECISIONS,[dict(case_key="fresh",security_id=1,as_of_at="2026-09-20T00:00:00+00:00",status="completed")])
        db.put(SCHEMA,T_EVALUATIONS,[])
        self.assertEqual([],repo.evaluation_candidates(200, now=datetime(2026,9,23,tzinfo=timezone.utc)))

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
        row=build_experience(Prices(),case,as_of_at=datetime(2026,1,8,tzinfo=timezone.utc),horizon_days=5)
        self.assertEqual(case,original)
        self.assertEqual(row["net_reward"],0)
        self.assertEqual(row["features"]["decision_action_avoid"],1)
        self.assertAlmostEqual(row["asset_return"],.05)
        self.assertIsNone(build_experience(Prices(),case,as_of_at=datetime(2026,1,7,tzinfo=timezone.utc),horizon_days=5))
        case["final_decision"]["signal"]="open"
        self.assertAlmostEqual(build_experience(Prices(),case,as_of_at=datetime(2026,1,8,tzinfo=timezone.utc),horizon_days=5)["net_reward"],.048)

    def test_split_does_not_create_fake_loss(self):
        # 저장 계약대로 분할 조정된 연속 종가를 준다(분할일에 가격이 끊기지 않는다).
        # 분할 비율이 수익률에 들어가면 여기서 +100%가 나온다.
        from datetime import date, datetime, timedelta, timezone
        from investment_agent.research.commands.build_decision_experiences import build_experience
        class Prices:
            def price_path(self,ticker,start_date,limit=80):
                return [dict(trade_date=str(date(2026,1,2)+timedelta(days=i)),close=100,split_ratio=2 if i==1 else None,div_amount=0) for i in range(6)]
        case=dict(case_key="c",ticker="ABC",as_of_at="2026-01-01T00:00:00+00:00",final_decision=dict(signal="hold",confidence=.8,probability_up=.5,expected_excess_return=0))
        row=build_experience(Prices(),case,as_of_at=datetime(2026,1,8,tzinfo=timezone.utc),horizon_days=5)
        self.assertAlmostEqual(row["asset_return"],0)
