"""예상치 상태 저장이 돌려주는 수는 관측한 상태 수다."""
from __future__ import annotations

import unittest
from unittest import mock

from investment_agent.data.fundamentals.infrastructure.supabase import expectations


class WriteVersionsCountTest(unittest.TestCase):
    def test_unchanged_states_count_as_observed(self) -> None:
        stored = [{
            "security_id": 1, "source": "yfinance", "snapshot_date": "2026-09-01",
            "collected_at": "2026-09-01T00:00:00+00:00", "last_seen_at": "2026-09-01T00:00:00+00:00",
            "target_mean": 10.0,
        }]
        upserts: list[list[dict]] = []
        with (
            mock.patch.object(expectations, "_with_security_id",
                              side_effect=lambda rows: [{**row, "security_id": 1} for row in rows]),
            mock.patch.object(expectations, "select_paged_in_chunks", return_value=stored),
            mock.patch.object(expectations, "_upsert", side_effect=lambda _t, rows, _pk: upserts.append(rows)),
        ):
            written = expectations._write_versions(
                "analyst_consensus_snapshots",
                [{"ticker": "AAPL", "source": "yfinance", "snapshot_date": "2026-09-14", "target_mean": 10.0}],
                key=("security_id", "source"), values=("target_mean",), pk="security_id,source,snapshot_date",
            )

        # 값이 같아 새 버전은 없지만 확인 한 건을 관측으로 센다. 0이면 일일 수집이 붕괴로 판정된다.
        self.assertEqual(1, written)
        self.assertEqual([[], ], upserts[:1])


if __name__ == "__main__":
    unittest.main()
