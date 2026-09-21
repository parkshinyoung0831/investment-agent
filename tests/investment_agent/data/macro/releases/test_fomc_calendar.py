"""FOMC official calendar parser의 좁은 markup contract."""
from __future__ import annotations

import unittest
from datetime import date

from investment_agent.data.macro.infrastructure.releases.sources.fomc_calendar import _current_dates, _historical_dates


class FomcCalendarTest(unittest.TestCase):
    def test_current_page_keeps_future_meetings_without_statement_links(self) -> None:
        document = """
        <div class='panel'>
          <h4>2025 FOMC Meetings</h4>
          <div class='row fomc-meeting'><div class='fomc-meeting__month'>January</div>
            <div class='fomc-meeting__date'>28-29</div><strong>Statement:</strong></div>
          <div class='row fomc-meeting'><div class='fomc-meeting__month'>September</div>
            <div class='fomc-meeting__date'>16-17*</div></div>
          <div class='row fomc-notice'><div class='fomc-meeting__month'>August</div>
            <div class='fomc-meeting__date'>22</div><a>Statement on Longer-Run Goals</a></div>
        </div>
        """
        self.assertEqual(_current_dates(document), [date(2025, 1, 29), date(2025, 9, 17)])

    def test_historical_page_uses_last_meeting_day(self) -> None:
        document = "<h5>Jan/Feb 31-1 Meeting - 2017</h5><h5>March 14-15 Meeting - 2017</h5>"
        self.assertEqual(_historical_dates(document, expected_year=2017), [date(2017, 2, 1), date(2017, 3, 15)])

    def test_a_window_in_a_later_year_still_reads_the_current_page(self) -> None:
        """페이지가 다루는 마지막 연도를 코드에 박아 두면 그 해가 지난 뒤의 창은 페이지를 읽지도 않고 빈 일정이 된다."""
        from unittest import mock

        from investment_agent.data.macro.infrastructure.releases.sources import fomc_calendar

        document = """
        <div class='panel'><h4>2029 FOMC Meetings</h4>
          <div class='row fomc-meeting'><div class='fomc-meeting__month'>January</div>
            <div class='fomc-meeting__date'>30-31</div></div></div>
        """
        with mock.patch.object(fomc_calendar, "_fetch", return_value=document) as fetch:
            found = fomc_calendar.fetch_dates(start=date(2029, 1, 1), end=date(2029, 12, 31))
        self.assertEqual([date(2029, 1, 31)], found)
        fetch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
