"""정정 공시는 자기가 보고한 컬럼만 원본 값 위에 덮는다."""
from __future__ import annotations

import unittest

from investment_agent.data.fundamentals.domain.services.reported_observations import to_wide_tables

ORIGINAL = "0000000001-26-000001"
AMENDMENT = "0000000001-26-000009"


def _fact(concept: str, column_key: str, value: float, *, accession_no: str, filed_at: str,
          qtrs: int, period_start: str | None) -> dict:
    return {
        "cik": "0000000001", "statement": "IS" if qtrs else "BS", "concept": concept,
        "standard_tag": column_key, "column_key": column_key, "fiscal_year": 2026,
        "fiscal_period": "Q1", "qtrs": qtrs, "form_type": "10-Q",
        "period_start": period_start, "period_end": "2026-03-31", "value": value, "unit": "USD",
        "filed_at": filed_at, "accession_no": accession_no, "is_derived": False,
    }


class AmendmentMergeTest(unittest.TestCase):
    def test_columns_the_amendment_did_not_report_keep_the_original_values(self) -> None:
        facts = [
            _fact("Revenues", "revenue", 100, accession_no=ORIGINAL, filed_at="2026-05-01",
                  qtrs=1, period_start="2026-01-01"),
            _fact("Assets", "assets", 1_000, accession_no=ORIGINAL, filed_at="2026-05-01",
                  qtrs=0, period_start=None),
            _fact("Revenues", "revenue", 110, accession_no=AMENDMENT, filed_at="2026-07-01",
                  qtrs=1, period_start="2026-01-01"),
        ]

        rows, _anomalies = to_wide_tables(facts)

        self.assertEqual(1, len(rows))
        self.assertEqual((110, 1_000), (rows[0]["revenue"], rows[0]["assets"]))
        self.assertEqual(AMENDMENT, rows[0]["accession_no"])


if __name__ == "__main__":
    unittest.main()
