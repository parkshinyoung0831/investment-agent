"""발표가 옮겨지거나 사라져 소스가 더는 주지 않는 미래 일정은 취소로 남는다(DA-11).

안 남기면 옛 이벤트가 "예정"으로 영영 남아 캘린더에 유령이 되고, 지나면 `not_available_yet`로 굳는다.
"""
from __future__ import annotations

import unittest
from datetime import date

from investment_agent.data.macro.application.release_calendar import stale_future_events

TODAY, END = date(2026, 9, 21), date(2026, 12, 20)


def _version(scheduled_at: str, *, source: str = "official_calendar", cancelled: bool = False) -> dict:
    return {"scheduled_at": scheduled_at, "source": source, "schedule_precision": "exact", "is_cancelled": cancelled}


def _stale(index, fresh=frozenset(), synced=("US_CPI",)):
    return stale_future_events(index, set(fresh), synced_series=set(synced), today=TODAY, end=END)


class StaleFutureEventsTest(unittest.TestCase):
    def test_an_event_the_source_no_longer_lists_is_cancelled(self) -> None:
        index = {("US_CPI", "2026-10-01"): _version("2026-10-30T12:30:00+00:00")}
        (row,) = _stale(index)
        self.assertEqual(("US_CPI", "2026-10-01", True), (row["series_id"], row["ref_period"], row["is_cancelled"]))
        self.assertEqual("2026-10-30T12:30:00+00:00", row["scheduled_at"])

    def test_an_event_the_source_still_lists_is_kept(self) -> None:
        index = {("US_CPI", "2026-10-01"): _version("2026-10-30T12:30:00+00:00")}
        self.assertEqual([], _stale(index, fresh={("US_CPI", "2026-10-01")}))

    def test_what_this_sync_did_not_read_is_left_alone(self) -> None:
        index = {
            ("US_CPI", "2027-03-01"): _version("2027-03-30T12:30:00+00:00"),                 # 창 밖
            ("US_CPI", "2026-08-01"): _version("2026-09-10T12:30:00+00:00"),                 # 이미 지난 발표
            ("US_NFP", "2026-10-01"): _version("2026-10-02T12:30:00+00:00"),                 # 이번에 읽기 실패한 지표
            ("US_CPI", "2026-09-01"): _version("2026-10-14T12:30:00+00:00", source="alfred_first_print"),  # 다른 출처
            ("US_CPI", "2026-10-01"): _version("2026-10-30T12:30:00+00:00", cancelled=True),  # 이미 취소
        }
        self.assertEqual([], _stale(index, synced=("US_CPI",)))


if __name__ == "__main__":
    unittest.main()
