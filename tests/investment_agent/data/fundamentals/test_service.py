"""v1 CompanyFacts writer의 원천→원장→wide 경로."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import unittest

from investment_agent.data.fundamentals.domain.filings import FilingRef
from investment_agent.data.fundamentals.repository import SCHEMA, T_FILINGS, T_FINANCIALS, T_PROCESSING
from investment_agent.data.fundamentals.service import refresh_fundamentals
from tests.investment_agent.fakes import FakeDatabase

CIK = "0000320193"
ACCESSION = "0000320193-26-000001"


@dataclass(frozen=True)
class _Batch:
    core_rows: list[dict]


def _ref() -> FilingRef:
    return FilingRef(
        accession_no=ACCESSION,
        filing_date="2026-05-01",
        report_date="2026-03-31",
        form_type="10-Q",
        cik=int(CIK),
    )


def _prepared_db() -> FakeDatabase:
    db = FakeDatabase()
    db.put(SCHEMA, T_FILINGS, [{
        "accession_no": ACCESSION, "cik": CIK, "form_type": "10-Q",
        "filing_date": "2026-05-01", "report_date": "2026-03-31",
        "available_at": "2026-05-02T00:00:00+00:00", "source": "sec_edgar",
    }])
    return db


class FundamentalsWriterTest(unittest.TestCase):
    def test_parsed_companyfacts_writes_only_v1_wide_columns_and_processing_ledger(self) -> None:
        db = _prepared_db()
        result = refresh_fundamentals(
            db,
            ciks=[CIK],
            floor=date(2016, 1, 1),
            filing_source=lambda _cik, _floor: [_ref()],
            companyfacts_source=lambda _cik: {"cik": int(CIK)},
            facts_normalizer=lambda *_args, **_kwargs: [{"accession_no": ACCESSION}],
            wide_builder=lambda _facts: _Batch([{
                "cik": CIK, "period_end": "2026-03-31", "accession_no": ACCESSION,
                "fiscal_year": 2026, "fiscal_period": "Q1", "revenue": 100.0,
                "mapping_version": "obsolete", "source_manifest": {"revenue": {}},
                "filed_at": "2026-05-01",
            }]),
        )

        self.assertEqual(1, result.filings_parsed)
        self.assertEqual(1, result.financial_rows)
        self.assertEqual((), result.failures)
        financial = [call for call in db.upserts if call[0] == (SCHEMA, T_FINANCIALS)]
        self.assertEqual(1, len(financial))
        self.assertEqual("cik,period_end,fiscal_period", financial[0][2])
        self.assertNotIn("source_manifest", financial[0][1][0])
        self.assertNotIn("filed_at", financial[0][1][0])
        self.assertEqual("v1", financial[0][1][0]["mapping_version"])
        processing = [call for call in db.upserts if call[0] == (SCHEMA, T_PROCESSING)]
        self.assertEqual("parsed", processing[0][1][0]["status"])
        self.assertEqual(1, processing[0][1][0]["facts_count"])
        self.assertEqual(1, processing[0][1][0]["rows_count"])

    def test_factless_filing_is_explicitly_empty_not_fake_financial_zero(self) -> None:
        db = _prepared_db()
        result = refresh_fundamentals(
            db, ciks=[CIK], floor=date(2016, 1, 1),
            filing_source=lambda _cik, _floor: [_ref()],
            companyfacts_source=lambda _cik: {"cik": int(CIK)},
            facts_normalizer=lambda *_args, **_kwargs: [],
            wide_builder=lambda _facts: _Batch([]),
        )

        self.assertEqual(1, result.filings_empty)
        self.assertEqual(0, result.financial_rows)
        self.assertFalse([call for call in db.upserts if call[0] == (SCHEMA, T_FINANCIALS)])
        processing = [call for call in db.upserts if call[0] == (SCHEMA, T_PROCESSING)]
        self.assertEqual("empty", processing[0][1][0]["status"])

    def test_wrong_cik_from_the_source_is_a_retryable_failure(self) -> None:
        db = _prepared_db()
        wrong = FilingRef(
            accession_no=ACCESSION, filing_date="2026-05-01", report_date="2026-03-31",
            form_type="10-Q", cik=1234,
        )
        result = refresh_fundamentals(
            db, ciks=[CIK], floor=date(2016, 1, 1),
            filing_source=lambda _cik, _floor: [wrong],
            companyfacts_source=lambda _cik: {"cik": int(CIK)},
            facts_normalizer=lambda *_args, **_kwargs: [], wide_builder=lambda _facts: _Batch([]),
        )

        self.assertEqual(1, len(result.failures))
        self.assertFalse([call for call in db.upserts if call[0] == (SCHEMA, T_PROCESSING)])


if __name__ == "__main__":
    unittest.main()
