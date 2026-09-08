"""30-family ECON schedule/measure source contract의 오프라인 회귀 테스트."""
from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from investment_agent.data.macro.domain.releases import normalize, schedule
from investment_agent.data.macro.domain.releases import release_catalog as catalog

ROOT = Path(__file__).resolve().parents[5]
EXPECTED_SERIES = {
    "US_CPI", "US_CORE_CPI", "US_PPI", "US_CORE_PPI", "US_PCE", "US_CORE_PCE", "KR_CPI", "KR_CORE_CPI",
    "US_NFP", "US_UNEMPLOYMENT", "US_AHE", "US_JOLTS_OPENINGS", "US_INITIAL_CLAIMS", "US_CONTINUING_CLAIMS",
    "US_GDP", "KR_GDP", "US_RETAIL_SALES", "US_INDUSTRIAL_PRODUCTION", "US_ISM_MANUFACTURING", "US_ISM_SERVICES",
    "US_MICHIGAN_SENTIMENT", "US_FOMC_FED_FUNDS", "KR_BASE_RATE", "US_MORTGAGE_30Y", "US_NEW_HOME_SALES",
    "US_EXISTING_HOME_SALES", "US_M2", "FED_NET_LIQUIDITY", "KR_EXPORT", "EIA_CRUDE_OIL_INVENTORIES",
}


class ScheduleTimezoneTest(unittest.TestCase):
    def test_kr_base_rate_0950_kst_is_0050_utc(self) -> None:
        actual = schedule.scheduled_at_utc(
            date(2026, 8, 27), release_time="09:50", release_tz="Asia/Seoul", confidence="exact"
        )
        self.assertEqual(actual.isoformat(), "2026-08-27T00:50:00+00:00")

    def test_us_dst_is_not_hardcoded_to_one_utc_offset(self) -> None:
        winter = schedule.scheduled_at_utc(
            date(2026, 1, 9), release_time="08:30", release_tz="America/New_York", confidence="exact"
        )
        summer = schedule.scheduled_at_utc(
            date(2026, 7, 9), release_time="08:30", release_tz="America/New_York", confidence="exact"
        )
        self.assertEqual(winter.isoformat(), "2026-01-09T13:30:00+00:00")
        self.assertEqual(summer.isoformat(), "2026-07-09T12:30:00+00:00")

    def test_date_only_does_not_silently_become_0830(self) -> None:
        actual = schedule.scheduled_at_utc(
            date(2026, 8, 1), release_time=None, release_tz="Asia/Seoul", confidence="date_only"
        )
        self.assertEqual(actual.isoformat(), "2026-08-01T03:00:00+00:00")

    def test_confidence_windows_are_bounded(self) -> None:
        self.assertEqual(schedule.schedule_window("exact").total_seconds(), 2 * 3600)
        self.assertEqual(schedule.schedule_window("date_only").total_seconds(), 36 * 3600)


class ReferencePeriodTest(unittest.TestCase):
    def test_monthly_and_quarterly_periods_are_canonical_period_starts(self) -> None:
        self.assertEqual(
            schedule.reference_period("US_CPI", "monthly", date(2026, 9, 11)),
            date(2026, 8, 1),
        )
        self.assertEqual(
            schedule.reference_period("US_GDP", "quarterly", date(2026, 7, 30)),
            date(2026, 4, 1),
        )

    def test_weekly_claims_use_prior_reference_week(self) -> None:
        self.assertEqual(
            schedule.reference_period("US_INITIAL_CLAIMS", "weekly", date(2026, 8, 27)),
            date(2026, 8, 22),
        )

    def test_rule_dates_are_deterministic(self) -> None:
        self.assertEqual(
            schedule.rule_dates("weekly_wednesday", start=date(2026, 8, 1), end=date(2026, 8, 15)),
            [date(2026, 8, 5), date(2026, 8, 12)],
        )
        self.assertEqual(
            schedule.rule_dates("monthly_first_business_day", start=date(2026, 8, 1), end=date(2026, 9, 3)),
            [date(2026, 8, 3), date(2026, 9, 1)],
        )


