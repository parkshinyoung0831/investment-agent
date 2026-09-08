"""매크로 단위 계약, 환율 교차검증 및 정합성/품질 안전장치를 검증한다."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import unittest

import pandas as pd

from investment_agent.data.macro.domain.catalog import MARKET_INDICATOR_CATALOG
from investment_agent.data.macro.domain.releases import release_catalog
from investment_agent.reporting.services.macro.freshness import freshness_for
from investment_agent.data.macro.domain.quality import audit_fx_cross_sources, validate_series

ROOT = Path(__file__).resolve().parents[4]



class SeriesContractTest(unittest.TestCase):
    def test_non_series_result_is_rejected(self):
        with self.assertRaisesRegex(TypeError, "expected Series"):
            validate_series({}, [1.0])

    def test_non_finite_result_is_rejected(self):
        series = pd.Series(
            [1400.0, float("inf")],
            index=pd.to_datetime(["2026-08-06", "2026-08-07"]),
        )

        with self.assertRaisesRegex(ValueError, "non-finite"):
            validate_series({}, series)

    def test_duplicate_calendar_dates_are_rejected(self):
        series = pd.Series(
            [1400.0, 1401.0],
            index=pd.to_datetime([
                "2026-08-06 09:00",
                "2026-08-06 15:00",
            ]),
        )

        with self.assertRaisesRegex(ValueError, "duplicate observation dates"):
            validate_series({}, series)

    def test_range_catches_wrong_jpy_scale(self):
        indicator = {
            "source_params": {
                "validation": {"min_value": 300, "max_value": 2000}
            }
        }
        series = pd.Series(
            [8.95, 8.97],
            index=pd.to_datetime(["2026-08-06", "2026-08-07"]),
        )

        with self.assertRaisesRegex(ValueError, "below configured minimum"):
            validate_series(indicator, series)

    def test_change_limit_catches_single_day_spike(self):
        indicator = {
            "source_params": {
                "validation": {"max_abs_change_pct": 10}
            }
        }
        series = pd.Series(
            [1400.0, 1700.0],
            index=pd.to_datetime(["2026-08-06", "2026-08-07"]),
        )

        with self.assertRaisesRegex(ValueError, "exceeds configured maximum"):
            validate_series(indicator, series)


class FxCrossSourceTest(unittest.TestCase):
    def setUp(self):
        self.index = pd.date_range("2026-07-20", periods=6, freq="D")

    def _fred(self, series_id: str, _start: date, _end: date) -> pd.Series:
        if series_id == "DEXKOUS":
            return pd.Series([1400, 1402, 1404, 1406, 1408, 1410], index=self.index)
        if series_id == "DEXJPUS":
            return pd.Series([140, 140, 140, 140, 140, 140], index=self.index)
        raise KeyError(series_id)

    def test_matching_bok_rates_pass(self):
        primary = {
            "USDKRW": pd.Series([1401, 1403, 1405, 1407, 1409, 1411], index=self.index),
            "JPYKRW": pd.Series([1001, 1002, 1003, 1004, 1005, 1006], index=self.index),
        }

        checks = audit_fx_cross_sources(
            primary,
            self._fred,
            start=date(2026, 7, 1),
            end=date(2026, 8, 9),
        )

        self.assertEqual({c["status"] for c in checks}, {"pass"})

    def test_one_yen_scale_fails_against_100_yen_reference(self):
        primary = {
            "JPYKRW": pd.Series([10.01, 10.02, 10.03, 10.04, 10.05, 10.06], index=self.index)
        }

        checks = audit_fx_cross_sources(
            primary,
            self._fred,
            start=date(2026, 7, 1),
            end=date(2026, 8, 9),
        )

        self.assertEqual(checks[0]["status"], "fail")
        self.assertGreater(checks[0]["median_abs_pct"], 90)

    def test_reference_outage_is_non_blocking_skip(self):
        def unavailable(_series_id: str, _start: date, _end: date) -> pd.Series:
            raise TimeoutError("offline")

        checks = audit_fx_cross_sources(
            {"USDKRW": pd.Series([1400.0], index=[pd.Timestamp("2026-08-07")])},
            unavailable,
            start=date(2026, 7, 1),
            end=date(2026, 8, 9),
        )

        self.assertEqual(checks[0]["status"], "skipped")
        self.assertEqual(checks[0]["reason"], "reference_unavailable")


class MacroFreshnessTest(unittest.TestCase):
    def test_daily_friday_value_is_fresh_on_monday_morning(self):
        result = freshness_for("2026-08-07", "daily", as_of=date(2026, 8, 10))

        self.assertEqual(result["age_days"], 3)
        self.assertEqual(result["state"], "fresh")

    def test_daily_value_beyond_market_weekend_window_is_stale(self):
        result = freshness_for("2026-08-07", "daily", as_of=date(2026, 8, 11))

        self.assertEqual(result["state"], "stale")

    def test_missing_observation_is_explicitly_missing(self):
        self.assertEqual(freshness_for(None, "daily")["state"], "missing")


class MacroEconBoundaryTest(unittest.TestCase):
    """catalog seed는 이제 SQL이 아니라 코드가 소유한다(repository.py의
    ``upsert_series`` 진입점이 정상 writer 실행마다 먼저 seed한다) — market
    지표는 ``catalog.py``, 경제 발표는 ``releases/release_catalog.py``다."""

    def test_market_and_economic_release_catalogs_do_not_overlap(self):
        market = {str(row["series_id"]) for row in MARKET_INDICATOR_CATALOG}
        release = set(release_catalog.series_ids())
        self.assertTrue(market, "market catalog가 비어 있다")
        self.assertTrue(release, "release catalog가 비어 있다")
        self.assertEqual(set(), market & release, "같은 series_id가 두 도메인에 겹친다")

    def test_market_notification_kpis_are_covered_by_their_catalogs(self):
        market = {str(row["series_id"]) for row in MARKET_INDICATOR_CATALOG}
        self.assertIn("BREADTH_200DMA", market)
        self.assertIn("US_CPI", set(release_catalog.series_ids()))


class MacroSqlContractTest(unittest.TestCase):
    def test_canonical_sql_contains_only_current_macro_objects(self):
        schema = (ROOT / "db/postgres/v1/40_macro.sql").read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS macro.series", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS macro.market_observations", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS macro.economic_observations", schema)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS macro.observations", schema)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS macro.observation_versions", schema)
        self.assertNotIn("macro.alerts_sent", schema)
        self.assertIn("'market_indicator'", schema)
        # series 데이터 자체는 이제 코드 catalog가 seed한다 — DDL에는 특정
        # series_id 리터럴이 없어야 한다.
        self.assertNotIn("'BREADTH_200DMA'", schema)


if __name__ == "__main__":
    unittest.main()

