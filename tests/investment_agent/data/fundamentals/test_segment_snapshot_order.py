"""세그먼트 스냅샷이 고르는 20행은 조회 순서에 흔들리지 않는다.

정렬 기준이 매출 하나뿐이면 매출이 없는 행들이 전부 동점이고, 파이썬 정렬은
안정적이라 **입력 순서가 곧 결과**가 된다. 실제로 그랬다 — 같은 종목을 따로
물었을 때와 여러 종목을 묶어 물었을 때 BRK-B 카드에 다른 세그먼트가 실렸다.
어느 쪽이 옳다고 말할 수 없는 차이라서 더 나쁘다.
"""
from __future__ import annotations

import random
import unittest

from investment_agent.data.fundamentals.infrastructure.supabase.segment_metrics import (
    _SNAPSHOT_METRIC_COLUMNS,
    _SNAPSHOT_METRICS,
    _select_snapshot,
)

FILINGS = [{"accession_no": "a1", "filing_date": "2026-05-01"}]


def _metrics() -> list[dict]:
    rows = [
        {"accession_no": "a1", "axis": "BusinessSegments", "member": f"M{index:02d}",
         "secondary_member": None, "revenue": None}
        for index in range(_SNAPSHOT_METRICS + 15)
    ]
    rows.append({"accession_no": "a1", "axis": "BusinessSegments", "member": "Big",
                 "secondary_member": None, "revenue": 1_000})
    return rows


class SegmentSnapshotOrderTest(unittest.TestCase):
    def _members(self, rows: list[dict]) -> list[str]:
        snapshot = _select_snapshot("BRK-B", FILINGS, rows)
        return [row["member"] for row in snapshot["metrics"]]

    def test_the_same_rows_in_a_different_order_give_the_same_twenty(self) -> None:
        rows = _metrics()
        shuffled = list(rows)
        random.Random(7).shuffle(shuffled)
        self.assertEqual(self._members(rows), self._members(shuffled))

    def test_rows_with_revenue_still_come_first(self) -> None:
        self.assertEqual("Big", self._members(_metrics())[0])

    def test_the_cut_keeps_the_declared_size(self) -> None:
        self.assertEqual(_SNAPSHOT_METRICS, len(self._members(_metrics())))


class SegmentSnapshotScopeTest(unittest.TestCase):
    """스냅샷은 공시가 직접 보고한 1차원 행만 담는다.

    10-K accession에는 FY와 그것에서 파생한 Q4가 함께 있고, 교차표 행은 주 축 이름을
    공유한다. 섞이면 같은 매출이 두 번 세어져 매매 후보의 집중도(HHI)가 틀린다.
    """

    def test_derived_and_cross_tab_rows_are_left_out(self) -> None:
        rows = [
            {"accession_no": "a1", "axis": "BusinessSegments", "member": "A",
             "secondary_axis": None, "secondary_member": None, "is_derived": False, "revenue": 800},
            {"accession_no": "a1", "axis": "BusinessSegments", "member": "A",
             "secondary_axis": None, "secondary_member": None, "is_derived": True, "revenue": 200},
            {"accession_no": "a1", "axis": "BusinessSegments", "member": "A",
             "secondary_axis": "Geographical", "secondary_member": "US",
             "is_derived": False, "revenue": 500},
        ]
        snapshot = _select_snapshot("AMD", FILINGS, rows)
        self.assertEqual([800], [row["revenue"] for row in snapshot["metrics"]])

    def test_snapshot_reads_the_derivation_flag(self) -> None:
        self.assertIn("is_derived", _SNAPSHOT_METRIC_COLUMNS.split(","))


if __name__ == "__main__":
    unittest.main()
