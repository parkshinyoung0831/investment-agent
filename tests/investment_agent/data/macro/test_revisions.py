"""정정이 쌓인 더미에서 '그때의 값'을 정확히 골라야 한다."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from investment_agent.data.macro.domain.revisions import (
    MacroDataError,
    Observation,
    first_print,
    latest_known_at,
    revision_size,
    series_as_of,
)


def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _obs(
    value: float,
    *,
    period: date = date(2026, 7, 1),
    effective: datetime,
    collected: datetime | None = None,
    precision: str = "exact",
) -> Observation:
    return Observation(
        series_id="PAYEMS",
        ref_period=period,
        value=value,
        effective_at=effective,
        collected_at=collected or effective,
        time_precision=precision,
    )


FIRST = _obs(100.0, effective=_utc(2026, 8, 1, 12))
SECOND = _obs(95.0, effective=_utc(2026, 9, 1, 12))
THIRD = _obs(93.0, effective=_utc(2026, 10, 1, 12))


class KnownAtTest(unittest.TestCase):
    def test_a_value_is_not_known_before_it_is_published(self) -> None:
        self.assertFalse(FIRST.known_at(_utc(2026, 8, 1, 11)))
        self.assertTrue(FIRST.known_at(_utc(2026, 8, 1, 13)))

    def test_late_collection_delays_when_we_knew_it(self) -> None:
        """발표됐어도 우리가 손에 넣지 못했으면 쓸 수 없었다."""
        late = _obs(100.0, effective=_utc(2026, 8, 1, 12), collected=_utc(2026, 8, 5, 12))
        self.assertFalse(late.known_at(_utc(2026, 8, 3)))
        self.assertTrue(late.known_at(_utc(2026, 8, 6)))

    def test_date_only_precision_waits_a_day(self) -> None:
        """그날 몇 시인지 모르는 값을 장중에 알았다고 가정하면 미래를 본다."""
        rough = _obs(100.0, effective=_utc(2026, 8, 1), precision="date_only")
        self.assertFalse(rough.known_at(_utc(2026, 8, 1, 23)))
        self.assertTrue(rough.known_at(_utc(2026, 8, 2, 1)))


class FirstPrintTest(unittest.TestCase):
    def test_the_earliest_publication_wins(self) -> None:
        self.assertEqual(FIRST, first_print([THIRD, FIRST, SECOND]))

    def test_nothing_is_none(self) -> None:
        self.assertIsNone(first_print([]))


class LatestKnownAtTest(unittest.TestCase):
    def test_only_revisions_we_already_had_are_visible(self) -> None:
        chosen = latest_known_at([FIRST, SECOND, THIRD], _utc(2026, 9, 15))
        self.assertEqual(95.0, chosen.value)

    def test_before_the_first_publication_there_is_nothing(self) -> None:
        self.assertIsNone(latest_known_at([FIRST, SECOND], _utc(2026, 7, 1)))

    def test_after_everything_the_last_revision_wins(self) -> None:
        self.assertEqual(93.0, latest_known_at([FIRST, SECOND, THIRD], _utc(2027, 1, 1)).value)


class SeriesAsOfTest(unittest.TestCase):
    def test_each_period_picks_its_own_version(self) -> None:
        """시계열을 통째로 최신으로 채우면 과거 기간에 미래 값이 들어간다."""
        july_first = _obs(100.0, period=date(2026, 7, 1), effective=_utc(2026, 8, 1))
        july_revised = _obs(95.0, period=date(2026, 7, 1), effective=_utc(2026, 10, 1))
        august = _obs(110.0, period=date(2026, 8, 1), effective=_utc(2026, 9, 1))

        seen = series_as_of([july_first, july_revised, august], _utc(2026, 9, 15))
        self.assertEqual({date(2026, 7, 1): 100.0, date(2026, 8, 1): 110.0}, seen)

    def test_periods_not_yet_published_are_absent(self) -> None:
        seen = series_as_of([FIRST, SECOND], _utc(2026, 7, 15))
        self.assertEqual({}, seen)


class RevisionSizeTest(unittest.TestCase):
    def test_change_from_the_first_print(self) -> None:
        self.assertAlmostEqual(-7.0, revision_size([FIRST, SECOND, THIRD]))

    def test_a_single_version_has_no_revision(self) -> None:
        self.assertIsNone(revision_size([FIRST]))


class ObservationRowTest(unittest.TestCase):
    def _row(self, **overrides: object) -> dict:
        row = {
            "series_id": "PAYEMS",
            "ref_period": "2026-07-01",
            "value": 100.0,
            "effective_at": "2026-08-01T12:00:00+00:00",
            "collected_at": "2026-08-01T12:05:00+00:00",
            "time_precision": "exact",
        }
        row.update(overrides)
        return row

    def test_a_readable_row_becomes_an_observation(self) -> None:
        observation = Observation.from_row(self._row())
        self.assertEqual(date(2026, 7, 1), observation.ref_period)
        self.assertEqual(timezone.utc, observation.effective_at.tzinfo)

    def test_a_nan_value_is_refused(self) -> None:
        with self.assertRaises(MacroDataError):
            Observation.from_row(self._row(value=float("nan")))

    def test_an_unknown_precision_is_refused(self) -> None:
        """모르는 정밀도를 기본값으로 삼키면 PIT 경계가 조용히 헐거워진다."""
        with self.assertRaises(MacroDataError):
            Observation.from_row(self._row(time_precision="roughly"))

    def test_an_unreadable_period_is_refused(self) -> None:
        with self.assertRaises(MacroDataError):
            Observation.from_row(self._row(ref_period="not-a-date"))


if __name__ == "__main__":
    unittest.main()
