"""활성 provider의 오프라인 fail-closed 계약 테스트."""
from __future__ import annotations

import json
import re
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import pandas as pd

from investment_agent.data.macro.infrastructure.releases.sources import actuals
from investment_agent.data.macro.domain.catalog import MARKET_INDICATOR_CATALOG, SOURCE_CODES
from investment_agent.data.macro.domain.releases.release_catalog import series_config, series_ids
from investment_agent.data.macro.infrastructure.sources import market, web, yfinance


_START = date(2026, 8, 1)
_END = date(2026, 8, 22)
_INDEX = pd.DatetimeIndex(["2026-08-20", "2026-08-21"])
_ROOT = Path(__file__).resolve().parents[1]


class ActiveSeedContractTest(unittest.TestCase):
    """운영 seed의 provider 설정이 코드 registry와 어긋나지 않는지 검사한다."""

    def test_macro_seed_uses_registered_parsers_and_fields(self):
        rows = [
            (str(row["series_id"]), str(row["source"]), dict(row["source_params"]))
            for row in MARKET_INDICATOR_CATALOG
        ]
        self.assertTrue(rows)
        for series_id, source, params in rows:
            self.assertIn(source, SOURCE_CODES)
            if source == "web_crawling":
                self.assertIn(
                    (params.get("source"), params.get("parser")),
                    web.PARSERS,
                    series_id,
                )
            elif source == "market":
                self.assertEqual(series_id, "BREADTH_200DMA")
                self.assertEqual(params.get("ma_window"), 200)
                self.assertEqual(params.get("min_periods"), 180)
            else:
                if source == "yfinance":
                    self.assertTrue(params.get("ticker"), series_id)
                    field = params.get("field")
                    self.assertTrue(field is None or field in yfinance._INFO_FIELD_MAP, series_id)

    def test_macro_web_registry_has_no_parser_the_seed_never_calls(self):
        """등록만 되고 seed가 부르지 않는 파서는 조용히 썩는다."""
        seeded = {
            (row["source_params"].get("source"), row["source_params"].get("parser"))
            for row in MARKET_INDICATOR_CATALOG
            if row["source"] == "web_crawling"
        }
        self.assertTrue(seeded)
        self.assertSetEqual(set(web.PARSERS), seeded)

    def test_econ_seed_declares_every_actual_contract_and_unsupported_is_explicit(self):
        config = [series_config(sid) for sid in series_ids()]
        providers = [row["source_contract"]["actual"]["provider"] for row in config]
        self.assertEqual(len(config), 30)
        self.assertEqual(providers.count("fred"), 21)
        self.assertTrue({"ecos", "eia", "fred_components"}.issubset(providers))
        self.assertEqual(providers.count("unsupported"), 2)
        self.assertNotIn("AAII", series_ids())



class ActualsFailClosedTest(unittest.TestCase):
    def test_provider_failure_is_typed_and_does_not_leak_cause(self):
        setting = {
            "series_id": "TEST_FRED",
            "actual_provider": "fred",
            "collection_status": "ok",
            "source_contract": {"actual": {"provider": "fred", "code": "TEST", "unit": "index"}},
            "frequency": "daily",
        }
        with mock.patch.object(
            actuals, "_fred", side_effect=RuntimeError("secret-query-token")
        ):
            values, failures = actuals.fetch_batch(
                [setting], start=_START, end=_END
            )

        self.assertEqual(values, {})
        self.assertEqual(failures[0]["type"], "ActualProviderError")
        self.assertNotIn("secret-query-token", failures[0]["error"])

    def test_unknown_source_is_typed_configuration_failure(self):
        setting = {
            "series_id": "UNKNOWN",
            "actual_provider": "mystery",
            "collection_status": "ok",
            "source_contract": {"actual": {"provider": "mystery"}},
            "frequency": "daily",
        }
        with self.assertRaises(actuals.UnsupportedActualSourceError):
            actuals._one(setting, _START, _END)

    def test_active_computed_recipe_is_scaled_and_validated(self):
        setting = {
            "series_id": "FED_NET_LIQ",
            "actual_provider": "fred_components",
            "collection_status": "ok",
            "source_contract": {
                "actual": {"provider": "fred_components", "unit": "usd_billions", "scale": "0.5"},
            },
            "frequency": "weekly",
        }
        source = pd.Series([100.0, 120.0], index=_INDEX)
        with mock.patch.object(
            actuals, "_fed_net_liquidity", return_value=source
        ):
            result = actuals._one(setting, _START, _END)

        self.assertEqual(result.tolist(), [50.0, 60.0])

    def test_duplicate_dates_are_typed_data_failure(self):
        duplicated = pd.Series(
            [1.0, 2.0],
            index=pd.DatetimeIndex(["2026-08-20", "2026-08-20"]),
        )
        setting = {
            "series_id": "TEST_FRED",
            "actual_provider": "fred",
            "collection_status": "ok",
            "source_contract": {"actual": {"provider": "fred", "code": "TEST", "unit": "index"}},
            "frequency": "weekly",
        }
        with (
            mock.patch.object(actuals, "_fred", return_value=duplicated),
            self.assertRaises(actuals.ActualDataError),
        ):
            actuals._one(setting, _START, _END)


