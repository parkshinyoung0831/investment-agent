"""부분 성공을 성공으로 승격하지 않고, 거절이 주문으로 새지 않는다."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.trading.run_context import shadow_context
from investment_agent.trading.repository import (
    SCHEMA,
    T_ATTRIBUTION_REPORTS,
    T_EVALUATIONS,
    T_MODEL_PROMOTIONS,
    T_MODEL_VERSIONS,
    T_POLICIES,
    T_PORTFOLIO_DECISIONS,
    T_RISK_DECISIONS,
    T_RUNS,
    T_SECURITY_DECISIONS,
    T_SIGNAL_RUNS,
    T_SIGNALS,
    TradingRepository,
)
from tests.investment_agent.fakes import FakeDatabase

NOW = datetime(2026, 9, 5, 13, 30, tzinfo=timezone.utc)


class RunLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = FakeDatabase()
        self.repo = TradingRepository(self.db)

    def test_a_new_run_is_open(self) -> None:
        self.repo.start_run(run_id="r1", as_of_at=NOW, context=shadow_context(),
                            candidate_tickers=["AAPL"])
        (_key, rows, _conflict) = self.db.upserts[0]
        self.assertEqual("running", rows[0]["status"])
        self.assertNotIn("finished_at", rows[0])

    def test_a_failed_run_must_say_why(self) -> None:
        with self.assertRaises(ValueError):
            self.repo.finish_run("r1", status="failed")

    def test_a_successful_run_must_not_carry_a_failure_reason(self) -> None:
        """둘 다 있으면 나중에 읽는 사람이 어느 쪽을 믿을지 모른다."""
        with self.assertRaises(ValueError):
            self.repo.finish_run("r1", status="completed", failure_reason="oops")

    def test_partial_is_a_real_status_not_a_rounded_success(self) -> None:
        """completed로 적으면 빠진 종목이 '신호 없음'으로 보인다."""
        self.repo.finish_run("r1", status="partial", finished_at=NOW)
        (_key, rows, _conflict) = self.db.upserts[0]
        self.assertEqual("partial", rows[0]["status"])
        self.assertIsNotNone(rows[0]["finished_at"])

    def test_a_run_cannot_be_finished_as_running(self) -> None:
        with self.assertRaises(ValueError):
            self.repo.finish_run("r1", status="running")


class PolicyAndModelRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = FakeDatabase()
        self.repo = TradingRepository(self.db)

    def test_policy_is_owned_by_trading_repository(self) -> None:
        self.assertEqual(1, self.repo.record_policy({"policy_key": "default", "policy_version": 1}))
        table, row = self.db.inserts[0]
        self.assertEqual((SCHEMA, T_POLICIES), table)
        self.assertEqual("default", row["policy_key"])

    def test_model_version_drops_non_ledger_payload(self) -> None:
        self.repo.record_model_version({
            "artifact_id": "a1", "artifact_uri": "file:///model", "sha256": "a" * 64,
            "algorithm": "rule", "feature_version": "v1", "private_weights": [1, 2],
        })
        table, rows = self.db.inserts[0]
        self.assertEqual((SCHEMA, T_MODEL_VERSIONS), table)
        self.assertNotIn("private_weights", rows)

    def test_model_version_reader_is_point_lookup(self) -> None:
        self.db.put(SCHEMA, T_MODEL_VERSIONS, [{"artifact_id": "a1", "stage": "shadow"}])
        self.assertEqual({"artifact_id": "a1", "stage": "shadow"}, self.repo.model_version("a1"))

    def test_model_promotion_reader_is_ordered_and_scoped(self) -> None:
        self.db.put(SCHEMA, T_MODEL_PROMOTIONS, [
            {"promotion_id": 2, "artifact_id": "a1", "created_at": "2026-02-01"},
            {"promotion_id": 1, "artifact_id": "a1", "created_at": "2026-01-01"},
        ])
        rows = self.repo.model_promotions("a1")
        self.assertEqual([1, 2], [row["promotion_id"] for row in rows])

    def test_decision_exists_ignores_failed_rows(self) -> None:
        self.db.put(SCHEMA, T_SECURITY_DECISIONS, [
            {"case_key": "failed", "status": "failed"},
            {"case_key": "done", "status": "completed"},
        ])
        self.assertFalse(self.repo.decision_exists("failed"))
        self.assertTrue(self.repo.decision_exists("done"))

    def test_signal_batch_writer_keeps_batch_and_signal_identity(self) -> None:
        self.repo.record_signal_batch(
            batch={"batch_id": "b1", "run_id": "r1"},
            signals=[{"signal_id": "s1", "batch_id": "b1", "security_id": 1}],
        )
        self.assertEqual((SCHEMA, T_SIGNAL_RUNS), self.db.inserts[0][0])
        self.assertEqual((SCHEMA, T_SIGNALS), self.db.inserts[1][0])

    def test_signal_batch_reader_rejects_ambiguous_as_of(self) -> None:
        self.db.put(SCHEMA, T_SIGNAL_RUNS, [
            {"batch_id": "b1", "as_of_at": NOW.isoformat()},
            {"batch_id": "b2", "as_of_at": NOW.isoformat()},
        ])
        with self.assertRaisesRegex(RuntimeError, "multiple signal batches"):
            self.repo.signal_batch_id_for_as_of(NOW)

    def test_execution_ready_reader_ignores_incomplete_or_expired_batches(self) -> None:
        self.db.put(SCHEMA, T_SIGNAL_RUNS, [
            {"batch_id": "expired", "is_complete": True, "completed_at": NOW.isoformat()},
            {"batch_id": "ready", "is_complete": True, "completed_at": NOW.isoformat()},
            {"batch_id": "incomplete", "is_complete": False, "completed_at": NOW.isoformat()},
        ])
        self.db.put(SCHEMA, T_SIGNALS, [
            {"signal_id": "old", "batch_id": "expired", "expires_at": "2026-09-04T00:00:00+00:00"},
            {"signal_id": "live", "batch_id": "ready", "expires_at": "2026-09-06T00:00:00+00:00"},
        ])
        self.assertEqual("ready", self.repo.latest_execution_ready_batch_id(as_of_at=NOW))

    def test_proposal_and_risk_readers_are_v1_scoped(self) -> None:
        self.db.put(SCHEMA, "portfolio_proposals", [{"proposal_id": "p1", "run_id": "r1"}])
        self.db.put(SCHEMA, T_RISK_DECISIONS, [{"risk_decision_id": "rd1", "proposal_id": "p1"}])
        self.assertEqual("r1", self.repo.portfolio_proposal("p1")["run_id"])
        self.assertEqual("p1", self.repo.risk_decision("rd1")["proposal_id"])

    def test_evaluation_writer_and_candidate_reader_use_v1_tables(self) -> None:
        self.repo.record_evaluation({"case_key": "c1", "horizon_days": 20})
        self.assertEqual((SCHEMA, T_EVALUATIONS), self.db.upserts[0][0])
        self.db.put(SCHEMA, T_SECURITY_DECISIONS, [
            {"case_key": "c1", "security_id": 1, "as_of_at": NOW.isoformat(), "status": "completed"},
            {"case_key": "failed", "security_id": 2, "as_of_at": NOW.isoformat(), "status": "failed"},
        ])
        rows = self.repo.evaluation_candidates()
        self.assertEqual(["c1"], [row["case_key"] for row in rows])

    def test_evaluated_memory_reader_joins_only_evaluated_cases(self) -> None:
        self.db.put(SCHEMA, T_SECURITY_DECISIONS, [
            {"case_key": "c1", "security_id": 1, "as_of_at": "2026-01-01T00:00:00+00:00", "status": "completed", "final_decision": {}},
            {"case_key": "c2", "security_id": 1, "as_of_at": "2026-01-02T00:00:00+00:00", "status": "abstained", "final_decision": {}},
        ])
        self.db.put(SCHEMA, T_EVALUATIONS, [
            {"case_key": "c1", "horizon_days": 20, "evaluated_at": "2026-01-03T00:00:00+00:00"},
        ])
        rows = self.repo.evaluated_memory_rows(security_id=1)
        self.assertEqual(["c1"], [row["case_key"] for row in rows])

    def test_attribution_report_writer_uses_v1_owner(self) -> None:
        self.repo.record_attribution_report({
            "period_start": "2026-01-01",
            "period_end": "2026-01-01",
            "execution_mode": "paper",
            "breakdown": {},
        })
        self.assertEqual((SCHEMA, T_ATTRIBUTION_REPORTS), self.db.upserts[0][0])


class DecisionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = FakeDatabase()
        self.repo = TradingRepository(self.db)

    def _row(self, **overrides: object) -> dict:
        row = {
            "case_key": "1:2026-09-05:h20:abc", "run_id": "r1", "security_id": 1,
            "as_of_at": NOW.isoformat(), "horizon_days": 20, "policy_key": "default",
            "policy_version": 1, "model_provider": "anthropic", "model_name": "claude-opus-5",
            "source_kind": "live_shadow", "status": "completed",
            "context_hash": "a" * 64, "final_decision": {"action": "buy"},
            "failure_reason": None,
        }
        row.update(overrides)
        return row

    def test_a_failed_decision_carries_no_payload(self) -> None:
        with self.assertRaises(ValueError):
            self.repo.record_decision(self._row(status="failed", final_decision={"action": "buy"}))

    def test_a_completed_decision_needs_a_payload(self) -> None:
        with self.assertRaises(ValueError):
            self.repo.record_decision(self._row(final_decision=None))

    def test_an_abstention_still_records_why(self) -> None:
        """'판단하지 않음'도 판단이다. 근거가 없으면 나중에 되짚을 수 없다."""
        with self.assertRaises(ValueError):
            self.repo.record_decision(self._row(status="abstained", final_decision=None))
        self.repo.record_decision(
            self._row(status="abstained", final_decision={"reason": "insufficient_data"})
        )
        self.assertEqual(1, len(self.db.upserts))

    def test_the_case_key_is_the_conflict_key(self) -> None:
        self.repo.record_decision(self._row())
        (_key, _rows, conflict) = self.db.upserts[0]
        self.assertEqual("case_key", conflict)


class SignalExpiryTest(unittest.TestCase):
    def test_expired_signals_are_not_returned(self) -> None:
        """어제 신호가 오늘 판단에 섞이면 예외 없이 틀린다."""
        db = FakeDatabase()
        db.put(SCHEMA, T_SIGNALS, [
            {"signal_id": "s1", "batch_id": "b1", "case_key": None, "security_id": 1,
             "proposal": {}, "recorded_at": (NOW - timedelta(days=2)).isoformat(),
             "expires_at": (NOW - timedelta(days=1)).isoformat()},
            {"signal_id": "s2", "batch_id": "b1", "case_key": None, "security_id": 2,
             "proposal": {}, "recorded_at": NOW.isoformat(),
             "expires_at": (NOW + timedelta(days=1)).isoformat()},
        ])
        live = TradingRepository(db).live_signals(now=NOW)
        self.assertEqual(["s2"], [row["signal_id"] for row in live])


class RiskDecisionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = FakeDatabase()
        self.repo = TradingRepository(self.db)

    def test_a_rejection_cannot_carry_weights(self) -> None:
        """거절인데 비중이 남아 있으면 그것을 주문으로 읽는 길이 열린다."""
        with self.assertRaises(ValueError):
            self.repo.record_risk_decision({
                "risk_decision_id": "rd1", "proposal_id": "p1", "is_approved": False,
                "approved_weights": {"AAPL": 0.1},
            })

    def test_an_approval_needs_weights(self) -> None:
        with self.assertRaises(ValueError):
            self.repo.record_risk_decision({
                "risk_decision_id": "rd1", "proposal_id": "p1", "is_approved": True,
                "approved_weights": None,
            })

    def test_an_approval_with_weights_is_stored(self) -> None:
        self.repo.record_risk_decision({
            "risk_decision_id": "rd1", "proposal_id": "p1", "is_approved": True,
            "approved_weights": {"AAPL": 0.1},
        })
        self.assertEqual(1, len(self.db.upserts))


class AdoptedWeightsTest(unittest.TestCase):
    def _db(self, *, approved: dict | None, status: str = "approved") -> FakeDatabase:
        db = FakeDatabase()
        db.put(SCHEMA, T_RUNS, [
            {"run_id": "r1", "stage": "shadow", "as_of_at": NOW.isoformat()},
        ])
        db.put(SCHEMA, T_PORTFOLIO_DECISIONS, [
            {"decision_id": "d1", "run_id": "r1", "created_at": NOW.isoformat(),
             "status": status, T_RISK_DECISIONS: {"approved_weights": approved}},
        ])
        return db

    def test_the_latest_approved_weights_are_returned(self) -> None:
        repo = TradingRepository(self._db(approved={"AAPL": 0.1}))
        self.assertEqual({"AAPL": 0.1}, repo.latest_adopted_weights(stage="shadow"))

    def test_never_adopted_is_none_not_empty(self) -> None:
        """`{}`(빈 포트폴리오)와 `None`(채택된 적 없음)은 위험 엔진에서 다르게 다뤄진다."""
        db = FakeDatabase()
        db.put(SCHEMA, T_RUNS, [])
        self.assertIsNone(TradingRepository(db).latest_adopted_weights(stage="shadow"))

    def test_an_empty_adopted_portfolio_is_an_empty_dict(self) -> None:
        repo = TradingRepository(self._db(approved={}))
        self.assertEqual({}, repo.latest_adopted_weights(stage="shadow"))

    def test_rejected_portfolios_are_not_adopted(self) -> None:
        repo = TradingRepository(self._db(approved={"AAPL": 0.1}, status="rejected"))
        self.assertIsNone(repo.latest_adopted_weights(stage="shadow"))


if __name__ == "__main__":
    unittest.main()