class MeasureCalculationTest(unittest.TestCase):
    def test_required_investment_measure_calculations(self) -> None:
        measures = [
            {"measure_id": "X.LEVEL", "transform": "level"},
            {"measure_id": "X.MOM", "transform": "pct_change_1"},
            {"measure_id": "X.YOY", "transform": "pct_change_12"},
            {"measure_id": "X.CHANGE_4W", "transform": "change_4"},
        ]
        raw = {date(2025, month, 1): 100.0 + month for month in range(1, 13)}
        raw[date(2026, 1, 1)] = 121.0
        values = normalize.calculate_family(measures, raw)[date(2026, 1, 1)]
        self.assertEqual(values["X.LEVEL"], 121.0)
        self.assertAlmostEqual(values["X.MOM"], (121 / 112 - 1) * 100)
        self.assertAlmostEqual(values["X.YOY"], (121 / 101 - 1) * 100)
        self.assertAlmostEqual(values["X.CHANGE_4W"], 121 - 109)

    def test_zero_base_and_missing_history_do_not_become_fake_zero(self) -> None:
        self.assertIsNone(normalize.calculate_measure("pct_change_1", current=2, prior_1=0))
        self.assertIsNone(normalize.calculate_measure("change_1", current=2, prior_1=None))

    def test_missing_month_does_not_shift_mom_or_yoy(self) -> None:
        raw = {date(2024, month, 1): 100.0 + month for month in range(1, 13)}
        raw.update({date(2025, month, 1): 120.0 + month for month in range(1, 13) if month != 10})
        measures = [{"measure_id": "US_CPI.MOM", "transform": "pct_change_1"},
                    {"measure_id": "US_CPI.YOY", "transform": "pct_change_12"}]
        november = normalize.calculate_family(measures, raw)[date(2025, 11, 1)]
        self.assertNotIn("US_CPI.MOM", november)
        self.assertAlmostEqual(november["US_CPI.YOY"], (131 / 111 - 1) * 100)

    def test_weekly_exact_lag_never_becomes_the_fourth_available_row(self) -> None:
        raw = {date(2026, 7, day): value for day, value in ((1, 100), (8, 101), (22, 103), (29, 104))}
        measure = {"measure_id": "FED_NET_LIQUIDITY.CHANGE_4W", "transform": "change_4",
                   "frequency": "weekly"}
        result = normalize.calculate_family([measure], raw)
        self.assertEqual(result[date(2026, 7, 29)][measure["measure_id"]], 4)

    def test_previous_change_uses_the_prior_available_observation(self) -> None:
        raw = {date(2026, 7, 1): 100.0, date(2026, 7, 22): 103.0}
        measure = {"measure_id": "EIA_CRUDE_OIL_INVENTORIES.WEEKLY_CHANGE",
                   "transform": "change_previous", "frequency": "weekly"}
        result = normalize.calculate_family([measure], raw)
        self.assertEqual(result[date(2026, 7, 22)][measure["measure_id"]], 3)

    def test_poll_reads_comparison_periods_without_fetching_all_history(self) -> None:
        self.assertEqual(normalize.required_history_start([{"transform": "pct_change_12"}],
            frequency="monthly", ref_period=date(2026, 7, 1)), date(2025, 7, 1))


class SeedContractTest(unittest.TestCase):
    def test_exactly_30_families_and_46_measures(self) -> None:
        measures = catalog.measure_definitions()
        self.assertSetEqual(set(catalog.series_ids()), EXPECTED_SERIES)
        self.assertEqual(len(measures), 46)
        self.assertEqual(len({row["measure_id"] for row in measures}), 46)

    def test_removed_and_unsupported_contracts_are_explicit(self) -> None:
        config = (ROOT / "src/investment_agent/data/macro/releases/series_config.json").read_text(encoding="utf-8")
        for removed in ("AAII", "KR_CCSI", "KR_FX_RESERVES", "marketcalendar.example", "STLENI"):
            self.assertNotIn(removed, config)
        self.assertSetEqual(set(catalog.series_ids()), EXPECTED_SERIES)
        self.assertEqual(sum(catalog.series_config(sid)["collection_status"] == "unsupported" for sid in EXPECTED_SERIES), 2)
        self.assertIn("ISM terms prohibit automated", config)

    def test_each_series_has_one_existing_forecast_target(self) -> None:
        measures = {row["measure_id"] for row in catalog.measure_definitions()}
        targets = {
            catalog.series_config(sid)["forecast_measure_id"]
            for sid in EXPECTED_SERIES
        }
        self.assertEqual(len(targets), len(EXPECTED_SERIES))
        self.assertTrue(targets <= measures)
        self.assertTrue(all(target.startswith(f"{sid}.")
                            for sid in EXPECTED_SERIES
                            for target in [catalog.series_config(sid)["forecast_measure_id"]]))

    def test_current_declarations_do_not_reintroduce_removed_storage(self) -> None:
        schema = (ROOT / "db/postgres/v1/40_macro.sql").read_text(encoding="utf-8")
        seed = schema
        for removed in ("schedule_version_id", "observation_id", "forecast_version_id",
                        "source_revision_key", "last_seen_at", "lag_basis", "is_forecastable",
                        "month_rollup", "year_rollup"):
            self.assertNotIn(removed, schema + seed)
        measures = schema.split("CREATE TABLE IF NOT EXISTS macro.measures", 1)[1].split(");", 1)[0]
        self.assertNotIn("is_surprise_eligible", measures)
        schedule_table = schema.split("CREATE TABLE IF NOT EXISTS macro.release_schedule_versions", 1)[1].split(");", 1)[0]
        self.assertNotIn("effective_at", schedule_table)

    def test_config_callers_cannot_mutate_shared_provider_definitions(self) -> None:
        before = catalog.series_config("US_CPI")
        changed = catalog.series_config("US_CPI")
        changed["source_contract"]["actual"]["unit"] = "percent"
        self.assertEqual(catalog.series_config("US_CPI"), before)


if __name__ == "__main__":
    unittest.main()
