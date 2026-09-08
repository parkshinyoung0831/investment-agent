"""13F filing 순회가 개별 파싱 실패 뒤에도 계속되는지 검증한다."""
from __future__ import annotations

import unittest
from unittest import mock
from types import SimpleNamespace

from investment_agent.data.universe.infrastructure.sources.sec import SecFiling
from investment_agent.data.institutional.infrastructure.sources import sec13f as edgar
from tests.investment_agent.data.institutional._factories import make_filing_record


class FilingIterationTest(unittest.TestCase):
    def test_parse_failure_does_not_block_later_filing(self):
        first = SecFiling(
            accession_no="BAD",
            form_type="13F-HR",
            report_date="2024-03-31",
            filing_date="2024-05-14",
            accepted_at=None,
            primary_document="bad.xml",
        )
        second = SecFiling(
            accession_no="GOOD",
            form_type="13F-HR",
            report_date="2024-03-31",
            filing_date="2024-05-15",
            accepted_at=None,
            primary_document="good.xml",
        )
        record = make_filing_record(accession_no="GOOD", positions=())
        errors: list[tuple[str, str]] = []

        with mock.patch.object(
                edgar,
                "_parse_filing",
                side_effect=[ValueError("broken XML"), record],
            ):
            rows = list(
                edgar.iter_filings(
                    record.manager_cik,
                    "2024-01-01",
                    sec_client=SimpleNamespace(
                        filings_filed_since=lambda *_args, **_kwargs: [first, second]
                    ),
                    error_sink=lambda filing, exc: errors.append(
                        (filing.accession_no, str(exc))
                    ),
                )
            )

        self.assertEqual([row.accession_no for row in rows], ["GOOD"])
        self.assertEqual(errors, [("BAD", "broken XML")])


if __name__ == "__main__":
    unittest.main()
