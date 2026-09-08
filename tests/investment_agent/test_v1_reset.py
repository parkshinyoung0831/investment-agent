"""빈 DB 재구축 도구가 구 스키마에 기대지 않는지 확인한다."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class V1ResetContractTest(unittest.TestCase):
    def test_execution_binds_to_trading_decisions_without_a_cross_schema_fk(self) -> None:
        """trading·execution은 둘 다 로컬 runtime.sqlite3 소유라 물리적으로 같은 파일에
        있지만, execution이 trading의 risk_decision_id에 FK를 걸지는 않는다 —
        판단 원장(trading)이 실행 원장(execution)에 의존하지 않는 방향을 지키기 위해
        결속은 UNIQUE 제약과 ExecutionRepository의 애플리케이션 검증이 대신한다."""
        sql = (ROOT / "db" / "sqlite" / "runtime" / "v1" / "30_execution.sql").read_text(encoding="utf-8")
        self.assertIn("risk_decision_id TEXT NOT NULL UNIQUE", sql)
        self.assertNotIn("REFERENCES trading.", sql)
        self.assertNotIn("REFERENCES ai_investor.", sql)

    def test_reset_scope_excludes_supabase_managed_schemas(self) -> None:
        from scripts.v1_reset import APP_SCHEMAS, POSTGREST_SCHEMAS, V1_SCHEMAS

        # notifications는 더 이상 Supabase 표가 아니다(subscriptions는
        # notifications/subscriptions.py의 KIND_ENV로 이동).
        self.assertEqual(len(V1_SCHEMAS), 6)
        self.assertNotIn("notifications", V1_SCHEMAS)
        self.assertFalse({"auth", "storage", "realtime", "vault"} & set(APP_SCHEMAS))
        self.assertFalse({"trading", "execution", "operations"} & set(APP_SCHEMAS))
        self.assertTrue(set(V1_SCHEMAS) <= set(POSTGREST_SCHEMAS))


if __name__ == "__main__":
    unittest.main()
