"""외부 I/O를 fake port로 대체한 application 유스케이스 테스트."""
from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from investment_agent.data.fundamentals.domain.filings import FilingRef
from investment_agent.data.fundamentals.domain.normalization import (
    CompanyFinancialBatch,
)
from investment_agent.data.fundamentals.application.detect_earnings_events import (
    detect_earnings_events_for_ticker,
)
from investment_agent.data.fundamentals.application import PressReleaseDocument
from investment_agent.data.fundamentals.application.process_filing import (
    process_company_facts,
)
from investment_agent.data.fundamentals.application.refresh_earnings_season import (
    evaluate_earnings_season,
)
from investment_agent.data.fundamentals.application.sync_recent_filings import (
    sync_company_filings,
)


class _CompanyRepository:
    def __init__(self) -> None:
        self.core: list[dict] = []
        self.filings: list[dict] = []
        self.reported_anomalies: list[dict] = []

    def upsert_filings(self, rows: list[dict]) -> int:
        self.filings.extend(rows)
        return len(rows)

    def upsert_core_wide(self, rows: list[dict]) -> int:
        self.core.extend(rows)
        return len(rows)

    def report_anomalies(self, rows: list[dict]) -> int:
        self.reported_anomalies.extend(rows)
        return len(rows)

class _EarningsRepository:
    def __init__(self) -> None:
        self.saved: list[dict] = []

    def load_fiscal_calendar(self, ticker: str) -> list[dict]:
        return [
            {
                "fiscal_year": 2026,
                "fiscal_period": "Q2",
                "period_end": "2026-06-30",
            }
        ]

    def load_consensus_estimates(
        self,
        ticker: str,
        fiscal_year: int,
        fiscal_period: str,
    ) -> dict:
        return {"eps_estimate": 1.1, "revenue_estimate": 2_400_000_000.0}

    def upsert_earnings_results(self, rows: list[dict]) -> int:
        self.saved.extend(rows)
        return len(rows)


class ApplicationUseCaseTest(unittest.TestCase):
    def test_process_company_facts_builds_then_persists(self) -> None:
        repository = _CompanyRepository()
        batch = CompanyFinancialBatch(
            core_rows=[{"cik": "0000320193"}],
            quarantine_rows=[{"reason": "balance"}],
        )
        with patch(
            "investment_agent.data.fundamentals.application.process_filing."
            "build_company_financials",
            return_value=batch,
        ):
            result = process_company_facts([{"raw": True}], repository=repository)

        self.assertEqual(result["rows"], 1)
        self.assertEqual(result["quarantined"], 1)
        self.assertEqual(result["rows_by_accession"], {})

    def test_process_company_facts_applies_parent_cik_to_filing_refs(self) -> None:
        repository = _CompanyRepository()
        filing = FilingRef(
            "0000320193-26-000001",
            "2026-08-20",
            "2026-06-30",
            "10-Q",
        )
        batch = CompanyFinancialBatch(core_rows=[], quarantine_rows=[])

        with patch(
            "investment_agent.data.fundamentals.application.process_filing."
            "build_company_financials",
            return_value=batch,
        ):
            process_company_facts(
                [],
                cik="320193",
                filings=[filing],
                repository=repository,
            )

        self.assertEqual("0000320193", repository.filings[0]["cik"])

    def test_detect_earnings_event_composes_all_ports(self) -> None:
        filing = SimpleNamespace(
            filing_date="2026-08-20",
            report_date="2026-06-30",
            accession_no="0001-26-000001",
            primary_document="release.htm",
        )
        filing_source = SimpleNamespace(
            earnings_8k_filings=lambda cik, cutoff: [filing]
        )
        press_source = SimpleNamespace(
            press_release_document=lambda cik, accession_no, primary: PressReleaseDocument(
                "<p>Total revenue was $2.5 billion.</p>",
                "https://example.test/release",
            )
        )
        repository = _EarningsRepository()

        result = detect_earnings_events_for_ticker(
            "AAPL",
            "0000320193",
            filing_source=filing_source,
            press_release_source=press_source,
            repository=repository,
            today=date(2026, 8, 24),
        )

        self.assertEqual(result["rows"], 1)
        self.assertEqual(repository.saved[0]["fiscal_period"], "Q2")
        self.assertEqual(repository.saved[0]["cik"], "0000320193")
        self.assertEqual(repository.saved[0]["revenue_actual"], 2_500_000_000.0)


    def test_earnings_season_is_fail_open_without_snapshot(self) -> None:
        state = evaluate_earnings_season([], date(2026, 8, 24))
        self.assertTrue(state["in_season"])
        self.assertEqual(state["reason"], "no_snapshot")

    def test_company_sync_preserves_financial_rows_but_reports_earnings_failure(self) -> None:
        filing = FilingRef(
            "0001-26-000001",
            "2026-08-20",
            "2026-06-30",
            "10-Q",
            cik=1,
        )
        source = SimpleNamespace(
            recent_financial_ciks=lambda **kwargs: ({1}, 1),
            submissions=lambda cik: {},
            financial_filings=lambda document: [filing],
            pending_filings=lambda filings, *args: filings,
            companyfacts=lambda cik: {},
            companyfacts_to_facts=lambda document, **kwargs: [
                {"accession_no": filing.accession_no}
            ],
        )

        class Repository:
            def __init__(self) -> None:
                self.processed: list = []

            def tracked_ciks(self):
                return {"0000000001"}

            def tickers_by_cik(self):
                return {"0000000001": ["TEST"]}

            def gating_universe(self):
                return [{"ticker": "TEST", "cik": "0000000001"}]

            def ciks_for_tickers(self, tickers):
                return {"0000000001"}

            def last_filed_map(self):
                return {}

            def processed_filing_accessions(self):
                return {}

            def mark_empty_filing_targets(self, *args, **kwargs):
                return 0

            def mark_processed_filing_targets(self, targets, **kwargs):
                self.processed.extend(targets)
                return len(targets)

        repository = Repository()
        with patch(
            "investment_agent.data.fundamentals.application.sync_recent_filings."
            "process_company_facts",
            return_value={
                "rows": 1,
                "core_rows": 1,
                "sector_rows": 0,
                "quarantined": 0,
                "rows_by_accession": {"0001-26-000001": 1},
            },
        ):
            result = sync_company_filings(
                source=source,
                repository=repository,
                earnings_event_detector=lambda ticker, cik: (_ for _ in ()).throw(
                    RuntimeError("provider unavailable")
                ),
            )

        self.assertEqual(result["rows"], 1)
        self.assertEqual(result["filings"], 1)
        self.assertEqual(len(result["failures"]), 1)
        self.assertEqual(result["failures"][0]["stage"], "earnings_event")


if __name__ == "__main__":
    unittest.main()
