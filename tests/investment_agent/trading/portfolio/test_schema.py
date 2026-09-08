from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from investment_agent.trading.repository import TradingRepository


class FullPortfolioSchemaTest(unittest.TestCase):
    def _decisions_sql(self) -> str:
        return Path("db/sqlite/runtime/v1/20_decisions.sql").read_text(encoding="utf-8").lower()

    def _execution_sql(self) -> str:
        return Path("db/sqlite/runtime/v1/30_execution.sql").read_text(encoding="utf-8").lower()

    def _account_sql(self) -> str:
        return Path("db/sqlite/runtime/v1/10_account.sql").read_text(encoding="utf-8").lower()

    def test_signal_ledgers_exist_and_execution_owns_no_snapshot_identity_table(self):
        """trading·execution 모두 Supabase가 아니라 실행 컴퓨터 로컬
        runtime.sqlite3가 소유한다 — RLS로 지킬 대상이 없다. account/position
        snapshot은 execution 스키마의 전용 표가 아니라 `runtime_records`
        (record_type 구분)와 계좌 롤업 `account_snapshots`가 대신한다
        (execution/db.py 참고)."""
        decisions = self._decisions_sql()
        execution = self._execution_sql()
        for table in ("signal_runs", "signals"):
            self.assertIn(f"create table if not exists {table}", decisions)
        self.assertNotIn("create table if not exists account_snapshots", execution)
        self.assertNotIn("create table if not exists position_snapshots", execution)
        account = self._account_sql()
        self.assertIn("create table if not exists account_snapshots", account)
        # 하루 한 행으로 접으면 paper/live가 같은 날짜를 덮어쓴다. 키가 셋인지 본다.
        self.assertIn(
            "unique (broker_account_hash, execution_mode, snapshot_date)", account
        )
        self.assertIn("create table if not exists runtime_records", execution)

    def test_decision_records_bind_to_the_portfolio_snapshot_they_used(self):
        """trading은 execution snapshot을 가리키되 FK로 계층 방향을 뒤집지 않는다."""
        sql = self._decisions_sql()
        body = sql.split("create table if not exists decision_runs (", 1)[1].split(
            "\n);", 1
        )[0]
        self.assertIn("account_snapshot_id text", body)
        self.assertNotIn("portfolio_snapshot_id", body)
        self.assertNotIn("references", body.split("account_snapshot_id text", 1)[1].split("\n", 1)[0])

        proposal = sql.split(
            "create table if not exists portfolio_proposals (", 1
        )[1].split("\n);", 1)[0]
        self.assertNotIn("portfolio_snapshot_id", proposal)
        for column in ("weights", "confidence", "reasoning", "case_keys"):
            self.assertRegex(proposal, rf"\b{column}\s+\w+")

    def test_decision_lineage_uses_composite_unique_indexes_and_fks(self):
        sql = self._decisions_sql()
        self.assertIn("unique (proposal_id, run_id)", sql)
        self.assertIn("unique (risk_decision_id, proposal_id)", sql)
        self.assertIn("portfolio_decisions_proposal_run_fkey", sql)
        self.assertIn("foreign key (proposal_id, run_id)", sql)
        self.assertIn("portfolio_decisions_risk_proposal_fkey", sql)
        self.assertIn("foreign key (risk_decision_id, proposal_id)", sql)

    def test_model_versions_table_has_no_denormalized_stage_column(self):
        sql = self._decisions_sql()
        model_versions = sql.split(
            "create table if not exists model_versions (", 1
        )[1].split("\n);", 1)[0]
        self.assertNotIn("stage", model_versions)
        self.assertIn("from_stage = 'shadow'        and to_stage = 'backtest'", sql)

    def test_model_promotion_is_compare_and_swap_against_current_stage(self):
        """Postgres `approve_model_promotion` 함수의 FOR UPDATE 잠금을 대신해,
        로컬 SQLite에서는 `LocalTradingDatabase.rpc()`가 현재 stage를 다시 읽고
        `p_from_stage`와 어긋나면 거부하는 것으로 같은 compare-and-swap을 보장한다."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.sqlite3"
            with patch.dict("os.environ", {"AI_INVESTOR_RUNTIME_DB_PATH": str(path)}):
                repo = TradingRepository()
                repo.record_model_version({
                    "artifact_id": "artifact-1", "algorithm": "ridge", "feature_version": "v1",
                    "artifact_uri": "s3://bucket/artifact-1", "sha256": "a" * 64,
                })
                self.assertEqual("shadow", repo.current_model_stage("artifact-1"))
                audit_row = {
                    "evidence": {"note": "ok"}, "approved_by": "operator",
                    "approved_at": "2026-09-06T00:00:00+00:00", "confirmation_text": "yes",
                }
                approved = repo.approve_model_promotion(
                    audit_row=audit_row, artifact_id="artifact-1",
                    from_stage="shadow", to_stage="backtest",
                )
                self.assertEqual("approved", approved["status"])
                self.assertEqual("backtest", repo.current_model_stage("artifact-1"))
                with self.assertRaises(ValueError):
                    repo.approve_model_promotion(
                        audit_row={**audit_row, "approved_at": "2026-09-06T00:00:01+00:00"},
                        artifact_id="artifact-1", from_stage="shadow", to_stage="backtest",
                    )


if __name__ == "__main__":
    unittest.main()
