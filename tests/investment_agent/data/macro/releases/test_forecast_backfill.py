"""ALFRED forecast reconstruction이 measure/PIT 계약을 지키는지 검사한다."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from investment_agent.data.macro.commands import econ_calendar_backfill as backfill


class HistoricalForecastTest(unittest.TestCase):
    def test_non_alfred_series_can_be_backfilled_on_its_own(self) -> None:
        from investment_agent.data.macro.application import release_calendar as etl
        from investment_agent.data.macro.releases import db
        from investment_agent.data.macro.infrastructure.releases.sources import actuals, alfred

        setting = {"series_id": "EIA_CRUDE_OIL_INVENTORIES", "actual_provider": "eia", "revision_provider": "none"}
        with (patch("investment_agent.platform.db.postgres.Database.from_config"),
              patch.object(db, "configure"),
              patch.object(db, "seed_catalog"),
              patch.object(db, "collectible_series", return_value=[setting]),
              patch.object(alfred, "fetch_batch", return_value=({}, [])),
              patch.object(actuals, "fetch_batch", return_value=({setting["series_id"]: []}, [])) as fetch,
              patch.object(etl, "sync_schedules", return_value=({"candidate_releases": 0}, [])) as schedules,
              patch.object(db, "upsert_releases", return_value={}),
              patch.object(etl, "ingest_raw", return_value={"observations_inserted": 0})):
            result = backfill.main(["--backfill-from", "2024-01-01", "--series", setting["series_id"], "--no-revisions", "--no-forecasts"])
        self.assertEqual(result, 0)
        self.assertEqual(fetch.call_args.args[0], [setting])
        self.assertEqual(schedules.call_args.kwargs["series_ids"], {setting["series_id"]})

    def test_own_model_is_measure_level_and_pre_release_only(self) -> None:
        fetched = {
            "US_UNEMPLOYMENT": [
                {"ref_period": "2025-01-01", "released_on": "2025-02-07", "value": 4.0},
                {"ref_period": "2025-02-01", "released_on": "2025-03-07", "value": 4.1},
                {"ref_period": "2025-03-01", "released_on": "2025-04-04", "value": 4.2},
                {"ref_period": "2025-04-01", "released_on": "2025-05-02", "value": 4.1},
            ]
        }
        settings = {"US_UNEMPLOYMENT": {
            "frequency": "monthly", "forecast_measure_id": "US_UNEMPLOYMENT.LEVEL",
        }}
        releases = {
            ("US_UNEMPLOYMENT", row["ref_period"]): {
                "series_id": "US_UNEMPLOYMENT", "ref_period": row["ref_period"],
                "scheduled_at": f"{row['released_on']}T13:30:00+00:00",
            }
            for index, row in enumerate(fetched["US_UNEMPLOYMENT"], start=1)
        }
        measures = {
            "US_UNEMPLOYMENT": [{
                "measure_id": "US_UNEMPLOYMENT.LEVEL", "is_primary": True, "transform": "level",
            }]
        }
        rows = backfill._historical_own_model_rows(
            fetched=fetched, settings=settings, release_map=releases, measures=measures,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["measure_id"], "US_UNEMPLOYMENT.LEVEL")
        self.assertEqual(rows[0]["forecast_kind"], "own_model")
        self.assertTrue(rows[0]["provenance"]["not_market_consensus"])
        self.assertLess(rows[0]["as_of"].isoformat(), releases[("US_UNEMPLOYMENT", "2025-04-01")]["scheduled_at"])
        self.assertGreater(rows[0]["collected_at"], rows[0]["as_of"])
        self.assertEqual(rows[0]["collected_at"].date(), datetime.now(timezone.utc).date())

    def test_archive_forecast_preserves_real_collection_time(self) -> None:
        rows = backfill._gdpnow_rows([
            {"ref_period": "2025-04-01", "snapshot_date": "2025-07-15", "value": 2.3},
            {"ref_period": "2025-04-01", "snapshot_date": "2025-07-31", "value": 2.4},
        ], release_map={("US_GDP", "2025-04-01"): {"scheduled_at": "2025-07-30T12:30:00Z"}})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ref_period"], "2025-04-01")
        self.assertEqual(rows[0]["time_precision"], "date_only")
        self.assertGreater(rows[0]["collected_at"], rows[0]["as_of"])


if __name__ == "__main__":
    unittest.main()
