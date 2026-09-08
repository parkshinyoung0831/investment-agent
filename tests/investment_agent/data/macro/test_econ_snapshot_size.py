"""경제 근거가 evidence bundle을 삼키지 않게 한다.

실측(2026-09-03): 번들 202,724자 중 economic_calendar가 140,084자(69%)였고 그
상태로는 Groq·Azure·Gemini 어느 쪽도 프롬프트를 받지 않았다.

행은 macro owner가 선언한 계약(`SUMMARY_ROW_KEYS`)으로만 짓는다 — 지어낸 모양
위에서 크기를 재면, 실제 행이 그 모양이 아니게 된 날 검사가 조용히 무의미해진다.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from investment_agent.data.macro.releases import db as econ_db
from investment_agent.trading import supabase_repository as db

MOMENT = datetime(2026, 8, 10, tzinfo=timezone.utc)


def _rows(count: int) -> list[dict]:
    out = []
    for index in range(count):
        scheduled = MOMENT + timedelta(days=index - count // 2)
        row = {key: None for key in econ_db.SUMMARY_ROW_KEYS}
        row.update({
            "event_key": f"US_CPI:{index}", "series_id": "US_CPI",
            "ref_period": "2026-07-01", "series_name_ko": "소비자물가",
            "unit": "percent", "frequency": "monthly", "status": "released",
            "schedule_confidence": "exact", "scheduled_at": scheduled.isoformat(),
            "first_actual_at": scheduled.isoformat(),
            "latest_actual_value": 0.2, "first_actual_value": 0.1,
            "closing_survey_value": 0.3, "source": f"src_{index}",
        })
        out.append(row)
    return out


def _snapshot(rows: list[dict], **kwargs) -> dict:
    with patch.object(econ_db, "select_snapshot_rows", return_value=rows):
        return db.SupabaseRepository().econ_snapshot(MOMENT, **kwargs)


class EconSnapshotSizeTest(unittest.TestCase):
    def test_fields_are_not_stored_twice_in_the_same_row(self):
        """release 그룹에 이미 있는 값을 평면 키로 또 담으면 프롬프트만 커진다."""
        row = _snapshot(_rows(1))["forecasts"][0]
        for duplicated in db._ECON_RELEASE_KEYS:
            self.assertNotIn(duplicated, row, duplicated)

    def test_the_release_group_survives(self):
        row = _snapshot(_rows(1))["forecasts"][0]
        self.assertEqual("US_CPI:0", row["release"]["event_key"])
        self.assertEqual(0.3, row["forecast"])

    def test_row_count_is_capped_per_kind(self):
        result = _snapshot(_rows(60), max_rows_per_kind=10)
        for kind in ("events", "results", "forecasts"):
            with self.subTest(kind=kind):
                self.assertEqual(10, len(result[kind]))

    def test_the_kept_rows_are_the_ones_closest_to_the_cutoff(self):
        result = _snapshot(_rows(60), max_rows_per_kind=4)
        kept = [row["release"]["scheduled_at"] for row in result["forecasts"]]
        distances = [
            abs((datetime.fromisoformat(value) - MOMENT).total_seconds()) for value in kept
        ]
        self.assertLessEqual(max(distances), 2 * 86400)

    def test_capping_shrinks_the_serialised_payload(self):
        rows = _rows(60)
        big = json.dumps(_snapshot(rows, max_rows_per_kind=60), ensure_ascii=False)
        small = json.dumps(_snapshot(rows, max_rows_per_kind=10), ensure_ascii=False)
        self.assertLess(len(small), len(big) // 3)


if __name__ == "__main__":
    unittest.main()
