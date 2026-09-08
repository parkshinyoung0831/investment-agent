"""내재화한 SEC 8-K 파서의 표·EX-99·Item 계약을 네트워크 없이 검증한다."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from investment_agent.data.fundamentals.infrastructure.sec import press_releases
from investment_agent.data.fundamentals.infrastructure.sec.edgar_parser import (
    exhibit_extractor,
    item_classifier,
    parse_8k_earnings,
)
from investment_agent.data.fundamentals.infrastructure.sec.edgar_parser.table_parser import (
    extract_summary_financials,
    normalize_table,
    parse_amount,
)


class ItemClassifierTest(unittest.TestCase):
    def test_classifies_only_original_8k_item_202(self):
        self.assertEqual(item_classifier.extract_item_numbers("Item 2.02, Item 9.01"), ("2.02", "9.01"))
        self.assertTrue(item_classifier.is_earnings_item("8-K", "Item 2.02, 9.01"))
        self.assertFalse(item_classifier.is_earnings_item("8-K/A", "Item 2.02"))
        self.assertEqual(item_classifier.classify_8k_items("8-K", "5.02"), "executive_change")
        self.assertTrue(item_classifier.is_earnings_item("8-K", "", html="<h2>Item 2.02</h2>"))


class ExhibitExtractorTest(unittest.TestCase):
    def test_selects_ex99_press_release_over_primary_document(self):
        selected = exhibit_extractor.select_exhibit([
            {"name": "acme-20260827.htm", "description": "8-K"},
            {"name": "ex99-1.htm", "description": "EX-99.1 Press Release"},
            {"name": "logo.png", "description": "image"},
        ], "acme-20260827.htm")
        self.assertEqual(selected["name"], "ex99-1.htm")

    def test_removes_script_and_extracts_guidance_blocks(self):
        html = """
          <script>guidance should not leak</script>
          <h1>Results</h1>
          <p>The company raises full-year guidance for revenue.</p>
          <p>It expects operating margin to improve.</p>
        """
        self.assertNotIn("should not leak", exhibit_extractor.extract_text(html))
        guidance = exhibit_extractor.extract_guidance_text(html)
        self.assertIn("raises full-year guidance", guidance)
        self.assertIn("expects operating margin", guidance)

    def test_extracts_guidance_from_table_cells(self):
        guidance = exhibit_extractor.extract_guidance_text(
            "<table><tr><td>Full-year outlook: revenue is expected to grow.</td></tr></table>"
        )
        self.assertIn("expected to grow", guidance)


class TableParserTest(unittest.TestCase):
    HTML = """
      <div>Condensed Consolidated Statements (in millions)</div>
      <table>
        <tr><th colspan="3">Three Months Ended</th></tr>
        <tr><th>Revenue</th><td>$ 47,861</td><td>$ 45,277</td></tr>
        <tr><th>Operating Income</th><td>12,300</td><td>11,500</td></tr>
        <tr><th>Net Income</th><td>(1,200)</td><td>1,000</td></tr>
      </table>
    """

    def test_expands_colspan_and_converts_millions(self):
        matrix = normalize_table("<table><tr><th colspan='2'>Header</th></tr><tr><td>A</td><td>B</td></tr></table>")
        self.assertEqual(matrix[0], ["Header", "Header"])
        self.assertEqual(
            extract_summary_financials(self.HTML),
            {"revenue": 47_861_000_000.0, "operating_income": 12_300_000_000.0, "net_income": -1_200_000_000.0},
        )

    def test_parse_8k_contract_exposes_guidance_and_all_summary_values(self):
        parsed = parse_8k_earnings(self.HTML + "<p>We reaffirm our full-year outlook.</p>")
        self.assertEqual(parsed["revenue_actual"], 47_861_000_000.0)
        self.assertEqual(parsed["operating_income_actual"], 12_300_000_000.0)
        self.assertEqual(parsed["net_income_actual"], -1_200_000_000.0)
        self.assertIn("reaffirm", parsed["guidance_summary"])

    def test_parse_amount_does_not_negate_parenthetical_qualifier(self):
        self.assertEqual(parse_amount("(unaudited) $1,234"), 1234.0)

    def test_text_headline_is_used_when_release_has_no_table(self):
        parsed = extract_summary_financials(
            "The company reported revenue of $2.5 billion and net income was $300 million."
        )
        self.assertEqual(parsed["revenue"], 2_500_000_000.0)
        self.assertEqual(parsed["net_income"], 300_000_000.0)

    def test_guidance_caption_is_not_preferred_over_quarterly_actual(self):
        parsed = extract_summary_financials(
            """
            <table><caption>Fiscal 2027 guidance (in millions)</caption>
              <tr><th>Total revenue</th><td>23,500</td></tr>
            </table>
            <table><caption>Three Months Ended (in millions)</caption>
              <tr><th>Total revenue</th><td>4,354</td></tr>
            </table>
            """
        )
        self.assertEqual(parsed["revenue"], 4_354_000_000.0)

    def test_reads_units_declared_inside_table_and_consolidated_net_income(self):
        parsed = extract_summary_financials(
            """
            <table>
              <tr><th colspan='3'>(Amounts in millions, except per share data)</th></tr>
              <tr><th>Three Months Ended</th><th>2026</th><th>2025</th></tr>
              <tr><td>Total revenues</td><td>187,937</td><td>177,402</td></tr>
              <tr><td>Operating income</td><td>9,383</td><td>7,286</td></tr>
              <tr><td>Consolidated net income</td><td>6,529</td><td>7,151</td></tr>
            </table>
            """
        )
        self.assertEqual(parsed["revenue"], 187_937_000_000.0)
        self.assertEqual(parsed["operating_income"], 9_383_000_000.0)
        self.assertEqual(parsed["net_income"], 6_529_000_000.0)

    def test_accepts_operating_earnings_label(self):
        parsed = extract_summary_financials(
            """
            <table><caption>Second Quarter (in millions)</caption>
              <tr><th>Operating earnings</th><td>12,983</td></tr>
              <tr><th>Net earnings attributable to shareholders</th><td>25,667</td></tr>
            </table>
            """
        )
        self.assertEqual(parsed["operating_income"], 12_983_000_000.0)
        self.assertEqual(parsed["net_income"], 25_667_000_000.0)


class PressReleaseArchiveAdapterTest(unittest.TestCase):
    def test_fetches_selected_archive_document_without_edgar_sdk(self):
        with (
            patch.object(press_releases.sec, "filing_archive_items", return_value=[
                {"name": "8-k.htm", "description": "8-K"},
                {"name": "ex99-1.htm", "description": "EX-99.1 earnings release"},
            ]),
            patch.object(press_releases.sec, "filing_document_url", return_value="https://sec.test/ex99-1.htm"),
            patch.object(press_releases.sec, "get_bytes_optional", return_value=b"<p>Revenue</p>"),
        ):
            document = press_releases.press_release_document("1234", "0001234-26-000001", "8-k.htm")

        self.assertEqual(document.url, "https://sec.test/ex99-1.htm")
        self.assertEqual(document.html, "<p>Revenue</p>")

    def test_document_contains_structured_guidance_and_income_values(self):
        html = """
          <p>We reaffirm our full-year outlook.</p>
          <table><caption>Three Months Ended (in millions)</caption>
            <tr><th>Net Sales</th><td>$ 47,861</td></tr>
            <tr><th>Operating Income</th><td>12,300</td></tr>
            <tr><th>Net Income</th><td>9,100</td></tr>
          </table>
        """
        with (
            patch.object(press_releases.sec, "filing_archive_items", return_value=[
                {"name": "ex99-1.htm", "description": "EX-99.1 earnings release"},
            ]),
            patch.object(press_releases.sec, "filing_document_url", return_value="https://sec.test/ex99-1.htm"),
            patch.object(press_releases.sec, "get_bytes_optional", return_value=html.encode()),
        ):
            document = press_releases.press_release_document("1234", "0001234-26-000001", "8-k.htm")

        self.assertEqual(document.operating_income_actual, 12_300_000_000.0)
        self.assertEqual(document.net_income_actual, 9_100_000_000.0)
        self.assertIn("reaffirm", document.guidance_summary)


if __name__ == "__main__":
    unittest.main()
