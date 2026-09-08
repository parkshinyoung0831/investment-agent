"""Fundamentals 일간 워터마크가 같은 날의 추가 공시를 놓치지 않는지 검증한다."""
from __future__ import annotations

import unittest

from investment_agent.data.fundamentals.infrastructure.sec.companyfacts import Filing, pending_filings


def _filing(accession_no: str, filing_date: str) -> Filing:
    return Filing(
        accession_no=accession_no,
        filing_date=filing_date,
        report_date="2026-06-30",
        form_type="10-Q",
        is_xbrl=True,
    )


class PendingFilingsTest(unittest.TestCase):
    def test_unprocessed_same_day_amendment_is_pending(self):
        filings = [
            _filing("BASE", "2026-08-03"),
            _filing("AMEND", "2026-08-03"),
        ]

        result = pending_filings(
            filings,
            "2026-08-03",
            processed_accessions={"BASE"},
        )

        self.assertEqual([row.accession_no for row in result], ["AMEND"])

    def test_processed_same_day_filing_is_not_repeated(self):
        result = pending_filings(
            [_filing("BASE", "2026-08-03")],
            "2026-08-03",
            processed_accessions={"BASE"},
        )

        self.assertEqual(result, [])

    def test_new_ticker_only_seeds_latest_filing_date(self):
        filings = [
            _filing("OLD", "2026-05-01"),
            _filing("NEW1", "2026-08-03"),
            _filing("NEW2", "2026-08-03"),
        ]

        result = pending_filings(filings, None)

        self.assertEqual(
            [row.accession_no for row in result],
            ["NEW1", "NEW2"],
        )

    def test_older_uncompleted_filing_is_retried_without_a_failed_state(self):
        filings = [
            _filing("FAILED", "2026-08-01"),
            _filing("DONE", "2026-08-03"),
        ]

        result = pending_filings(
            filings,
            "2026-08-03",
            processed_accessions={"DONE"},
        )

        self.assertEqual([row.accession_no for row in result], ["FAILED"])


if __name__ == "__main__":
    unittest.main()
