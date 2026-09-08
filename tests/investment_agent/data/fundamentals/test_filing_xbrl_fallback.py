"""CompanyFacts 최신 반영 지연 시 filing XBRL 변환 회귀 테스트."""
from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

from investment_agent.data.fundamentals.domain.filings import FilingRef
from lxml import etree

from investment_agent.data.fundamentals.domain.services import parse_xbrl
from investment_agent.data.fundamentals.domain.services.parse_xbrl import (
    parse_consolidated_numeric_facts,
)
from investment_agent.data.fundamentals.infrastructure.sec import companyfacts
from investment_agent.data.fundamentals.infrastructure.sec import filing_xbrl
from investment_agent.data.fundamentals.infrastructure.sec.filing_xbrl import xbrl_rows_to_facts


class FilingXbrlFallbackTest(unittest.TestCase):
    def test_direct_parser_excludes_segment_and_normalizes_inline_scale(self) -> None:
        document = b"""\
        <html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
              xmlns:xbrli="http://www.xbrl.org/2003/instance"
              xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
              xmlns:us-gaap="http://fasb.org/us-gaap/2026"
              xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
          <body>
            <xbrli:context id="consolidated">
              <xbrli:entity><xbrli:identifier scheme="cik">1</xbrli:identifier></xbrli:entity>
              <xbrli:period><xbrli:instant>2026-06-30</xbrli:instant></xbrli:period>
            </xbrli:context>
            <xbrli:context id="scenario-segment">
              <xbrli:entity><xbrli:identifier scheme="cik">1</xbrli:identifier></xbrli:entity>
              <xbrli:scenario>
                <xbrldi:explicitMember dimension="us-gaap:ProductOrServiceAxis">us-gaap:CloudMember</xbrldi:explicitMember>
              </xbrli:scenario>
              <xbrli:period><xbrli:instant>2026-06-30</xbrli:instant></xbrli:period>
            </xbrli:context>
            <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
            <ix:nonFraction name="us-gaap:Assets" contextRef="consolidated" unitRef="usd" decimals="-6" scale="6">2,895</ix:nonFraction>
            <ix:nonFraction name="us-gaap:Assets" contextRef="scenario-segment" unitRef="usd" decimals="-6">645000000</ix:nonFraction>
          </body>
        </html>
        """

        rows, units = parse_consolidated_numeric_facts(document)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["numeric_value"], 2_895_000_000)
        self.assertFalse(rows[0]["is_dimensioned"])
        self.assertTrue(rows[1]["is_dimensioned"])
        self.assertEqual(units["usd"]["measure"], "iso4217:USD")

    def test_filing_download_uses_repo_native_parser(self) -> None:
        filing = FilingRef(
            accession_no="0000831001-26-000045",
            filing_date="2026-08-06",
            report_date="2026-06-30",
            form_type="10-Q",
            cik=831001,
        )
        document = b"""\
        <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
                    xmlns:us-gaap="http://fasb.org/us-gaap/2026"
                    xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
          <xbrli:context id="c"><xbrli:entity/><xbrli:period><xbrli:instant>2026-06-30</xbrli:instant></xbrli:period></xbrli:context>
          <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
          <us-gaap:Assets contextRef="c" unitRef="usd" decimals="-6">2894654000000</us-gaap:Assets>
        </xbrli:xbrl>
        """
        with mock.patch(
            "investment_agent.data.fundamentals.infrastructure.sec.filing_documents.fetch_xbrl_document",
            return_value=document,
        ) as fetch:
            facts = filing_xbrl.filing_to_facts(
                831001,
                filing,
                fiscal_year=2026,
                fiscal_period="Q2",
                floor=date(2016, 8, 29),
            )

        fetch.assert_called_once_with(831001, filing.accession_no)
        self.assertEqual(facts[0]["column_key"], "assets")
        self.assertEqual(facts[0]["value"], 2_894_654_000_000)

    def test_selects_consolidated_precise_facts_and_normalizes_units(self) -> None:
        filing = FilingRef(
            accession_no="0000831001-26-000045",
            filing_date="2026-08-06",
            report_date="2026-06-30",
            form_type="10-Q",
            cik=831001,
        )
        common = {
            "period_type": "instant",
            "period_instant": "2026-06-30",
            "unit_ref": "usd",
            "statement_type": "BalanceSheet",
            "is_dimensioned": False,
        }
        rows = [
            {
                **common,
                "concept": "us-gaap:Assets",
                "numeric_value": 2_895_000_000_000,
                "decimals": -9,
                "fact_key": "rounded",
            },
            {
                **common,
                "concept": "us-gaap:Assets",
                "numeric_value": 2_894_654_000_000,
                "decimals": -6,
                "fact_key": "precise",
            },
            {
                **common,
                "concept": "us-gaap:Assets",
                "numeric_value": 645_000_000_000,
                "decimals": -6,
                "fact_key": "segment",
                "is_dimensioned": True,
            },
            {
                **common,
                "concept": "us-gaap:Liabilities",
                "numeric_value": 2_680_204_000_000,
                "decimals": -6,
                "fact_key": "liabilities",
            },
            {
                "concept": "us-gaap:NetIncomeLoss",
                "numeric_value": 4_010_000_000,
                "unit_ref": "usd",
                "period_type": "duration",
                "period_start": "2026-04-01",
                "period_end": "2026-06-30",
                "statement_type": "IncomeStatement",
                "is_dimensioned": False,
                "decimals": -6,
                "fact_key": "net-income",
            },
            {
                "concept": "us-gaap:EarningsPerShareDiluted",
                "numeric_value": 2.30,
                "unit_ref": "usd_per_share",
                "period_type": "duration",
                "period_start": "2026-04-01",
                "period_end": "2026-06-30",
                "statement_type": "IncomeStatement",
                "is_dimensioned": False,
                "decimals": 2,
                "fact_key": "eps",
            },
        ]
        units = {
            "usd": {"type": "simple", "measure": "iso4217:USD"},
            "usd_per_share": {
                "type": "divide",
                "numerator": ["iso4217:USD"],
                "denominator": ["xbrli:shares"],
            },
        }

        facts = xbrl_rows_to_facts(
            rows,
            units,
            cik=831001,
            filing=filing,
            fiscal_year=2026,
            fiscal_period="Q2",
            floor=date(2016, 8, 29),
        )
        by_column = {row["column_key"]: row for row in facts}

        self.assertEqual(by_column["assets"]["value"], 2_894_654_000_000)
        self.assertEqual(by_column["assets"]["unit"], "USD")
        self.assertEqual(by_column["net_income"]["qtrs"], 1)
        self.assertEqual(by_column["eps_diluted_gaap"]["unit"], "USD/shares")

    def test_historical_empty_does_not_trigger_direct_filing_download(self) -> None:
        historical = FilingRef(
            "0001932393-23-000025",
            "2023-02-15",
            "2022-12-31",
            "10-K",
            cik=1932393,
        )
        latest = FilingRef(
            "0001932393-26-000060",
            "2026-07-29",
            "2026-06-30",
            "10-Q",
            cik=1932393,
        )
        focus = {
            historical.accession_no: (2022, "FY"),
            latest.accession_no: (2026, "Q2"),
        }

        with (
            mock.patch.object(companyfacts, "filing_focus", return_value=focus),
            mock.patch.object(filing_xbrl, "filing_to_facts") as direct,
        ):
            facts = companyfacts.companyfacts_to_facts(
                {"cik": 1932393, "facts": {"us-gaap": {}}},
                filings=[historical, latest],
                target_accessions={historical.accession_no},
                floor=date(2016, 8, 29),
                allow_filing_fallback=True,
            )

        self.assertEqual(facts, [])
        direct.assert_not_called()

    def test_latest_companyfacts_gap_uses_direct_filing(self) -> None:
        latest = FilingRef(
            "0000831001-26-000045",
            "2026-08-06",
            "2026-06-30",
            "10-Q",
            cik=831001,
        )
        expected = [
            {
                "accession_no": latest.accession_no,
                "cik": "0000831001",
                "qtrs": 0,
                "column_key": "assets",
            },
            {
                "accession_no": latest.accession_no,
                "cik": "0000831001",
                "qtrs": 1,
                "column_key": "net_income",
            },
        ]
        with (
            mock.patch.object(
                companyfacts,
                "filing_focus",
                return_value={latest.accession_no: (2026, "Q2")},
            ),
            mock.patch.object(
                filing_xbrl,
                "filing_to_facts",
                return_value=expected,
            ) as direct,
        ):
            facts = companyfacts.companyfacts_to_facts(
                {"cik": 831001, "facts": {"us-gaap": {}}},
                filings=[latest],
                target_accessions={latest.accession_no},
                floor=date(2016, 8, 29),
                allow_filing_fallback=True,
            )

        self.assertEqual(facts, expected)
        direct.assert_called_once()

    def test_partial_latest_filing_replaces_companyfacts_and_loads_support(self) -> None:
        q3 = FilingRef(
            "0000721371-26-000018",
            "2026-04-30",
            "2026-03-31",
            "10-Q",
            cik=721371,
        )
        annual = FilingRef(
            "0000721371-26-000038",
            "2026-08-11",
            "2026-06-30",
            "10-K",
            cik=721371,
        )
        document = {
            "cik": 721371,
            "facts": {
                "us-gaap": {
                    "Assets": {
                        "units": {
                            "USD": [
                                {
                                    "accn": annual.accession_no,
                                    "form": "10-K",
                                    "end": "2026-06-30",
                                    "filed": "2026-08-11",
                                    "val": 100,
                                }
                            ]
                        }
                    }
                }
            },
        }

        def direct_facts(
            _cik: int,
            filing: FilingRef,
            **_kwargs: object,
        ) -> list[dict]:
            return [
                {
                    "accession_no": filing.accession_no,
                    "cik": "0000721371",
                    "qtrs": 0,
                    "column_key": "assets",
                    "source": "direct",
                },
                {
                    "accession_no": filing.accession_no,
                    "cik": "0000721371",
                    "qtrs": 1,
                    "column_key": "revenue",
                    "source": "direct",
                },
            ]

        with (
            mock.patch.object(
                companyfacts,
                "filing_focus",
                return_value={
                    q3.accession_no: (2026, "Q3"),
                    annual.accession_no: (2026, "FY"),
                },
            ),
            mock.patch.object(
                filing_xbrl,
                "filing_to_facts",
                side_effect=direct_facts,
            ) as direct,
        ):
            facts = companyfacts.companyfacts_to_facts(
                document,
                filings=[q3, annual],
                target_accessions={annual.accession_no},
                floor=date(2016, 8, 29),
                allow_filing_fallback=True,
            )

        self.assertEqual(direct.call_count, 2)
        self.assertEqual(
            {row["accession_no"] for row in facts},
            {q3.accession_no, annual.accession_no},
        )
        self.assertTrue(all(row.get("source") == "direct" for row in facts))


class XbrlParserContractTests(unittest.TestCase):
    def test_invalid_scale_fails_instead_of_changing_units_silently(self) -> None:
        fact = etree.fromstring(b'<Revenue scale="thousands">10</Revenue>')

        with self.assertRaisesRegex(ValueError, "invalid XBRL scale"):
            parse_xbrl._fact_value(fact)

    def test_nonfinite_numeric_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-finite XBRL numeric"):
            parse_xbrl._clean_number("1e9999")

    def test_invalid_fiscal_year_focus_fails(self) -> None:
        document = b"<root><DocumentFiscalYearFocus>FY26</DocumentFiscalYearFocus></root>"

        with self.assertRaisesRegex(ValueError, "invalid DocumentFiscalYearFocus"):
            parse_xbrl.parse_fiscal_focus(document)


if __name__ == "__main__":
    unittest.main()

