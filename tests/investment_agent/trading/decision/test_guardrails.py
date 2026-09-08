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

    def test_reference_tickers_are_price_only(self):
        """벤치마크는 시세만 들고 있는 대상이다 — 판단 유니버스에 섞이지 않는다.

        목록을 정확한 튜플로 못박으면 벤치마크를 하나 늘릴 때마다 이 검사가 막는다.
        실제로 자산배분 전략이 쓰는 ETF 21종을 넣을 때 그렇게 걸렸다. 지켜야 할 것은
        목록의 내용이 아니라 "시세 대상에만 더해지고 판단 대상은 그대로"라는 성질이다.
        """
        self.assertIn("SPY", REFERENCE_PRICE_TICKERS)
        with mock.patch.object(market_db, "universe_company_tickers", return_value=["AAPL"]):
            tracked = market_db.universe_tracked()
        # 시세 대상 = 판단 대상 + 벤치마크. 그 차이가 정확히 벤치마크여야 한다.
        self.assertEqual(sorted({"AAPL", *REFERENCE_PRICE_TICKERS}), tracked)
        self.assertEqual(set(REFERENCE_PRICE_TICKERS), set(tracked) - {"AAPL"})


if __name__ == "__main__":
    unittest.main()
