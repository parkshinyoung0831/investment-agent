"""macro 저장소가 시장 관측은 최신값으로 덮고, 경제 발표는 버전을 보존하며,
일정 관측을 중복으로 세지 않는지 확인한다."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from investment_agent.data.macro.domain.catalog import MARKET_INDICATOR_CATALOG
from investment_agent.data.macro.repository import (
    DOMAIN_MARKET,
    DOMAIN_RELEASE,
    SCHEMA,
    T_ECONOMIC_OBSERVATIONS,
    T_MARKET_OBSERVATIONS,
    T_RELEASE_SCHEDULE,
    T_SERIES,
    MacroRepository,
)
from investment_agent.data.macro.domain.revisions import Observation
from tests.investment_agent.fakes import FakeDatabase


def _series_row(series_key: int, series_code: str, domain: str) -> dict:
    return {"series_key": series_key, "series_code": series_code, "domain": domain}


def _economic_row(series_key: int, value: float, vintage: str, available: str, *, period: str = "2026-07-01") -> dict:
    return {
        "series_key": series_key, "observation_date": period, "value": value,
        "vintage_at": vintage, "available_at": available, "time_precision": "exact",
    }


class SeriesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = FakeDatabase()
        self.db.put(SCHEMA, T_SERIES, [
            _series_row(1, "VIX", DOMAIN_MARKET),
            _series_row(2, "PAYEMS", DOMAIN_RELEASE),
        ])
        self.repo = MacroRepository(self.db)

    def test_all_series_by_default(self) -> None:
        self.assertEqual(["PAYEMS", "VIX"], self.repo.series_ids())

    def test_domain_narrows_the_list(self) -> None:
        self.assertEqual(["VIX"], self.repo.series_ids(domain=DOMAIN_MARKET))

    def test_an_unknown_domain_is_refused(self) -> None:
        """오타를 빈 목록으로 삼키면 '지표가 없다'는 답을 조용히 받는다."""
        with self.assertRaises(ValueError):
            self.repo.series_ids(domain="markets")


class MarketReaderTest(unittest.TestCase):
    def test_market_catalog_is_the_code_catalog_not_a_db_query(self) -> None:
        """수집 설정은 DB가 아니라 코드 catalog가 소유한다(repository.py 문서 참고).

        DB 조회 없이 ``MARKET_INDICATOR_CATALOG``를 그대로 돌려주므로, 빈 DB에서도
        결과가 같아야 한다.
        """
        repo = MacroRepository(FakeDatabase())
        self.assertEqual(list(MARKET_INDICATOR_CATALOG), repo.market_catalog())

    def test_upsert_series_stores_the_source_name_on_the_series_row(self) -> None:
        db = FakeDatabase()
        db.put(SCHEMA, T_SERIES, [])
        MacroRepository(db).upsert_series([{
            "series_id": "DGS10", "domain": DOMAIN_MARKET, "name_ko": "미국 10년 금리",
            "source": "fred", "source_params": {"fred_id": "DGS10"},
            "frequency": "daily", "unit": "percent", "category": "rates", "series_kind": "rate",
        }])
        (_key, rows, _conflict) = db.upserts[0]
        self.assertEqual("fred", rows[0]["source_code"])
        self.assertEqual("DGS10", rows[0]["provider_series_code"])

    def test_upsert_series_rejects_a_series_without_a_source(self) -> None:
        """원천 이름이 비면 그 series는 어디서 온 값인지 말할 수 없다."""
        db = FakeDatabase()
        with self.assertRaises(ValueError):
            MacroRepository(db).upsert_series([{
                "series_id": "DGS10", "domain": DOMAIN_MARKET, "name_ko": "x",
                "source": "", "frequency": "daily", "unit": "percent",
            }])

    def test_snapshot_as_of_excludes_observation_dates_after_as_of(self) -> None:
        """market_observations는 날짜당 한 행만 있다(버전 없음) — as_of 경계는
        관측일 자체가 미래인 행을 거르는 것으로 지킨다.

        ``observation_snapshot_as_of``는 DB가 아니라 ``market_catalog()``(코드
        catalog)가 열거하는 series만 본다 — 그래서 실제 catalog에 있는 "VIX"를 쓴다.
        """
        db = FakeDatabase()
        db.put(SCHEMA, T_SERIES, [_series_row(7, "VIX", DOMAIN_MARKET)])
        db.put(SCHEMA, T_MARKET_OBSERVATIONS, [
            {"series_key": 7, "observation_date": "2026-08-01", "value": 4.1},
            {"series_key": 7, "observation_date": "2026-09-02", "value": 4.3},
        ])

        snapshot = MacroRepository(db).observation_snapshot_as_of(
            datetime(2026, 9, 1, tzinfo=timezone.utc)
        )
        self.assertEqual(1, len(snapshot["observations"]))
        self.assertEqual(4.1, snapshot["observations"][0]["value"])
        self.assertEqual("available", snapshot["run"]["status"])


class ObservationReadTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = FakeDatabase()
        self.db.put(SCHEMA, T_SERIES, [_series_row(2, "PAYEMS", DOMAIN_RELEASE)])
        self.db.put(SCHEMA, T_ECONOMIC_OBSERVATIONS, [
            _economic_row(2, 100.0, "2026-08-01T12:00:00+00:00", "2026-08-01T12:00:00+00:00"),
            _economic_row(2, 95.0, "2026-09-01T12:00:00+00:00", "2026-09-01T12:00:00+00:00"),
            _economic_row(2, 110.0, "2026-09-01T12:00:00+00:00", "2026-09-01T12:00:00+00:00", period="2026-08-01"),
        ])
        self.repo = MacroRepository(self.db)

    def test_every_version_is_returned_raw(self) -> None:
        """고르는 일은 저장소가 아니라 revisions가 한다."""
        self.assertEqual(3, len(self.repo.observations(["PAYEMS"])))

    def test_values_as_of_hides_later_revisions(self) -> None:
        seen = self.repo.values_as_of("PAYEMS", datetime(2026, 8, 15, tzinfo=timezone.utc))
        self.assertEqual({date(2026, 7, 1): 100.0}, seen)

    def test_values_as_of_later_shows_the_revision(self) -> None:
        seen = self.repo.values_as_of("PAYEMS", datetime(2026, 9, 15, tzinfo=timezone.utc))
        self.assertEqual({date(2026, 7, 1): 95.0, date(2026, 8, 1): 110.0}, seen)

    def test_latest_values_takes_the_newest_period(self) -> None:
        latest = self.repo.latest_values(["PAYEMS"])
        self.assertEqual((date(2026, 8, 1), 110.0), latest["PAYEMS"])


class ReleaseScheduleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = FakeDatabase()
        self.db.put(SCHEMA, T_SERIES, [_series_row(2, "PAYEMS", DOMAIN_RELEASE)])
        self.db.put(SCHEMA, T_RELEASE_SCHEDULE, [
            {"series_key": 2, "ref_period": "2026-07-01",
             "scheduled_at": "2026-08-07T12:30:00+00:00", "schedule_precision": "estimated",
             "is_cancelled": False, "collected_at": "2026-07-01T00:00:00+00:00"},
            # 같은 발표의 나중 관측. 시각이 확정됐다.
            {"series_key": 2, "ref_period": "2026-07-01",
             "scheduled_at": "2026-08-07T12:30:00+00:00", "schedule_precision": "exact",
             "is_cancelled": False, "collected_at": "2026-08-01T00:00:00+00:00"},
        ])
        self.repo = MacroRepository(self.db)

    def test_only_the_last_observation_of_a_release_survives(self) -> None:
        """관측이 쌓인 채로 세면 같은 발표가 여러 번 잡힌다."""
        releases = self.repo.upcoming_releases(on_or_after=date(2026, 8, 1))
        self.assertEqual(1, len(releases))
        self.assertEqual("exact", releases[0]["schedule_precision"])
        self.assertEqual("PAYEMS", releases[0]["series_id"])

    def test_a_cancelled_release_is_dropped(self) -> None:
        self.db.put(SCHEMA, T_RELEASE_SCHEDULE, self.db.tables[(SCHEMA, T_RELEASE_SCHEDULE)] + [
            {"series_key": 2, "ref_period": "2026-07-01",
             "scheduled_at": "2026-08-07T12:30:00+00:00", "schedule_precision": "exact",
             "is_cancelled": True, "collected_at": "2026-08-05T00:00:00+00:00"},
        ])
        self.assertEqual([], self.repo.upcoming_releases(on_or_after=date(2026, 8, 1)))

    def test_past_releases_are_not_upcoming(self) -> None:
        self.assertEqual([], self.repo.upcoming_releases(on_or_after=date(2026, 9, 1)))


class WriteTest(unittest.TestCase):
    def test_the_conflict_key_keeps_every_version(self) -> None:
        """이 키가 좁아지면 정정이 이전 버전을 덮는다."""
        db = FakeDatabase()
        db.put(SCHEMA, T_SERIES, [_series_row(2, "PAYEMS", DOMAIN_RELEASE)])
        MacroRepository(db).record_observations([
            Observation(
                series_id="PAYEMS",
                ref_period=date(2026, 7, 1),
                value=95.0,
                effective_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                collected_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            )
        ], source_code="fred")
        (_key, rows, conflict) = db.upserts[0]
        self.assertEqual("series_key,observation_date,vintage_at,available_at", conflict)
        self.assertEqual("fred", rows[0]["source_code"])
        self.assertEqual(2, rows[0]["series_key"])

    def test_market_observations_conflict_on_date_only_and_carry_no_vintage(self) -> None:
        """시장 지표는 하루 한 값만 유지한다 — 정정 이력을 보존하지 않는 의도적 한계."""
        db = FakeDatabase()
        db.put(SCHEMA, T_SERIES, [_series_row(7, "VIX", DOMAIN_MARKET)])
        MacroRepository(db).record_observations([
            Observation(
                series_id="VIX", ref_period=date(2026, 7, 1), value=18.5,
                effective_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
                collected_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            )
        ], source_code="fred")
        (_key, rows, conflict) = db.upserts[0]
        self.assertEqual("series_key,observation_date", conflict)
        self.assertNotIn("vintage_at", rows[0])
        self.assertNotIn("source_code", rows[0])


if __name__ == "__main__":
    unittest.main()
