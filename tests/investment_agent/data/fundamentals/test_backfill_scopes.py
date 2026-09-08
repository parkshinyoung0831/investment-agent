"""기업 전체·세그먼트 재무가 같은 백필 범위 의미를 사용하는지 검증한다."""
from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from investment_agent.operations.backfill import resolve_backfill_window, select_accessions
from investment_agent.data.fundamentals.domain.filings import FilingRef
from investment_agent.data.fundamentals.application import backfill_history


class _CompanySource:
    """기업 전체 재무 백필이 쓰는 companyfacts 원천의 최소 대역."""

    def __init__(
        self,
        filings: list[FilingRef] | None = None,
        facts: list[dict] | None = None,
        focus: dict[str, tuple[int, str]] | None = None,
    ) -> None:
        self._filings = list(filings or [])
        self._facts = list(facts or [])
        self._focus = dict(focus or {})
        self.requested_ciks: list[int] = []

    def all_financial_filings(
        self, cik: str | int, *, cutoff: date
    ) -> list[FilingRef]:
        self.requested_ciks.append(int(cik))
        return [
            filing
            for filing in self._filings
            if int(filing.cik or 0) == int(cik)
        ]

    def companyfacts(self, cik: str | int) -> dict:
        return {"cik": int(cik)}

    def filing_focus(
        self,
        document: dict,
        filings: list[FilingRef],
    ) -> dict[str, tuple[int, str]]:
        return {
            filing.accession_no: self._focus[filing.accession_no]
            for filing in filings
            if filing.accession_no in self._focus
        }

    def superseded_filing_accessions(
        self,
        document: dict,
        filings: list[FilingRef],
    ) -> set[str]:
        return set()

    def companyfacts_to_facts(self, document: dict, **kwargs: object) -> list[dict]:
        return list(self._facts)


class _CompanyRepository:
    def __init__(
        self,
        *,
        processed: dict[str, set[str]] | None = None,
    ) -> None:
        self._processed = processed or {}
        self.mark_empty_filing_targets = mock.Mock(return_value=1)
        self.mark_superseded_filing_targets = mock.Mock(return_value=1)
        self.mark_processed_filing_targets = mock.Mock(return_value=1)
        self.reconcile_wide_history = mock.Mock(return_value=3)

    def gating_universe(self) -> list[dict]:
        return [{"ticker": "TEST", "cik": 1}]

    def tracked_ciks(self) -> set[str]:
        return {str(row["cik"]).zfill(10) for row in self.gating_universe()}

    def ciks_for_tickers(self, tickers: set[str]) -> set[str]:
        wanted = {str(ticker).upper() for ticker in tickers}
        found = {
            str(row["ticker"]): str(row["cik"]).zfill(10)
            for row in self.gating_universe()
        }
        unknown = wanted - set(found)
        if unknown:
            raise ValueError("requested tickers are not in the tracked CIK universe")
        return {found[ticker] for ticker in wanted}

    def ciks_missing_financials(self) -> list[str]:
        return ["0000000001"]

    def processed_filing_accessions(self) -> dict[str, set[str]]:
        return self._processed

