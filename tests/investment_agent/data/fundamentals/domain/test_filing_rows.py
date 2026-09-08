"""부모 `filings` 행을 만드는 일은 어떤 입력으로 와도 같아야 한다.

`Filing`(저장 계약)과 `FilingRef`(원문 읽기 전 참조)는 일부러 다른 타입이다.
그런데 쓰는 쪽마다 `as_row()`를 직접 부르고 있어서, 참조가 섞여 오는 backfill
경로가 `AttributeError: 'FilingRef' object has no attribute 'as_row'`로 죽었다 —
첫 기업에서 멈췄고 회사 재무가 한 줄도 들어오지 않았다.
"""
from __future__ import annotations

import unittest
from datetime import date

from investment_agent.data.fundamentals.domain import filings

_KEYS = {"accession_no", "cik", "form_type", "filing_date", "report_date", "source"}


class FilingRowAcceptsEveryShapeTest(unittest.TestCase):
    def test_a_storage_filing_keeps_its_own_row(self) -> None:
        filing = filings.Filing(
            accession_no="0000320193-25-000073", cik="0000320193", form_type="10-Q",
            filing_date=date(2025, 8, 1), report_date=date(2025, 6, 28), source="sec_edgar",
        )
        self.assertEqual(filing.as_row(), filings.filing_row(filing))

    def test_a_reference_becomes_the_same_row_shape(self) -> None:
        ref = filings.FilingRef(
            accession_no="0000320193-25-000073", filing_date="2025-08-01",
            report_date="2025-06-28", form_type="10-Q",
        )
        row = filings.filing_row(ref, "320193")
        self.assertEqual(_KEYS, set(row))
        self.assertEqual("0000320193", row["cik"])
        self.assertEqual("sec_edgar", row["source"])

    def test_a_reference_keeps_its_own_cik_over_the_context(self) -> None:
        ref = filings.FilingRef(
            accession_no="0000320193-25-000073", filing_date="2025-08-01",
            report_date="2025-06-28", form_type="10-Q", cik=320193,
        )
        self.assertEqual("0000320193", filings.filing_row(ref, "999")["cik"])

    def test_a_mapping_becomes_the_same_row_shape(self) -> None:
        row = filings.filing_row({
            "accession_no": "0000320193-25-000073", "form_type": "10-K",
            "accepted_date": "2025-11-01",
        }, "320193")
        self.assertEqual(_KEYS, set(row))
        self.assertEqual("2025-11-01", row["filing_date"])

    def test_an_unknown_shape_is_refused_with_the_domain_error(self) -> None:
        with self.assertRaises(filings.FilingError):
            filings.filing_row(object())


if __name__ == "__main__":
    unittest.main()
