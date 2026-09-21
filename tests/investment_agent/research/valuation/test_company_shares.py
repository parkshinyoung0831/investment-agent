"""시가총액은 회사 전체(모든 주식 종류) 주식수로 계산한다(RS-9)."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from investment_agent.data.fundamentals.infrastructure.supabase.share_class_snapshots import (
    company_shares_by_filing,
)
from investment_agent.research.valuation.inputs import shares_scalar

_AS_OF = datetime(2026, 9, 1, tzinfo=timezone.utc)
_GOOGL = [  # 운영 share_class_snapshots의 알파벳 최신 공시 모양
    {"accession_no": "A1", "as_of_date": "2026-07-15", "share_class_key": "commonclassa", "shares_outstanding": 5_868_000_000},
    {"accession_no": "A1", "as_of_date": "2026-07-15", "share_class_key": "capitalclassc", "shares_outstanding": 5_527_000_000},
    {"accession_no": "A1", "as_of_date": "2026-07-15", "share_class_key": "commonclassb", "shares_outstanding": 835_000_000},
]


class CompanySharesTest(unittest.TestCase):
    def test_all_classes_of_a_filing_are_summed_including_unlisted(self) -> None:
        total = company_shares_by_filing(_GOOGL)[("A1", "2026-07-15")]
        self.assertEqual(total, 12_230_000_000)

    def test_a_duplicated_class_row_is_counted_once(self) -> None:
        rows = _GOOGL + [dict(_GOOGL[0])]
        self.assertEqual(company_shares_by_filing(rows)[("A1", "2026-07-15")], 12_230_000_000)

    def test_different_filings_are_not_mixed(self) -> None:
        rows = _GOOGL + [{"accession_no": "A0", "as_of_date": "2026-04-15", "share_class_key": "commonclassa",
                          "shares_outstanding": 5_900_000_000}]
        totals = company_shares_by_filing(rows)
        self.assertEqual(totals[("A0", "2026-04-15")], 5_900_000_000)

    def test_valuation_uses_the_company_total_not_the_mapped_class(self) -> None:
        row = {"accession_no": "A1", "as_of_date": "2026-07-15", "filed_at": "2026-07-20",
               "share_class_key": "commonclassa", "shares_outstanding": 5_868_000_000,
               "company_shares_outstanding": 12_230_000_000}
        scalar = shares_scalar([row], as_of_at=_AS_OF)
        self.assertEqual(scalar.value, Decimal(12_230_000_000))

    def test_single_class_rows_without_a_total_keep_working(self) -> None:
        row = {"accession_no": "A1", "as_of_date": "2026-07-15", "filed_at": "2026-07-20",
               "share_class_key": "commonclassa", "shares_outstanding": 1_000}
        self.assertEqual(shares_scalar([row], as_of_at=_AS_OF).value, Decimal(1000))


if __name__ == "__main__":
    unittest.main()
