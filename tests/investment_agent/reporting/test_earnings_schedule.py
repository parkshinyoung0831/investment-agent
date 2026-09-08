from __future__ import annotations

import unittest
from datetime import date

from investment_agent.reporting.services.earnings import schedule


class EarningsScheduleContractTest(unittest.TestCase):
    """발표 예정 read model은 Reporting이 소유하고 알림은 그것을 재노출한다."""

    SNAPSHOTS = [
        {
            "ticker": "AAPL",
            "snapshot_date": "2026-08-20",
            "expected_report_date": "2026-08-27",
            "target_period_end": "2026-06-27",
            "target_fiscal_year": 2026,
            "target_fiscal_period": "Q3",
            "eps_avg": 1.42,
            "eps_analysts": 28,
            "revenue_avg": 89_000_000_000,
        },
        {
            "ticker": "AAPL",
            "snapshot_date": "2026-08-10",
            "expected_report_date": "2026-08-25",
            "target_period_end": "2026-06-27",
            "target_fiscal_year": 2026,
            "target_fiscal_period": "Q3",
        },
    ]
    FILINGS = [
        {
            "ticker": "AAPL",
            "period_end": "2025-06-28",
            "filed_at": "2025-08-01",
            "fiscal_year": 2025,
            "fiscal_period": "Q3",
        }
    ]
    NAMES = {"AAPL": {"name_ko": "애플", "sic_industry": "Electronic Computers"}}

    def _rows(self, module) -> list[dict]:
        return module.build_rows_in_window(
            self.SNAPSHOTS,
            self.FILINGS,
            self.NAMES,
            date(2026, 8, 24),
            start=date(2026, 8, 24),
            end=date(2026, 8, 30),
        )

    def test_window_rows_carry_shift_grade_and_prior_filing(self) -> None:
        rows = self._rows(schedule)
        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("AAPL", row["ticker"])
        self.assertEqual("애플", row["name"])
        self.assertEqual(date(2026, 8, 27), row["expected"])
        # 같은 회계기간에 예정일이 바뀐 적이 있으므로 shifted이고 이전 값을 함께 낸다.
        self.assertEqual("shifted", row["confidence"])
        self.assertEqual(date(2026, 8, 25), row["previous_expected"])
        self.assertEqual("10-Q", row["form_expected"])
        self.assertEqual(date(2025, 8, 1), row["prior_filed_at"])
        self.assertEqual("$89.0B", row["revenue_avg"])

    def test_week_window_and_iso_week_stay_stable(self) -> None:
        self.assertEqual(
            (date(2026, 8, 24), date(2026, 8, 30)),
            schedule.week_window(date(2026, 8, 27)),
        )
        self.assertEqual("2026-W35", schedule.iso_week(date(2026, 8, 27)))
