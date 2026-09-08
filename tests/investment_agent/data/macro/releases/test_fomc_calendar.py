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


if __name__ == "__main__":
    unittest.main()
