from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from investment_agent.trading.supabase_repository import SupabaseRepository
from investment_agent.research.promotion.gate import EvaluationSummary, ManualPromotionGate
from investment_agent.research.rl.contracts import FeatureSnapshot, ForwardReturnLabel
from investment_agent.platform.db.postgres import Database
from investment_agent.platform.db.sqlite import runtime_connection


class _Response:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return self


class _Query:
    def __init__(self, owner, schema, table):
        self.owner = owner
        self.schema_name = schema
        self.table_name = table

    def _call(self, name, *args, **kwargs):
        self.owner.calls.append((self.schema_name, self.table_name, name, args, kwargs))
        return self

    def select(self, *args, **kwargs):
        return self._call("select", *args, **kwargs)

    def upsert(self, *args, **kwargs):
        self._call("upsert", *args, **kwargs)
        return _Response([])

    def insert(self, *args, **kwargs):
        self._call("insert", *args, **kwargs)
        return _Response(list(self.owner.rows.get((self.schema_name, self.table_name), ())))

    def update(self, *args, **kwargs):
        self._call("update", *args, **kwargs)
        return self

    def eq(self, *args, **kwargs):
        return self._call("eq", *args, **kwargs)

    def in_(self, *args, **kwargs):
        return self._call("in", *args, **kwargs)

    def gte(self, *args, **kwargs):
        return self._call("gte", *args, **kwargs)

    def lte(self, *args, **kwargs):
        return self._call("lte", *args, **kwargs)

    def order(self, *args, **kwargs):
        return self._call("order", *args, **kwargs)

    def limit(self, *args, **kwargs):
        return self._call("limit", *args, **kwargs)

    def range(self, *args, **kwargs):
        return self._call("range", *args, **kwargs)

    def execute(self):
        return _Response(list(self.owner.rows.get((self.schema_name, self.table_name), ())))


class _Schema:
    def __init__(self, owner, name):
        self.owner = owner
        self.name = name

    def table(self, name):
        return _Query(self.owner, self.name, name)

    def rpc(self, name, params):
        self.owner.rpc_calls.append((self.name, name, params))
        return _Response(self.owner.rpc_result)


class _Supabase:
    def __init__(self, rows=None, rpc_result=None):
        self.rows = rows or {}
        self.rpc_result = rpc_result or []
        self.calls = []
        self.rpc_calls = []

    def schema(self, name):
        return _Schema(self, name)


def _feature() -> FeatureSnapshot:
    return FeatureSnapshot(
        feature_version="rl-v1",
        as_of_at="2026-01-01T21:00:00+00:00",
        ticker="AAPL",
        available_at="2026-01-01T20:59:00+00:00",
        is_available=True,
        features={"momentum": 0.2},
        source_ids=("market:AAPL:2026-01-01",),
        provenance={"dataset": "market.prices_daily", "point_in_time": True},
    )


def _label() -> ForwardReturnLabel:
    return ForwardReturnLabel(
        feature_version="rl-v1",
        as_of_at="2026-01-01T21:00:00+00:00",
        ticker="AAPL",
        forward_end_at="2026-01-02T21:00:00+00:00",
        label_available_at="2026-01-02T21:05:00+00:00",
        forward_return=0.03,
        benchmark_forward_return=0.01,
    )


def _model_version(artifact_id: str = "artifact-1") -> dict:
    return {
        "artifact_id": artifact_id, "algorithm": "ridge", "feature_version": "v1",
        "artifact_uri": f"s3://bucket/{artifact_id}", "sha256": "a" * 64,
    }


def _seed_signal_run(*, batch_id: str, run_id: str, as_of_at: str) -> None:
    """signal_runs는 decision_runs를 FK로 참조한다 — 둘 다 최소한으로 심는다."""
    with runtime_connection() as connection:
        connection.execute(
            "INSERT INTO decision_runs(run_id,as_of_at,stage,status,candidate_tickers,finished_at) "
            "VALUES(?,?,?,?,?,?)",
            (run_id, as_of_at, "shadow", "completed", json.dumps(["AAPL"]), as_of_at),
        )
        connection.execute(
            "INSERT INTO signal_runs(batch_id,run_id,as_of_at,completed_at,requested_symbols,successful_symbols,is_complete) "
            "VALUES(?,?,?,?,?,?,?)",
            (batch_id, run_id, as_of_at, as_of_at, json.dumps(["AAPL"]), json.dumps(["AAPL"]), True),
        )


class RLRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "runtime.sqlite3"
        env = patch.dict("os.environ", {"AI_INVESTOR_RUNTIME_DB_PATH": str(self.path)})
        env.start()
        self.addCleanup(env.stop)

    def test_fundamentals_cutoff_reads_canonical_version_and_filing_tables(self):
        versions = [{
            "cik": "0000320193",
            "source_accession_no": "0000320193-26-000001",
            "fiscal_year": 2026,
            "fiscal_period": "Q2",
            "period_end": "2026-06-30",
            "source_filing_date": "2026-07-30",
            "revenue": 100,
        }]
        fake = _Supabase(rows={
            ("universe", "securities"): [{"ticker": "AAPL", "cik": "0000320193"}],
            ("fundamentals", "financials"): versions,
            ("fundamentals", "filings"): [{
                "accession_no": "0000320193-26-000001",
                "filing_date": "2026-07-30",
                "form_type": "10-Q",
                "available_at": "2026-07-30T20:00:00+00:00",
            }],
        })
        # 조회는 fundamentals 스키마의 owner가 한다.
        with patch("investment_agent.data.fundamentals.infrastructure.supabase.expectations.sb", fake):
            result = SupabaseRepository().fundamentals_pit(
                "AAPL", datetime(2026, 8, 1, tzinfo=timezone.utc), limit=12,
            )

        self.assertEqual(result, [{
            **versions[0],
            "accession_no": "0000320193-26-000001",
            "ticker": "AAPL",
            "filed_at": "2026-07-30",
            "form_type": "10-Q",
            "available_at": "2026-07-30T20:00:00+00:00",
        }])
        self.assertIn(
            ("fundamentals", "financials", "eq", ("cik", "0000320193"), {}),
            fake.calls,
        )

    def test_compact_membership_snapshot_is_returned_without_row_expansion(self):
        rows = [
            {
                "security_id": i, "valid_from": "2025-06-01", "valid_to": None,
                "source": "wikipedia_provisional", "source_hash": "b" * 64,
                "securities": {"ticker": f"X{i:03d}"},
            }
            for i in range(500)
        ]
        fake = _Supabase(rows={("universe", "index_memberships"): rows})
        # 조회는 universe 스키마의 owner가 한다 — 여기를 갈아끼워야 실제 DB를 때리지 않는다.
        with patch(
            "investment_agent.data.universe.persistence._database",
            Database(fake),
        ):
            snapshots = SupabaseRepository().historical_sp500_membership(
                start_date=date(2026, 1, 2),
                end_date=date(2026, 1, 31),
            )
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["effective_date"], "2026-01-02")
        self.assertEqual(snapshots[0]["member_count"], 500)
        self.assertEqual(len(snapshots[0]["symbols"]), 500)
        self.assertEqual(snapshots[0]["source"], "universe.index_memberships")
        self.assertEqual(64, len(snapshots[0]["source_hash"]))

    def test_signal_batch_exact_as_of_does_not_depend_on_completion_cutoff(self):
        _seed_signal_run(batch_id="batch-stable", run_id="run-stable", as_of_at="2026-08-22T12:00:00+00:00")
        batch_id = SupabaseRepository().signal_batch_id_for_as_of(
            "2026-08-22T12:00:00+00:00"
        )
        self.assertEqual(batch_id, "batch-stable")

    def test_signal_batch_exact_as_of_fails_on_ambiguity(self):
        _seed_signal_run(batch_id="batch-1", run_id="run-1", as_of_at="2026-08-22T12:00:00+00:00")
        _seed_signal_run(batch_id="batch-2", run_id="run-2", as_of_at="2026-08-22T12:00:00+00:00")
        with self.assertRaisesRegex(RuntimeError, "multiple"):
            SupabaseRepository().signal_batch_id_for_as_of(
                "2026-08-22T12:00:00+00:00"
            )

    def test_feature_and_label_queries_are_separate_and_cutoff_bound(self):
        with patch(
            "investment_agent.trading.supabase_repository.ResearchStore"
        ) as research_store:
            research_store.return_value.records.side_effect = lambda dataset, **kwargs: (
                [_feature().to_storage_row()] if dataset == "rl_feature_snapshots"
                else [_label().to_storage_row()] if dataset == "rl_training_labels"
                else []
            )
            features = SupabaseRepository().rl_feature_snapshot_rows(
                ("AAPL",),
                start_as_of="2026-01-01T00:00:00+00:00",
                end_as_of="2026-01-02T00:00:00+00:00",
                feature_version="rl-v1",
            )
            labels = SupabaseRepository().rl_training_label_rows(
                ("AAPL",),
                start_as_of="2026-01-01T00:00:00+00:00",
                end_as_of="2026-01-02T00:00:00+00:00",
                feature_version="rl-v1",
                label_cutoff_at="2026-01-03T00:00:00+00:00",
            )
        self.assertNotIn("forward_return", features[0])
        self.assertNotIn("features", labels[0])
        self.assertEqual(research_store.return_value.records.call_count, 2)

    def test_tampered_feature_hash_is_rejected_before_write(self):
        row = _feature().to_storage_row()
        row["input_hash"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "input_hash"):
            SupabaseRepository().save_rl_feature_snapshots([row])

    def test_membership_rows_keep_point_in_time_source(self):
        repository = SupabaseRepository()
        with patch.object(repository, "historical_sp500_membership", return_value=[{
            "effective_date": "2025-12-20",
            "symbols": ["AAPL", "MSFT"],
            "member_count": 2,
            "source": "official",
            "source_hash": "a" * 64,
        }]) as membership:
            rows = repository.rl_historical_membership_rows(
                start_as_of="2026-01-01T00:00:00+00:00",
                end_as_of="2026-02-01T00:00:00+00:00",
            )
        membership.assert_called_once_with(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 1),
        )
        self.assertEqual(rows[0]["source_kind"], "historical_point_in_time")
        self.assertEqual(rows[0]["source_id"], "a" * 64)

    def test_approved_promotion_appends_v1_audit_without_mutating_artifact(self):
        repository = SupabaseRepository()
        repository._trading_repository().record_model_version(_model_version())
        summary = EvaluationSummary(
            out_of_sample_days=90,
            walk_forward_windows=3,
            paper_days=0,
            excess_return=0.05,
            max_drawdown=-0.1,
            turnover=0.5,
            evaluation_count=4,
            evaluation_ids=(1, 2, 3, 4),
        )
        proposed = ManualPromotionGate().propose(
            "artifact-1", from_stage="shadow", to_stage="backtest", summary=summary,
        )
        confirmation = "PROMOTE artifact-1 shadow->backtest"
        approved = ManualPromotionGate.approve(
            proposed, approved_by="operator-1", confirmation=confirmation,
        )
        row = repository.approve_model_promotion(approved, confirmation=confirmation)
        self.assertEqual(row["status"], "approved")
        self.assertEqual("backtest", repository.model_stage("artifact-1"))

    def test_model_evaluation_summary_is_joined_by_artifact(self):
        SupabaseRepository()._trading_repository().record_model_version(_model_version())
        evaluations = []
        for evaluation_id, proposal_id, kind, start_at, end_at in (
            (1, "proposal-oos", "out_of_sample", "2026-01-01", "2026-03-03"),
            (2, "proposal-wf-1", "walk_forward", "2026-03-10", "2026-03-20"),
            (3, "proposal-wf-2", "walk_forward", "2026-04-10", "2026-04-20"),
            (4, "proposal-wf-3", "walk_forward", "2026-05-10", "2026-05-20"),
        ):
            evaluations.append({
                "evaluation_id": evaluation_id,
                "proposal_id": proposal_id,
                "evaluation_kind": kind,
                "start_at": f"{start_at}T00:00:00+00:00",
                "end_at": f"{end_at}T00:00:00+00:00",
                "total_return": 0.05,
                "benchmark_return": 0.02,
                "excess_return": 0.03,
                "max_drawdown": -0.05,
                "turnover": 0.4,
                "metrics": {},
                "research_only": False,
                "survivorship_check_passed": True,
                "leakage_check_passed": True,
                "data_integrity_check_passed": True,
                "evaluated_at": "2026-06-01T00:00:00+00:00",
                "model_artifact_id": "artifact-1",
            })
        with patch(
            "investment_agent.trading.supabase_repository.ResearchStore"
        ) as research_store:
            research_store.return_value.records.return_value = evaluations
            summary = SupabaseRepository().model_evaluation_summary("artifact-1")
        self.assertEqual(summary.out_of_sample_days, 61)
        self.assertEqual(summary.walk_forward_windows, 3)
        self.assertEqual(summary.evaluation_ids, (1, 2, 3, 4))

    def test_live_approval_requires_complete_exact_audit_transitions(self):
        repository = SupabaseRepository()
        trading = repository._trading_repository()

        def promote(artifact_id: str, from_stage: str, to_stage: str, *, when: str) -> None:
            trading.approve_model_promotion(
                audit_row={
                    "artifact_id": artifact_id, "from_stage": from_stage, "to_stage": to_stage,
                    "evidence": {}, "approved_by": "operator-1", "approved_at": when,
                    "confirmation_text": f"PROMOTE {artifact_id} {from_stage}->{to_stage}",
                },
                artifact_id=artifact_id, from_stage=from_stage, to_stage=to_stage,
            )

        trading.record_model_version(_model_version("artifact-1"))
        # 실제 상태 머신은 shadow->...->paper 없이 곧장 live로 승인하지 못한다.
        # "감사 기록은 있지만 중간 체인이 빠진" 손상 시나리오는 원장에 직접 심는다.
        with runtime_connection() as connection:
            connection.execute(
                "INSERT INTO model_promotions(artifact_id,from_stage,to_stage,status,evidence,approved_by,approved_at,confirmation_text) "
                "VALUES(?,?,?,?,?,?,?,?)",
                ("artifact-1", "paper", "live", "approved", "{}", "operator-1",
                 "2026-06-05T00:00:00+00:00", "PROMOTE artifact-1 paper->live"),
            )
        # 중간 단계 감사가 없다 — shadow->...->paper 체인이 빠졌다.
        self.assertFalse(repository.has_approved_promotion("artifact-1", "live"))

        trading.record_model_version(_model_version("artifact-2"))
        chain = (
            ("shadow", "backtest"), ("backtest", "out_of_sample"),
            ("out_of_sample", "walk_forward"), ("walk_forward", "paper"), ("paper", "live"),
        )
        for index, (from_stage, to_stage) in enumerate(chain):
            promote("artifact-2", from_stage, to_stage, when=f"2026-06-0{index + 1}T00:00:00+00:00")
        self.assertTrue(repository.has_approved_promotion("artifact-2", "live"))


if __name__ == "__main__":
    unittest.main()
