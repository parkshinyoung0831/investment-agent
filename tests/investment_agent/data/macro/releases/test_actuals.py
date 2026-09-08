"""ECON actual provider의 unit/validation/fail-closed 계약."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd

from investment_agent.data.macro.infrastructure.releases.sources import actuals


def _fred_setting() -> dict:
    return {
        "series_id": "US_CPI",
        "frequency": "monthly",
        "actual_provider": "fred",
        "collection_status": "ok",
        "source_contract": {"actual": {"provider": "fred", "code": "CPIAUCSL", "unit": "index"}},
    }


class ActualProviderTest(unittest.TestCase):
    def test_ecos_history_reads_beyond_the_first_thousand_rows(self) -> None:
        days = pd.date_range("2016-01-01", periods=1002, freq="D")
        records = [{"TIME": day.strftime("%Y%m%d"), "DATA_VALUE": "1.5"} for day in days]
        responses = [MagicMock(), MagicMock()]
        responses[0].json.return_value = {"StatisticSearch": {"list_total_count": 1002, "row": records[:1000]}}
        responses[1].json.return_value = {"StatisticSearch": {"list_total_count": 1002, "row": records[1000:]}}
        with (patch.dict(actuals.os.environ, {"ECOS_API_KEY": "test-only"}),
              patch.object(actuals.requests, "get", side_effect=responses) as fetch):
            result = actuals._ecos("722Y001", "0101000", "irregular", days[0].date(), days[-1].date())
        self.assertEqual(len(result), 1002)
        self.assertEqual(result.index[-1], days[-1])
        self.assertIn("/1001/2000/", fetch.call_args_list[1].args[0])

    def test_ecos_truncated_or_overlapping_pages_are_rejected(self) -> None:
        for second in ([], [{"TIME": "20260101", "DATA_VALUE": "1.5"}]):
            with self.subTest(second=second):
                responses = [MagicMock(), MagicMock()]
                responses[0].json.return_value = {"StatisticSearch": {"list_total_count": 2,
                    "row": [{"TIME": "20260101", "DATA_VALUE": "1.5"}]}}
                responses[1].json.return_value = {"StatisticSearch": {"list_total_count": 2, "row": second}}
                with (patch.dict(actuals.os.environ, {"ECOS_API_KEY": "test-only"}),
                      patch.object(actuals.requests, "get", side_effect=responses)):
                    with self.assertRaises(actuals.ActualDataError):
                        actuals._ecos("722Y001", "0101000", "irregular", date(2026,1,1), date(2026,1,2))

    def test_collector_time_is_after_response_and_comparison_window_is_used(self) -> None:
        seen = datetime(2026, 8, 12, 12, 29, tzinfo=timezone.utc)
        after = datetime(2026, 8, 12, 12, 31, tzinfo=timezone.utc)

        def fetch(*_args):
            nonlocal seen
            seen = after
            return pd.Series([332.813], index=pd.DatetimeIndex(["2026-07-01"]))

        with (patch.object(actuals, "_one", side_effect=fetch) as provider,
              patch.object(actuals, "datetime") as clock):
            clock.now.side_effect = lambda *_args: seen
            values, failures = actuals.fetch_batch([_fred_setting()], start=date(2026, 7, 1),
                end=date(2026, 8, 12), starts_by_series={"US_CPI": date(2025, 7, 1)})
        self.assertEqual(failures, [])
        self.assertEqual(provider.call_args.args[1], date(2025, 7, 1))
        self.assertEqual(values["US_CPI"][0]["effective_at"], after.isoformat())
        self.assertEqual(values["US_CPI"][0]["collected_at"], after.isoformat())
        self.assertEqual(values["US_CPI"][0]["time_precision"], "collector_seen")

    def test_month_end_provider_period_is_normalized_to_month_start(self) -> None:
        setting = {
            "series_id": "KR_CPI", "frequency": "monthly", "actual_provider": "ecos",
            "collection_status": "ok",
            "source_contract": {"actual": {"provider": "ecos", "statistic": "901Y009", "item": "0", "unit": "index"}},
        }
        series = pd.Series([120.1], index=pd.DatetimeIndex(["2026-07-31"]))
        with patch.object(actuals, "_ecos", return_value=series):
            values, failures = actuals.fetch_batch([setting], start=date(2026, 7, 1), end=date(2026, 8, 1))
        self.assertEqual(failures, [])
        self.assertEqual(values["KR_CPI"][0]["ref_period"], "2026-07-01")

    def test_provider_failure_is_typed_and_secret_is_not_exposed(self) -> None:
        with patch.object(actuals, "_fred", side_effect=RuntimeError("secret-query-token")):
            values, failures = actuals.fetch_batch([_fred_setting()], start=date(2026, 8, 1), end=date(2026, 8, 2))
        self.assertEqual(values, {})
        self.assertEqual(failures[0]["type"], "ActualProviderError")
        self.assertNotIn("secret-query-token", failures[0]["error"])

    def test_empty_window_is_pending_not_provider_failure(self) -> None:
        with patch.object(actuals, "_fred", return_value=pd.Series(dtype=float, index=pd.DatetimeIndex([]))):
            values, failures = actuals.fetch_batch(
                [_fred_setting()], start=date(2026, 8, 1), end=date(2026, 8, 2)
            )
        self.assertEqual(values, {})
        self.assertEqual(failures[0]["status"], "not_available_yet")
        self.assertEqual(failures[0]["type"], "ActualNotAvailableYetError")

    def test_unsupported_family_is_skipped_not_scraped(self) -> None:
        setting = {
            "series_id": "US_ISM_MANUFACTURING", "frequency": "monthly",
            "actual_provider": "unsupported", "collection_status": "unsupported",
            "source_contract": {"actual": {"provider": "unsupported"}},
        }
        values, failures = actuals.fetch_batch([setting], start=date(2026, 8, 1), end=date(2026, 8, 2))
        self.assertEqual(values, {})
        self.assertEqual(failures[0]["status"], "unsupported")

    def test_duplicate_dates_and_nonfinite_values_fail_closed(self) -> None:
        duplicated = pd.Series([1.0, 2.0], index=pd.DatetimeIndex(["2026-08-01", "2026-08-01"]))
        with patch.object(actuals, "_fred", return_value=duplicated):
            with self.assertRaises(actuals.ActualDataError):
                actuals._one(_fred_setting(), date(2026, 8, 1), date(2026, 8, 2))

    def test_fomc_effective_provider_date_maps_to_policy_decision_event(self) -> None:
        setting = {
            "series_id": "US_FOMC_FED_FUNDS", "frequency": "irregular", "actual_provider": "fred",
            "collection_status": "degraded",
            "source_contract": {"actual": {
                "provider": "fred", "code": "DFEDTARU", "unit": "percent",
                "event_ref_period_offset_days": -1,
            }},
        }
        series = pd.Series([3.75], index=pd.DatetimeIndex(["2025-12-11"]))
        with patch.object(actuals, "_fred", return_value=series):
            values, failures = actuals.fetch_batch([setting], start=date(2025, 12, 10), end=date(2025, 12, 11))
        self.assertEqual(failures, [])
        self.assertEqual(values["US_FOMC_FED_FUNDS"][0]["ref_period"], "2025-12-10")
        self.assertEqual(values["US_FOMC_FED_FUNDS"][0]["provenance"]["provider_ref_period"], "2025-12-11")


if __name__ == "__main__":
    unittest.main()
