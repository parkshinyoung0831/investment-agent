"""주간 캘린더 카드가 대상 분기의 컨센서스를 일정 행에 붙이는 규칙."""
from __future__ import annotations

import unittest
from datetime import date

from investment_agent.reporting.notifications.earnings_calendar import attach_consensus
from investment_agent.reporting.services.earnings import schedule


def _schedule(security_id: int, year: int, period: str, snapshot: str) -> dict:
    return {
        "security_id": security_id, "ticker": "COST", "snapshot_date": snapshot,
        "target_fiscal_year": year, "target_fiscal_period": period,
        "target_period_end": "2026-08-30", "expected_report_date": "2026-09-24",
    }


CONSENSUS = {
    (7, 2026, "Q4"): {"eps_avg": 6.53, "eps_analysts": 28, "revenue_avg": 94_885_845_990.0,
                      "revenue_analysts": 26},
}


class AttachConsensusTest(unittest.TestCase):
    def test_consensus_of_the_target_period_is_attached(self) -> None:
        (row,) = attach_consensus([_schedule(7, 2026, "Q4", "2026-09-13")], CONSENSUS)

        self.assertEqual(6.53, row["eps_avg"])
        self.assertEqual(28, row["eps_analysts"])
        self.assertEqual(94_885_845_990.0, row["revenue_avg"])

    def test_every_version_of_the_same_schedule_gets_it(self) -> None:
        """예정일이 바뀐 이력(shifted 판정)이 컨센서스 때문에 갈라지면 안 된다."""
        rows = attach_consensus(
            [_schedule(7, 2026, "Q4", "2026-09-06"), _schedule(7, 2026, "Q4", "2026-09-13")],
            CONSENSUS,
        )

        self.assertEqual([6.53, 6.53], [row["eps_avg"] for row in rows])

    def test_another_target_period_is_not_mixed_in(self) -> None:
        (row,) = attach_consensus([_schedule(7, 2027, "Q1", "2026-09-13")], CONSENSUS)

        self.assertNotIn("eps_avg", row)

    def test_a_schedule_without_live_consensus_is_left_untouched(self) -> None:
        original = _schedule(9, 2026, "Q4", "2026-09-13")

        (row,) = attach_consensus([original], CONSENSUS)

        self.assertEqual(original, row)

    def test_the_input_rows_are_not_mutated(self) -> None:
        original = _schedule(7, 2026, "Q4", "2026-09-13")

        attach_consensus([original], CONSENSUS)

        self.assertNotIn("eps_avg", original)

    def test_the_calendar_row_shows_consensus_end_to_end(self) -> None:
        """리더가 붙인 값이 카드 행까지 가야 한다 — 예전에는 이 칸이 조용히 비었다."""
        rows = schedule.build_rows(
            attach_consensus([_schedule(7, 2026, "Q4", "2026-09-13")], CONSENSUS),
            [], {}, date(2026, 9, 21),
        )

        self.assertEqual("$94.9B", rows[0]["revenue_avg"])
        self.assertEqual(28, rows[0]["eps_analysts"])
        self.assertEqual(6.53, rows[0]["eps_avg"])


if __name__ == "__main__":
    unittest.main()
