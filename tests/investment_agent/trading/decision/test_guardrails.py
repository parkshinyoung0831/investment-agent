"""Phase 1에 주문 표면이 생기지 않고 DB가 비공개인지 검증한다."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from investment_agent.trading.decision.shadow_daily import make_case_key
from investment_agent.trading.decision.policy import ShadowPolicy
from investment_agent.data.market import REFERENCE_PRICE_TICKERS
from investment_agent.data.market import persistence as market_db

ROOT = Path(__file__).resolve().parents[4]


class GuardrailTest(unittest.TestCase):
    def test_schema_is_service_only_and_has_no_order_table(self):
        """trading은 Supabase 스키마가 아니라 실행 컴퓨터 로컬 runtime.sqlite3가
        소유한다 — PostgREST에 노출되지 않는 파일이라 RLS로 지킬 대상이 없다.
        여기서는 주문·체결 표가 섞이지 않는 것만 확인한다."""
        sql = (ROOT / "db" / "sqlite" / "runtime" / "v1" / "20_decisions.sql").read_text(encoding="utf-8")
        lowered = sql.lower()
        self.assertNotIn("create table if not exists orders", lowered)
        self.assertNotIn("create table if not exists fills", lowered)
        self.assertIn("create table if not exists model_versions", lowered)
        self.assertIn("create table if not exists model_promotions", lowered)
        self.assertIn("create table if not exists decision_runs", lowered)

    def test_case_key_is_human_readable_and_deterministic(self):
        when = datetime(2026, 8, 21, 1, 2, 3, tzinfo=timezone.utc)
        key = make_case_key("AAPL", when, 20, ShadowPolicy())
        self.assertEqual(key, "AAPL__2026-08-20__20d__evidence-first-v1")

    def test_spy_is_price_only_reference(self):
        self.assertEqual(REFERENCE_PRICE_TICKERS, ("SPY",))
        with mock.patch.object(market_db, "universe_company_tickers", return_value=["AAPL"]):
            self.assertEqual(market_db.universe_tracked(), ["AAPL", "SPY"])


if __name__ == "__main__":
    unittest.main()
