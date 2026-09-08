from __future__ import annotations

import unittest
from pathlib import Path


class ExecutionBoundaryTest(unittest.TestCase):
    def test_removed_alpaca_broker_has_no_runtime_or_configuration_surface(self):
        offenders: list[str] = []
        for path in Path("src").rglob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            if "alpaca" in text:
                offenders.append(path.as_posix())
        self.assertEqual(offenders, [])

    def test_lumibot_is_validation_only_and_not_an_execution_broker(self):
        offenders: list[str] = []
        for path in Path("src/investment_agent/execution").rglob("*.py"):
            if "lumibot" in path.read_text(encoding="utf-8").lower():
                offenders.append(path.as_posix())
        self.assertEqual(offenders, [])

    def test_toss_preview_is_read_only_and_live_client_is_gated(self):
        client = Path("src/investment_agent/execution/brokers/toss/client.py").read_text(encoding="utf-8")
        live = Path("src/investment_agent/execution/brokers/toss/orders.py").read_text(encoding="utf-8")
        entry = Path("src/investment_agent/operations/commands/toss_preview.py").read_text(encoding="utf-8")
        self.assertNotIn("def submit", client)
        self.assertNotIn("--submit", entry)
        self.assertNotIn("requests.post(\n        _ORDERS_URL", client)
        self.assertIn("NON_EXECUTABLE", entry)
        self.assertIn("assert_live_order_allowed", live)
        self.assertIn("assert_live_cancel_allowed", live)
        self.assertNotIn("confirmHighValueOrder\": True", live)

    def test_live_entry_requires_one_exact_approval_id(self):
        entry = Path("src/investment_agent/operations/commands/execute_toss_live.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('parser.add_argument("--approval-id", required=True)', entry)
        self.assertNotIn("--next-approved", entry)
        self.assertNotIn("approved_live_approvals", entry)

    def test_execution_schema_is_private_and_trading_schema_has_no_orders(self):
        """trading·execution은 Supabase 스키마가 아니라 실행 컴퓨터 로컬
        ``data/local/runtime/runtime.sqlite3``가 소유한다 — PostgREST에 노출되지 않는 로컬
        파일이라 RLS·GRANT로 지킬 대상 자체가 없다. 그 대신 trading 원장에 주문
        테이블이 섞이지 않는 것만 SQLite 선언에서 확인한다.
        """
        decisions_sql = Path("db/sqlite/runtime/v1/20_decisions.sql").read_text(encoding="utf-8")
        execution_sql = Path("db/sqlite/runtime/v1/30_execution.sql").read_text(encoding="utf-8")
        self.assertNotIn("CREATE TABLE IF NOT EXISTS orders", decisions_sql)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS fills", decisions_sql)
        for table in ("intents", "approvals", "order_attempts", "order_events", "orders", "fills"):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table} (", execution_sql)


if __name__ == "__main__":
    unittest.main()
