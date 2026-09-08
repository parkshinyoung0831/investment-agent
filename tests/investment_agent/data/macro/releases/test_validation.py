"""ECON 검증기가 훼손된 값·시간축·관계를 분리해서 보고하는지 확인한다."""
from __future__ import annotations

import unittest
from copy import deepcopy

from investment_agent.data.macro.domain.releases.validation import validate_snapshot


def _snapshot() -> dict:
    fact = {"series_id": "KR_BASE_RATE", "ref_period": "2026-08-27", "source_code": "fred",
            "effective_at": "2026-08-27T00:50:00Z", "collected_at": "2026-08-27T00:51:00Z",
            "time_precision": "collector_seen"}
    return {
        "series": [{"series_id": "KR_BASE_RATE", "timezone": "Asia/Seoul", "frequency": "irregular"}],
        "measures": [{"measure_id": "KR_BASE_RATE.LEVEL", "series_id": "KR_BASE_RATE", "is_primary": True}],
        "release_events": [{"series_id": "KR_BASE_RATE", "ref_period": "2026-08-27"}],
        "schedule_versions": [{"series_id": "KR_BASE_RATE", "ref_period": "2026-08-27",
                               "source_code": "fred", "collected_at": "2026-08-27T00:51:00Z",
                               "scheduled_at": "2026-08-27T00:50:00Z", "schedule_precision": "exact"}],
        "observations": [{**fact, "value": 2.5}],
        "forecast_versions": [{**fact, "measure_id": "KR_BASE_RATE.LEVEL",
                               "forecast_kind": "survey", "value": None}],
    }


class EconValidationTest(unittest.TestCase):
    def test_explicit_forecast_withdrawal_is_valid_and_actual_copies_are_not_required(self) -> None:
        errors = validate_snapshot(_snapshot())["errors"]
        self.assertEqual(errors["non_finite"], 0)
        self.assertEqual(errors["orphan_event"], 0)
        self.assertEqual(errors["temporal_order"], 0)
        self.assertEqual(errors["measure_mismatch"], 0)
        self.assertGreater(errors["series_not_30"], 0)  # 이 fixture는 관계 검사용으로 한 지표만 둔다.

    def test_detects_wrong_timezone_and_forecast_measure(self) -> None:
        rows = _snapshot()
        rows["schedule_versions"][0].update(schedule_precision="date_only", scheduled_at="2026-08-27T09:50:00Z")
        rows["forecast_versions"][0]["measure_id"] = "US_CPI.MOM"
        errors = validate_snapshot(rows)["errors"]
        self.assertEqual(errors["timezone_anomaly"], 1)
        self.assertGreater(errors["measure_mismatch"], 0)

    def test_bad_value_and_timestamp_are_reported_without_crashing(self) -> None:
        rows = _snapshot()
        rows["observations"].append({**rows["observations"][0],
                                     "value": "invalid", "collected_at": "broken"})
        errors = validate_snapshot(rows)["errors"]
        self.assertEqual(errors["non_finite"], 1)
        self.assertEqual(errors["temporal_order"], 1)

    def test_equal_values_across_offsets_are_detected_as_duplicates(self) -> None:
        rows = _snapshot()
        duplicate = {**rows["observations"][0],
                     "effective_at": "2026-08-27T10:00:00+09:00", "collected_at": "2026-08-27T10:01:00+09:00"}
        rows["observations"].append(duplicate)
        self.assertEqual(validate_snapshot(rows)["errors"]["unchanged_observation_duplicate"], 1)
        revised = deepcopy(duplicate)
        revised.update(value=2.6, effective_at="2026-08-28T00:00:00Z",
                       collected_at="2026-08-28T00:00:00Z")
        rows["observations"] = [rows["observations"][0], revised,
            {**revised, "value": 2.5, "effective_at": "2026-08-29T00:00:00Z",
             "collected_at": "2026-08-29T00:00:00Z"}]
        self.assertEqual(validate_snapshot(rows)["errors"]["unchanged_observation_duplicate"], 0)


if __name__ == "__main__":
    unittest.main()
