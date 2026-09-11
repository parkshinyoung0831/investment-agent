"""ECON 자연키·원자료 단일 저장·시간 보존 경계의 오프라인 테스트."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from investment_agent.data.macro.application import release_calendar as etl
from investment_agent.data.macro.releases import db
from investment_agent.data.macro.domain.releases.identity import event_key, split_event_key
from investment_agent.data.macro.infrastructure.releases.sources import alfred

KEY = "US_CPI:2026-07-01"
RAW = {
    "series_id": "US_CPI", "ref_period": "2026-07-01", "value": 332.813,
    "unit": "index", "provider": "fred", "provider_code": "CPIAUCSL",
    "effective_at": "2026-08-12T12:31:00Z", "collected_at": "2026-08-12T12:31:00Z",
    "availability_precision": "timestamp", "provenance": {"effective_basis": "collector_seen_at"},
}


class IdentityTest(unittest.TestCase):
    def test_readable_key_never_depends_on_scheduled_time(self) -> None:
        self.assertEqual(event_key("US_CPI", "2026-07-01"), KEY)
        self.assertEqual(split_event_key(KEY), ("US_CPI", "2026-07-01"))
        for invalid in ("opaque-uuid", "US_CPI:2026-07-32", "US_CPI.MOM:2026-07-01"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                split_event_key(invalid)


class WriterTest(unittest.TestCase):
    def test_raw_writer_keeps_timing_without_repeated_metadata_or_actuals(self) -> None:
        database = Mock()
        database.upsert.return_value = 1
        with (patch.object(db, "_series_key", return_value=11),
              patch.object(db, "_db", return_value=database)):
            self.assertEqual(db.append_observations([RAW]), 1)
        rows = database.upsert.call_args.kwargs["rows"]
        self.assertEqual(database.upsert.call_args.kwargs["table"], db.T_OBSERVATIONS)
        self.assertEqual(set(rows[0]), {
            "series_key", "observation_date", "value", "source_code", "time_precision",
            "vintage_at", "available_at", "revision_no",
        })
        self.assertEqual(rows[0]["source_code"], "fred")
        self.assertEqual(rows[0]["time_precision"], "collector_seen")
        self.assertEqual(rows[0]["available_at"], "2026-08-12T12:31:00+00:00")

    def test_bad_units_or_nonfinite_values_never_reach_rpc(self) -> None:
        for changed in ({"unit": "percent"}, {"value": float("nan")}, {"value": float("inf")},
                        {"effective_at": "2026-08-13T00:00:00Z"}, {"collected_at": "2026-08-12T12:31:00"}):
            with self.subTest(changed=changed), patch.object(db, "_db") as database:
                with self.assertRaises(ValueError):
                    db.append_observations([{**RAW, **changed}])
                database.upsert.assert_not_called()

    def test_forecast_can_change_twice_in_one_day_or_be_withdrawn(self) -> None:
        common = {"series_id": "US_CPI", "ref_period": "2026-07-01", "measure_id": "US_CPI.MOM",
                  "forecast_kind": "survey", "source": "licensed_survey", "time_precision": "exact"}
        rows = [{**common, "value": value, "effective_at": f"2026-08-10T{hour}:00:00Z"}
                for hour, value in (("08", .2), ("09", .3), ("10", .2), ("11", None))]
        database = Mock()
        database.upsert.return_value = 4
        with (patch.object(db, "_series_key", return_value=11),
              patch.object(db, "_db", return_value=database)):
            self.assertEqual(db.append_forecasts(rows), 4)
        self.assertEqual([row["value"] for row in database.upsert.call_args.kwargs["rows"]], [.2, .3, .2, None])

    def test_mismatched_forecast_measure_fails_before_rpc(self) -> None:
        row = {"series_id": "US_CPI", "ref_period": "2026-07-01", "measure_id": "KR_CPI.MOM",
               "forecast_kind": "survey", "source": "test", "value": .2}
        with self.assertRaises(ValueError):
            db.append_forecasts([row])

    def test_historical_forecast_effective_time_does_not_become_collection_time(self) -> None:
        now = datetime(2026, 8, 31, tzinfo=timezone.utc)
        row = {"as_of": "2020-08-01T00:00:00Z"}
        self.assertEqual(db._times(row, now)["collected_at"], now.isoformat())
        self.assertEqual(db._times(row, now)["effective_at"], "2020-08-01T00:00:00+00:00")

    def test_model_history_uses_release_periods_instead_of_dense_policy_rate_days(self) -> None:
        with patch.object(db, "_select", return_value=[{"ref_period": "2026-08-01", "value": 3.5, "effective_at": "2026-08-02", "collected_at": "2026-08-02"}, {"ref_period": "2026-09-01", "value": 4.0, "effective_at": "2026-09-02", "collected_at": "2026-09-02"}]):
            values = db.primary_history("US_FOMC_FED_FUNDS")
        self.assertEqual(values, [3.5, 4.0])

    def test_nonprimary_forecast_target_reads_its_own_measure_history(self) -> None:
        with patch.object(db, "_select", return_value=[{"ref_period": "2026-08-01", "value": 2.0, "effective_at": "2026-08-02", "collected_at": "2026-08-02"}, {"ref_period": "2026-09-01", "value": 1.0, "effective_at": "2026-09-02", "collected_at": "2026-09-02"}]):
            values = db.measure_history("US_M2", "US_M2.YOY")
        self.assertEqual(values, [2.0, 1.0])


class IngestTest(unittest.TestCase):
    def _summary(self, **changes) -> dict:
        return {"event_key": KEY, "series_id": "US_CPI", "ref_period": "2026-07-01",
                "scheduled_at": "2026-08-12T12:30:00Z", "first_actual_at": "2026-08-12T12:31:00Z",
                "first_actual_value": .2, "latest_actual_value": .2, **changes}

    def test_forecast_generation_uses_configured_nonprimary_measure(self) -> None:
        now = datetime(2026, 8, 31, tzinfo=timezone.utc)
        release = {"series_id": "US_M2", "ref_period": "2026-08-01"}
        setting = {"series_id": "US_M2", "frequency": "monthly",
                   "forecast_measure_id": "US_M2.YOY"}
        definitions = {"US_M2": [
            {"measure_id": "US_M2.LEVEL", "is_primary": True},
            {"measure_id": "US_M2.YOY", "is_primary": False},
        ]}
        with (patch.object(db, "releases_within", return_value=[release]),
              patch.object(db, "measures_by_series", return_value=definitions),
              patch.object(db, "enabled_series", return_value=[setting]),
              patch.object(db, "measure_history", return_value=[1.0, 2.0]) as history,
              patch.object(db, "primary_history") as primary_history,
              patch.object(etl.baseline, "drift_forecast", return_value={"method": "naive", "value": 2.0}),
              patch.object(db, "append_forecasts", return_value=1) as append):
            inserted, failures = etl.snapshot_forecasts(now=now)
        self.assertEqual(inserted, 1)
        self.assertEqual(failures, [])
        history.assert_called_once_with("US_M2", "US_M2.YOY")
        primary_history.assert_not_called()
        self.assertEqual(append.call_args.args[0][0]["measure_id"], "US_M2.YOY")

    def test_first_calculable_value_is_detected_without_writing_an_actual_copy(self) -> None:
        with (patch.object(db, "append_observations", return_value=1) as append,
              patch.object(db, "summaries_for", side_effect=[{}, {KEY: self._summary()}]) as summaries):
            result = etl.ingest_raw({"US_CPI": [RAW]})
        append.assert_called_once_with([RAW])
        self.assertEqual(summaries.call_count, 2)
        self.assertEqual(result["first_actual_event_keys"], [KEY])
        self.assertEqual(result["actualized_event_keys"], [KEY])

    def test_bad_schedule_does_not_discard_valid_raw_data(self) -> None:
        row = self._summary(scheduled_at="2026-09-22T12:30:00Z")
        with (patch.object(db, "append_observations", return_value=1),
              patch.object(db, "summaries_for", side_effect=[{}, {KEY: row}]),
              patch.object(etl, "_report_schedule_conflicts") as report):
            result = etl.ingest_raw({"US_CPI": [RAW]})
        self.assertEqual(result["observations_inserted"], 1)
        self.assertEqual(result["first_actual_event_keys"], [])
        self.assertEqual(result["schedule_conflicts"][0]["series_id"], "US_CPI")
        report.assert_called_once()

    def test_missing_base_value_remains_pending(self) -> None:
        row = self._summary(first_actual_value=None, latest_actual_value=None, first_actual_at=None)
        with (patch.object(db, "append_observations", return_value=1),
              patch.object(db, "summaries_for", side_effect=[{KEY: row}, {KEY: row}])):
            result = etl.ingest_raw({"US_CPI": [RAW]}, eligible_event_keys={KEY})
        self.assertEqual(result["observations_inserted"], 1)
        self.assertEqual(result["first_actuals"], 0)
        self.assertEqual(result["actualized_event_keys"], [])

    def test_backfill_saves_raw_without_notification_queries(self) -> None:
        with (patch.object(db, "append_observations", return_value=1),
              patch.object(db, "summaries_for") as summaries):
            result = etl.ingest_raw({"US_CPI": [RAW]}, notify_first=False)
        self.assertEqual(result["observations_inserted"], 1)
        summaries.assert_not_called()

    def test_value_without_a_schedule_is_still_retained(self) -> None:
        with (patch.object(db, "append_observations", return_value=1),
                patch.object(db, "summaries_for", return_value={})):
            result = etl.ingest_raw({"US_CPI": [RAW]})
        self.assertEqual(result["unmatched_observations"], [KEY])


class AlfredParserTest(unittest.TestCase):
    def test_output_type_three_wide_vintages_are_expanded(self) -> None:
        rows = [{"date": "2026-07-01", "CPIAUCSL_20260812": "332.813", "CPIAUCSL_20260910": "332.900"}]
        parsed = alfred._parse_revisions(rows, fred_id="CPIAUCSL", scale=None)
        self.assertEqual([(row["ref_period"], row["released_on"], row["value"]) for row in parsed],
                         [("2026-07-01", "2026-08-12", 332.813), ("2026-07-01", "2026-09-10", 332.9)])

    def test_revision_query_with_no_changed_vintages_is_a_successful_noop(self) -> None:
        """짧은 감사 구간에 개정이 없다는 것은 외부 원천 장애가 아니다."""
        target = {"series_id": "US_CPI", "fred_id": "CPIAUCSL", "scale": None}
        with patch.object(alfred, "fetch_revisions", return_value=[]):
            values, failures = alfred.fetch_batch(
                [target], observation_start=date(2026, 8, 12), revisions=True,
            )
        self.assertEqual(values, {})
        self.assertEqual(failures, [])

    def test_revision_failure_retains_the_safe_parser_reason(self) -> None:
        """API 키·URL은 숨기되, 데이터 계약 오류는 Actions에서 진단할 수 있어야 한다."""
        target = {"series_id": "US_CPI", "fred_id": "CPIAUCSL", "scale": None}
        error = alfred.AlfredDataError("ALFRED revision row has no observation date")
        with patch.object(alfred, "fetch_revisions", side_effect=error):
            _values, failures = alfred.fetch_batch(
                [target], observation_start=date(2026, 8, 12), revisions=True,
            )
        self.assertEqual(failures[0]["error"], "ALFRED revision row has no observation date")

    def test_revision_failure_retains_the_provider_error_message_without_a_request_url(self) -> None:
        response = requests.Response()
        response.status_code = 400
        response._content = b'{"error_message":"Bad Request. Invalid realtime_start."}'
        error = requests.HTTPError("request URL must never enter the diagnostic", response=response)
        target = {"series_id": "US_CPI", "fred_id": "CPIAUCSL", "scale": None}
        with patch.object(alfred, "fetch_revisions", side_effect=error):
            _values, failures = alfred.fetch_batch(
                [target], observation_start=date(2026, 8, 12), revisions=True,
            )
        self.assertEqual(failures[0]["error"], "HTTP 400: Bad Request. Invalid realtime_start.")

    def test_revision_window_without_provider_vintages_is_a_successful_noop(self) -> None:
        """ALFRED가 빈 vintage 구간을 400으로 표현해도 개정 없음으로 처리한다."""
        response = requests.Response()
        response.status_code = 400
        response._content = (
            b'{"error_message":"Bad Request. No vintage dates exist for the specified real-time period."}'
        )
        error = requests.HTTPError(response=response)
        target = {"series_id": "US_GDP", "fred_id": "A191RL1Q225SBEA", "scale": None}
        with patch.object(alfred, "fetch_revisions", side_effect=error):
            values, failures = alfred.fetch_batch(
                [target], observation_start=date(2026, 8, 12), revisions=True,
            )
        self.assertEqual(values, {})
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
