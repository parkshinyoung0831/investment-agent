"""SEC CompanyFacts의 오염된 fy/fp를 filing 기간으로 교정하는 계약."""
from __future__ import annotations

import unittest
from datetime import date

from investment_agent.data.fundamentals.domain.filings import FilingRef
from investment_agent.data.fundamentals.infrastructure.sec.companyfacts import (
    _canonical_filing_focus,
    companyfacts_to_facts,
    filing_focus,
    superseded_filing_accessions,
)


def _filing(accession: str, report_date: str, form_type: str) -> FilingRef:
    return FilingRef(
        accession_no=accession,
        filing_date=report_date,
        report_date=report_date,
        form_type=form_type,
    )


class CanonicalFilingFocusTest(unittest.TestCase):
    def test_public_focus_contract_uses_companyfacts_source_anchors(self) -> None:
        filings = [_filing("K", "2025-12-31", "10-K")]
        document = {
            "facts": {
                "us-gaap": {
                    "Assets": {
                        "units": {
                            "USD": [{"accn": "K", "fy": 2025, "fp": "FY"}]
                        }
                    }
                }
            }
        }

        self.assertEqual(filing_focus(document, filings), {"K": (2025, "FY")})

    def test_corroborated_fiscal_calendar_reset_supersedes_the_old_q1(self) -> None:
        filings = [
            _filing("K25", "2025-07-31", "10-K"),
            _filing("OLD-Q1", "2025-10-31", "10-Q"),
            _filing("NEW-Q1", "2026-03-31", "10-Q"),
            _filing("NEW-Q2", "2026-06-30", "10-Q"),
        ]
        entries = [
            {"accn": "K25", "fy": 2025, "fp": "FY"},
            {"accn": "OLD-Q1", "fy": 2026, "fp": "Q1"},
            {"accn": "NEW-Q1", "fy": 2026, "fp": "Q1"},
            {"accn": "NEW-Q2", "fy": 2026, "fp": "Q2"},
        ]
        document = {
            "facts": {
                "us-gaap": {
                    "Assets": {"units": {"USD": entries}},
                }
            }
        }

        focus = filing_focus(document, filings)

        self.assertNotIn("OLD-Q1", focus)
        self.assertEqual(focus["NEW-Q1"], (2026, "Q1"))
        self.assertEqual(focus["NEW-Q2"], (2026, "Q2"))
        self.assertEqual(
            superseded_filing_accessions(document, filings),
            {"OLD-Q1"},
        )

    def test_factless_amendment_does_not_replace_the_original_10k(self) -> None:
        filings = [
            _filing("ORIGINAL", "2025-12-31", "10-K"),
            FilingRef(
                accession_no="AMENDMENT",
                filing_date="2026-03-01",
                report_date="2025-12-31",
                form_type="10-K/A",
            ),
        ]
        document = {
            "facts": {
                "us-gaap": {
                    "Assets": {
                        "units": {
                            "USD": [
                                {"accn": "ORIGINAL", "fy": 2025, "fp": "FY"}
                            ]
                        }
                    }
                }
            }
        }

        self.assertEqual(
            filing_focus(document, filings),
            {"ORIGINAL": (2025, "FY")},
        )
        self.assertEqual(
            superseded_filing_accessions(document, filings),
            {"AMENDMENT"},
        )

    def test_current_quarters_use_the_previous_annual_anchor(self) -> None:
        filings = [
            _filing("K", "2025-12-31", "10-K"),
            _filing("Q1", "2026-03-31", "10-Q"),
            _filing("Q2", "2026-06-30", "10-Q"),
        ]

        self.assertEqual(
            _canonical_filing_focus(filings),
            {"K": (2025, "FY"), "Q1": (2026, "Q1"), "Q2": (2026, "Q2")},
        )

    def test_non_calendar_year_uses_the_following_annual_year(self) -> None:
        filings = [
            _filing("K25", "2025-09-27", "10-K"),
            _filing("Q1", "2025-12-27", "10-Q"),
            _filing("Q2", "2026-03-28", "10-Q"),
            _filing("K26", "2026-09-26", "10-K"),
        ]

        focus = _canonical_filing_focus(filings)

        self.assertEqual(focus["Q1"], (2026, "Q1"))
        self.assertEqual(focus["Q2"], (2026, "Q2"))

    def test_january_year_end_uses_the_10k_source_fiscal_year(self) -> None:
        filings = [
            _filing("K19", "2019-12-28", "10-K"),
            _filing("Q1", "2020-03-28", "10-Q"),
            _filing("K20", "2021-01-02", "10-K"),
        ]
        source_focus = {"K19": (2019, "FY"), "K20": (2020, "FY")}

        focus = _canonical_filing_focus(filings, source_focus)

        self.assertEqual(focus["K20"], (2020, "FY"))
        self.assertEqual(focus["Q1"], (2020, "Q1"))

    def test_annual_source_year_is_corrected_by_preceding_q3(self) -> None:
        filings = [
            _filing("Q3", "2021-09-30", "10-Q"),
            _filing("K", "2021-12-31", "10-K"),
        ]
        source_focus = {
            "Q3": (2021, "Q3"),
            # SEC occasionally reports the annual fy one year too early.
            "K": (2020, "FY"),
        }

        focus = _canonical_filing_focus(filings, source_focus)

        self.assertEqual(focus["Q3"], (2021, "Q3"))
        self.assertEqual(focus["K"], (2021, "FY"))

    def test_january_year_end_q3_preserves_the_prior_fiscal_year(self) -> None:
        filings = [
            _filing("Q3", "2020-09-26", "10-Q"),
            _filing("K", "2021-01-02", "10-K"),
        ]
        source_focus = {
            "Q3": (2020, "Q3"),
            "K": (2020, "FY"),
        }

        focus = _canonical_filing_focus(filings, source_focus)

        self.assertEqual(focus["Q3"], (2020, "Q3"))
        self.assertEqual(focus["K"], (2020, "FY"))

    def test_quarter_source_year_is_not_trusted_when_annual_anchors_agree(self) -> None:
        filings = [
            _filing("K18", "2018-12-31", "10-K"),
            _filing("Q1", "2019-03-31", "10-Q"),
            _filing("Q2", "2019-06-30", "10-Q"),
            _filing("Q3", "2019-09-30", "10-Q"),
            _filing("K19", "2019-12-31", "10-K"),
        ]
        source_focus = {
            "K18": (2018, "FY"),
            # SEC repeated the prior fy for Q1/Q2 and corrected it at Q3.
            "Q1": (2018, "Q1"),
            "Q2": (2018, "Q2"),
            "Q3": (2019, "Q3"),
            "K19": (2019, "FY"),
        }

        focus = _canonical_filing_focus(filings, source_focus)

        self.assertEqual(focus["Q1"], (2019, "Q1"))
        self.assertEqual(focus["Q2"], (2019, "Q2"))
        self.assertEqual(focus["Q3"], (2019, "Q3"))

    def test_first_quarter_after_non_calendar_year_end_advances_year(self) -> None:
        filings = [
            _filing("K25", "2025-04-25", "10-K"),
            _filing("Q1", "2025-07-25", "10-Q"),
            _filing("K26", "2026-04-24", "10-K"),
        ]
        source_focus = {
            "K25": (2025, "FY"),
            "Q1": (2025, "Q1"),
            "K26": (2026, "FY"),
        }

        self.assertEqual(
            _canonical_filing_focus(filings, source_focus)["Q1"],
            (2026, "Q1"),
        )

    def test_distant_missing_annual_anchor_does_not_shift_a_year(self) -> None:
        filings = [
            _filing("K16", "2016-12-31", "10-K"),
            _filing("Q1", "2017-03-31", "10-Q"),
            _filing("K18", "2018-12-31", "10-K"),
        ]

        self.assertEqual(_canonical_filing_focus(filings)["Q1"], (2017, "Q1"))

    def test_following_anchor_recovers_a_quarter_without_a_previous_10k(self) -> None:
        filings = [
            _filing("Q3", "2025-09-30", "10-Q"),
            _filing("K", "2025-12-31", "10-K"),
        ]

        self.assertEqual(_canonical_filing_focus(filings)["Q3"], (2025, "Q3"))

    def test_companyfacts_parser_ignores_corrupt_source_fiscal_labels(self) -> None:
        filings = [
            _filing("K", "2025-12-31", "10-K"),
            _filing("Q1", "2026-03-31", "10-Q"),
            _filing("Q2", "2026-06-30", "10-Q"),
        ]
        document = {
            "cik": 1,
            "facts": {
                "us-gaap": {
                    "Assets": {
                        "units": {
                            "USD": [
                                {
                                    "accn": "Q1",
                                    "form": "10-Q",
                                    "fy": 2024,
                                    "fp": "Q2",
                                    "end": "2026-03-31",
                                    "filed": "2026-03-31",
                                    "val": 100,
                                },
                                {
                                    "accn": "Q2",
                                    "form": "10-Q",
                                    "fy": 2024,
                                    "fp": "Q2",
                                    "end": "2026-06-30",
                                    "filed": "2026-06-30",
                                    "val": 110,
                                },
                            ]
                        }
                    }
                }
            },
        }

        rows = companyfacts_to_facts(
            document,
            filings=filings,
            target_accessions={"Q2"},
            floor=date(2025, 1, 1),
            allowed_keys={"assets"},
        )

        by_accession = {row["accession_no"]: row for row in rows}
        self.assertEqual(by_accession["Q1"]["fiscal_year"], 2026)
        self.assertEqual(by_accession["Q1"]["fiscal_period"], "Q1")
        self.assertEqual(by_accession["Q2"]["fiscal_year"], 2026)
        self.assertEqual(by_accession["Q2"]["fiscal_period"], "Q2")


if __name__ == "__main__":
    unittest.main()
