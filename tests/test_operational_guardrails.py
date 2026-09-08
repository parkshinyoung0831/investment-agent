"""권한·빈 응답·지연 DB 초기화 같은 운영 안전장치 회귀 테스트."""
from __future__ import annotations

import logging
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from investment_agent.platform.db import postgres as common_supabase
from investment_agent.data.macro.infrastructure.fetch import safe_fetch
from investment_agent.data.market.commands import market_backfill, market_daily


class LazySupabaseClientTest(unittest.TestCase):
    def test_service_client_is_not_needed_until_attribute_access(self):
        lazy = common_supabase._LazyServiceClient()
        fake = mock.Mock()
        fake.schema.return_value = "schema-result"

        with mock.patch.object(common_supabase, "service_client", return_value=fake) as factory:
            factory.assert_not_called()
            self.assertEqual(lazy.schema("market"), "schema-result")

        factory.assert_called_once_with()


class EmptySourceTest(unittest.TestCase):
    def test_macro_empty_series_counts_as_failure(self):
        output, failures = safe_fetch(
            logging.getLogger(__name__),
            [{"series_id": "EMPTY"}],
            lambda _: pd.Series(dtype=float),
        )

        self.assertTrue(output["EMPTY"].empty)
        self.assertEqual(failures[0]["series_id"], "EMPTY")

    def test_market_daily_empty_universe_is_failure(self):
        with (
            mock.patch("investment_agent.data.market.persistence.universe_tracked", return_value=[]),
            mock.patch("investment_agent.data.market.persistence.latest_price_date", return_value=None),
            self.assertRaisesRegex(RuntimeError, "is_tracked=true returned no rows"),
        ):
            market_daily.main([])

    def test_market_backfill_empty_response_is_failure(self):
        with (
            mock.patch("investment_agent.data.market.persistence.universe_missing_prices", return_value=["AAPL"]),
            mock.patch("investment_agent.data.market.infrastructure.sources.yahoo.download_ohlcv", return_value=[]),
            self.assertRaisesRegex(RuntimeError, "빈 응답"),
        ):
            market_backfill._backfill_prices(30, "missing")


class SqlContractTest(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def _read(self, relative: str) -> str:
        return (self.ROOT / relative).read_text(encoding="utf-8")

    def test_macro_schema_revokes_public_writes(self):
        sql = self._read("db/postgres/v1/40_macro.sql")

        self.assertIn(
            "REVOKE ALL ON SCHEMA macro FROM PUBLIC, anon, authenticated",
            sql,
        )
        self.assertNotIn(
            "GRANT ALL    ON TABLES    TO anon, authenticated, service_role",
            sql,
        )

    def test_gurus_manager_contract_is_code_owned(self):
        """추적 대상과 화면 해석은 코드 설정, SEC filing/position만 DB가 소유한다."""
        sql = self._read("db/postgres/v1/50_institutional.sql")
        code = self._read("src/investment_agent/data/institutional/domain/managers.py")

        self.assertNotIn("CREATE TABLE IF NOT EXISTS institutional.managers", sql)
        self.assertIn("MANAGER_CATALOG", code)
        self.assertIn("BLIND_SPOT_LABELS", code)
        self.assertIn('"copyable_core"', code)
        self.assertIn('"market_signal"', code)
        self.assertIn('"contrarian_value"', code)

    def test_market_breadth_uses_requested_window(self):
        sql = self._read("db/postgres/v1/20_market.sql")

        self.assertIn("market.prices_daily", sql)
        self.assertIn("prices_daily_trade_date_idx", sql)

    def test_macro_change_detection_uses_stable_pagination_order(self):
        code = self._read("src/investment_agent/data/macro/repository.py")

        self.assertIn('order_by="series_code"', code)
        self.assertIn('order_by="series_key,observation_date,available_at"', code)


if __name__ == "__main__":
    unittest.main()