class BackfillScopeTest(unittest.TestCase):
    def test_company_default_window_is_ten_years(self) -> None:
        window = resolve_backfill_window(
            None,
            default_years=backfill_history._COMPANY_BACKFILL_YEARS,
            today=date(2026, 8, 18),
        )

        self.assertEqual(backfill_history._COMPANY_BACKFILL_YEARS, 10)
        self.assertEqual(window.start, date(2016, 8, 20))

    def test_scope_selection_has_one_shared_meaning(self) -> None:
        discovered = {"A", "B", "C"}
        completed = {"A"}
        self.assertEqual(
            select_accessions(discovered, scope="gaps", completed=completed),
            {"B", "C"},
        )
        self.assertEqual(
            select_accessions(discovered, scope="all"),
            discovered,
        )

    def test_missing_company_selects_its_unprocessed_accession(self) -> None:
        filing = FilingRef(
            accession_no="ACC",
            filing_date="2026-08-01",
            report_date="2026-06-30",
            form_type="10-Q",
            cik=1,
        )

        result = backfill_history._company_backfill_targets(
            [filing],
            cik="0000000001",
            scope="missing",
            processed={},
        )

        self.assertIs(result["ACC"], filing)

    def test_gaps_scope_uses_all_uncompleted_accessions(self) -> None:
        filings = [
            FilingRef("FAILED", "2026-08-01", "2026-06-30", "10-Q", cik=1),
            FilingRef("OTHER", "2026-08-02", "2026-06-30", "10-Q", cik=1),
        ]

        result = backfill_history._company_backfill_targets(
            filings,
            cik="0000000001",
            scope="gaps",
            processed={"0000000001": {"OTHER"}},
        )

        self.assertEqual(set(result), {"FAILED"})

    def _run_company_backfill(
        self,
        filings: list[FilingRef],
        *,
        scope: str,
        processed: dict[str, set[str]] | None = None,
    ) -> tuple[dict, _CompanyRepository]:
        source = _CompanySource(filings)
        repository = _CompanyRepository(processed=processed)
        result = backfill_history.backfill_company_history(
            source=source,
            repository=repository,
            backfill_from="2018-01-01",
            scope=scope,
        )
        self.assertEqual(source.requested_ciks, [1])
        return result, repository

    def test_scope_all_marks_no_fact_filing_empty_and_reconciles_history(self) -> None:
        filing = FilingRef(
            "EMPTY", "2026-08-01", "2026-06-30", "10-Q", cik=1
        )

        result, repository = self._run_company_backfill([filing], scope="all")

        self.assertEqual(result["filings_empty"], 1)
        self.assertEqual(result["rows_removed"], 3)
        self.assertEqual(result["failures"], [])
        repository.mark_empty_filing_targets.assert_called_once_with(
            [(filing, "0000000001")],
            source="backfill_companyfacts",
        )
        repository.reconcile_wide_history.assert_called_once_with(
            {"0000000001": "2026-06-30"},
            date(2018, 1, 1),
        )

    def test_explicit_ticker_scope_never_scans_other_ciks(self) -> None:
        filing = FilingRef(
            "ONLY", "2026-08-01", "2026-06-30", "10-Q", cik=1
        )
        source = _CompanySource([filing])
        repository = _CompanyRepository()
        repository.gating_universe = lambda: [
            {"ticker": "TEST", "cik": 1},
            {"ticker": "OTHER", "cik": 2},
        ]

        result = backfill_history.backfill_company_history(
            source=source,
            repository=repository,
            backfill_from="2018-01-01",
            scope="all",
            target_tickers={"test"},
        )

        self.assertEqual(source.requested_ciks, [1])
        self.assertEqual(result["companies"], 1)

    def test_unknown_explicit_ticker_fails_before_sec_requests(self) -> None:
        source = _CompanySource()
        repository = _CompanyRepository()

        with self.assertRaisesRegex(ValueError, "not in the tracked CIK universe"):
            backfill_history.backfill_company_history(
                source=source,
                repository=repository,
                scope="all",
                target_tickers={"TYPO"},
            )

        self.assertEqual(source.requested_ciks, [])

    def test_partial_scope_does_not_remove_unselected_history(self) -> None:
        selected = FilingRef(
            "SELECTED", "2026-08-01", "2026-06-30", "10-Q", cik=1
        )
        completed = FilingRef(
            "COMPLETED", "2026-05-01", "2026-03-31", "10-Q", cik=1
        )

        _, repository = self._run_company_backfill(
            [selected, completed],
            scope="gaps",
            processed={"0000000001": {"COMPLETED"}},
        )

        repository.reconcile_wide_history.assert_not_called()

class BulkFilingContractTest(unittest.TestCase):
    """세그먼트 백필은 secfsdstools 파케이를 직접 읽는다. `sub` 컬럼 이름이
    어긋나면 공시를 전부 걸러 내고도 성공으로 끝나므로 실물 상수로 못 박는다."""

    def test_mock_column_name_matches_the_installed_library(self) -> None:
        """가짜 프레임이 실물과 어긋나면 이 테스트만 초록이고 운영은 0건이 된다.

        실제로 그랬다 — 목이 `form_type`을 쓰는 동안 secfsdstools는 `form`을 실어
        보내, 백필이 모든 공시를 걸러 내고도 성공으로 끝났다.
        """
        try:
            from secfsdstools.a_utils.constants import SUB_COLS
            from secfsdstools.c_index.indexdataaccess import IndexReport
        except ImportError:  # 최소 설치 환경에서는 건너뛴다
            self.skipTest("secfsdstools가 설치돼 있지 않다")
        import dataclasses

        self.assertIn("form", SUB_COLS)
        self.assertNotIn("form_type", SUB_COLS)
        self.assertIn("form", [f.name for f in dataclasses.fields(IndexReport)])


class FilingSchemaContractTest(unittest.TestCase):
    def test_company_and_segment_filings_keep_only_terminal_provenance(self) -> None:
        sql = Path("db/postgres/v1/30_fundamentals.sql").read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS fundamentals.filings", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS fundamentals.filing_processing", sql)
        for column in ("status", "mapping_version", "source", "content_type"):
            self.assertIn(column, sql)
        declaration = sql.split("CREATE TABLE IF NOT EXISTS fundamentals.filing_processing", 1)[1].split(");", 1)[0]
        self.assertNotIn("error_reason", declaration)
        self.assertIn("status IN ('parsed', 'empty', 'unsupported', 'superseded')", declaration)
        self.assertIn("PRIMARY KEY (accession_no, content_type, mapping_version)", sql)
        self.assertNotIn("DROP COLUMN IF EXISTS error_reason", sql)

    def test_security_filing_view_does_not_reintroduce_operational_error_columns(self) -> None:
        sql = Path("db/postgres/v1/30_fundamentals.sql").read_text(encoding="utf-8")
        self.assertNotIn("CREATE OR REPLACE VIEW fundamentals.", sql)
        self.assertNotIn("error_reason", sql)
        self.assertIn("available_at timestamptz NOT NULL DEFAULT now()", sql)
        self.assertIn("updated_at      timestamptz NOT NULL DEFAULT now()", sql)


if __name__ == "__main__":
    unittest.main()

