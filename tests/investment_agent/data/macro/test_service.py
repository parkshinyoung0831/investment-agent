"""v1 macro writer는 원천 날짜를 가용 시각으로 가장하지 않는다."""
from __future__ import annotations

from datetime import date, datetime, timezone
import unittest

from investment_agent.data.macro.repository import SCHEMA, T_ECONOMIC_OBSERVATIONS, T_SERIES
from investment_agent.data.macro.application.refresh_market_state import refresh_macro
from tests.investment_agent.fakes import FakeDatabase


class MacroWriterTest(unittest.TestCase):
    def test_observations_keep_collection_time_and_source_identity(self) -> None:
        db = FakeDatabase()
        db.put(SCHEMA, T_SERIES, [{"series_key": 11, "series_code": "PAYEMS", "domain": "economic_release"}])
        collected = datetime(2026, 9, 5, 4, 0, tzinfo=timezone.utc)
        result = refresh_macro(
            db,
            catalog=[{
                "series_id": "PAYEMS", "source": "fred", "domain": "economic_release",
                "name_ko": "비농업 고용", "frequency": "monthly", "unit": "천명",
                "country": "US", "timezone": "America/New_York",
            }],
            start=date(2026, 8, 1), end=date(2026, 8, 31), collected_at=collected,
            fetch=lambda _source, _series, _start, _end: (
                {"PAYEMS": {date(2026, 8, 1): 100.0}}, []
            ), persist=True,
        )

        self.assertEqual((1, 1, ()), (result.series, result.observations, result.failures))
        call = [item for item in db.upserts if item[0] == (SCHEMA, T_ECONOMIC_OBSERVATIONS)][0]
        self.assertEqual("fred", call[1][0]["source_code"])
        self.assertEqual(11, call[1][0]["series_key"])
        self.assertEqual(collected.isoformat(), call[1][0]["vintage_at"])
        self.assertEqual("collector_seen", call[1][0]["time_precision"])

    def test_source_failure_does_not_create_fake_zero_observations(self) -> None:
        db = FakeDatabase()
        db.put(SCHEMA, T_SERIES, [{"series_key": 11, "series_code": "PAYEMS", "domain": "economic_release"}])
        result = refresh_macro(
            db,
            catalog=[{"series_id": "PAYEMS", "source": "fred"}],
            start=date(2026, 8, 1), end=date(2026, 8, 31),
            collected_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
            fetch=lambda *_args: (_ for _ in ()).throw(RuntimeError("provider unavailable")), persist=False,
        )

        self.assertEqual(1, len(result.failures))
        self.assertFalse([item for item in db.upserts if item[0] == (SCHEMA, T_ECONOMIC_OBSERVATIONS)])


if __name__ == "__main__":
    unittest.main()
