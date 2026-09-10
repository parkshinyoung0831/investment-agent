"""AI 경제 근거는 macro owner가 실제로 주는 행 모양 위에서 조립된다.

전에는 이 검사가 손으로 지어낸 `record_kind` 행을 넣어 통과했다. 그 키는 owner의
계약에 없다 — `econ_snapshot`은 실제 행을 만나면 첫 줄에서 KeyError로 죽었고,
그 사실은 통합 점검에서만 드러났다. 그래서 여기서는 owner가 선언한
`SUMMARY_ROW_KEYS`로 행을 만든다: 계약이 바뀌면 이 검사가 먼저 깨진다.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from investment_agent.data.macro.releases import db as econ_db
from investment_agent.trading import supabase_repository as db

MOMENT = datetime(2026, 8, 10, tzinfo=timezone.utc)


def _summary_row(**overrides: object) -> dict:
    """owner의 계약에 있는 키만으로 행 하나를 만든다."""
    row = {key: None for key in econ_db.SUMMARY_ROW_KEYS}
    row.update({
        "event_key": "US_CPI:2026-07-01", "series_id": "US_CPI", "ref_period": "2026-07-01",
        "series_name_ko": "소비자물가", "unit": "percent", "frequency": "monthly",
        "scheduled_at": "2026-08-12T12:30:00+00:00", "schedule_confidence": "exact",
        "status": "scheduled",
    })
    row.update(overrides)
    return row


class EconSnapshotShapeTest(unittest.TestCase):
    def _snapshot(self, rows: list[dict]) -> dict:
        with patch.object(econ_db, "select_snapshot_rows", return_value=rows):
            return db.SupabaseRepository().econ_snapshot(MOMENT)

    def test_the_reader_only_touches_keys_the_owner_declares(self) -> None:
        for key in db._ECON_RELEASE_KEYS + db._ECON_FORECAST_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, econ_db.SUMMARY_ROW_KEYS)

    def test_a_scheduled_release_is_an_event_and_nothing_else(self) -> None:
        result = self._snapshot([_summary_row()])
        self.assertEqual(1, len(result["events"]))
        self.assertEqual([], result["results"])
        self.assertEqual([], result["forecasts"])

    def test_future_schedule_uses_snapshot_cutoff_as_availability(self) -> None:
        result = self._snapshot([_summary_row()])
        self.assertEqual(result["events"][0]["collected_at"], MOMENT.isoformat())
        self.assertEqual(result["events"][0]["scheduled_at"], "2026-08-12T12:30:00+00:00")

    def test_a_released_value_also_becomes_a_result(self) -> None:
        result = self._snapshot([_summary_row(status="released", latest_actual_value=0.2,
                                              first_actual_value=0.1, revision=0.1)])
        self.assertEqual(0.2, result["results"][0]["actual"])
        self.assertEqual(0.1, result["results"][0]["revision"])

    def test_market_consensus_wins_over_the_own_model(self) -> None:
        """자체 모델은 컨센서스가 없을 때의 대체지 같은 무게의 근거가 아니다."""
        result = self._snapshot([_summary_row(closing_survey_value=0.3,
                                              closing_own_model_value=0.9)])
        self.assertEqual(0.3, result["forecasts"][0]["forecast"])

    def test_the_own_model_is_used_when_nothing_else_exists(self) -> None:
        result = self._snapshot([_summary_row(closing_own_model_value=0.9)])
        self.assertEqual(0.9, result["forecasts"][0]["forecast"])

    def test_each_list_is_capped_so_the_prompt_stays_under_the_provider_limit(self) -> None:
        rows = [_summary_row(event_key=f"US_CPI:2026-{n:02d}-01", latest_actual_value=0.1,
                             closing_survey_value=0.2) for n in range(1, 13)]
        rows *= 3
        result = self._snapshot(rows)
        for kind in ("events", "results", "forecasts"):
            with self.subTest(kind=kind):
                self.assertEqual(db.ECON_MAX_ROWS_PER_KIND, len(result[kind]))


if __name__ == "__main__":
    unittest.main()