class MarketBreadthFailClosedTest(unittest.TestCase):
    def _indicator(self):
        return {
            "series_id": "BREADTH_200DMA",
            "source_params": {
                "ma_window": 200,
                "min_periods": 180,
                "min_coverage": 0.75,
            },
        }

    def test_active_breadth_source_success(self):
        expected = pd.Series([61.0, 62.0], index=_INDEX)
        with mock.patch.object(
            market, "breadth_200dma", return_value=expected
        ) as provider:
            values, failures = market.fetch_batch(
                [self._indicator()], _START, _END,
                universe_repository=mock.Mock(), load_prices=mock.Mock(),
            )

        self.assertEqual(failures, [])
        pd.testing.assert_series_equal(values["BREADTH_200DMA"], expected)
        provider.assert_called_once_with(
            _START,
            _END,
            universe_repository=mock.ANY,
            load_prices=mock.ANY,
            ma_window=200,
            min_periods=180,
            min_coverage=0.75,
        )

    def test_duplicate_breadth_dates_are_rejected(self):
        duplicated = pd.Series(
            [61.0, 62.0],
            index=pd.DatetimeIndex(["2026-08-20", "2026-08-20"]),
        )
        with mock.patch.object(market, "breadth_200dma", return_value=duplicated):
            values, failures = market.fetch_batch(
                [self._indicator()], _START, _END,
                universe_repository=mock.Mock(), load_prices=mock.Mock(),
            )

        self.assertTrue(values["BREADTH_200DMA"].empty)
        self.assertEqual(failures[0]["type"], "ValueError")


class WebFailClosedTest(unittest.TestCase):
    def test_unknown_parser_is_typed_per_indicator_failure(self):
        indicator = {
            "series_id": "UNKNOWN_WEB",
            "source_params": {"source": "old-site", "parser": "removed"},
        }
        values, failures = web.fetch_batch([indicator], _START, _END)

        self.assertTrue(values["UNKNOWN_WEB"].empty)
        self.assertEqual(failures[0]["type"], "UnsupportedWebParserError")

    def test_provider_failure_is_typed_and_sanitized(self):
        indicator = {
            "series_id": "BROKEN_WEB",
            "source_params": {"source": "fixture", "parser": "broken"},
        }

        def broken(_start: date, _end: date) -> pd.Series:
            raise RuntimeError("secret-page-body")

        with mock.patch.dict(web.PARSERS, {("fixture", "broken"): broken}):
            _values, failures = web.fetch_batch([indicator], _START, _END)

        self.assertEqual(failures[0]["type"], "WebProviderError")
        self.assertNotIn("secret-page-body", failures[0]["error"])

    def test_active_cnn_contract_accepts_offline_fixture(self):
        indicator = {
            "series_id": "FEAR_GREED",
            "source_params": {"source": "cnn", "parser": "fear_greed"},
        }
        fixture = pd.Series([48.0, 51.0], index=_INDEX)
        with mock.patch.dict(
            web.PARSERS, {("cnn", "fear_greed"): lambda _s, _e: fixture}
        ):
            values, failures = web.fetch_batch([indicator], _START, _END)

        self.assertEqual(failures, [])
        pd.testing.assert_series_equal(values["FEAR_GREED"], fixture)


class YFinanceFailClosedTest(unittest.TestCase):
    def test_unknown_info_field_is_typed_per_indicator_failure(self):
        indicator = {
            "series_id": "BAD_FIELD",
            "source_params": {"ticker": "SPY", "field": "made_up"},
        }
        with mock.patch.object(yfinance, "_fetch_many", return_value={}):
            values, failures = yfinance.fetch_batch([indicator], _START, _END)

        self.assertTrue(values["BAD_FIELD"].empty)
        self.assertEqual(
            failures[0]["type"], "UnsupportedYFinanceFieldError"
        )

    def test_batch_miss_and_fallback_provider_failure_is_typed(self):
        indicator = {
            "series_id": "SPY",
            "source_params": {"ticker": "^GSPC"},
        }
        history_error = yfinance.YFinanceProviderError(
            "^GSPC", "Ticker.history", RuntimeError("history-secret")
        )
        download_error = yfinance.YFinanceProviderError(
            "^GSPC", "download", RuntimeError("download-secret")
        )
        with (
            mock.patch.object(yfinance, "_fetch_many", return_value={}),
            mock.patch.object(yfinance, "_via_ticker", side_effect=history_error),
            mock.patch.object(yfinance, "_via_download", side_effect=download_error),
        ):
            values, failures = yfinance.fetch_batch([indicator], _START, _END)

        self.assertTrue(values["SPY"].empty)
        self.assertEqual(failures[0]["type"], "YFinanceProviderError")
        self.assertNotIn("download-secret", failures[0]["error"])

    def test_batch_price_success_never_calls_network_fallback(self):
        indicator = {
            "series_id": "SPY",
            "source_params": {"ticker": "^GSPC"},
        }
        fixture = pd.Series([6500.0, 6510.0], index=_INDEX)
        with (
            mock.patch.object(
                yfinance, "_fetch_many", return_value={"^GSPC": fixture}
            ),
            mock.patch.object(yfinance, "_fetch_one") as fallback,
        ):
            values, failures = yfinance.fetch_batch([indicator], _START, _END)

        self.assertEqual(failures, [])
        pd.testing.assert_series_equal(values["SPY"], fixture)
        fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
