"""Unit tests for 8-K earnings flash collector and helpers."""
from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from investment_agent.data.fundamentals.application.detect_earnings_events import (
    determine_fiscal_period,
    detect_earnings_events_for_ticker,
    reported_eps_for_filing,
)
from investment_agent.data.fundamentals.application import PressReleaseDocument
from investment_agent.data.fundamentals.infrastructure.sec.companyfacts import is_earnings_8k
from investment_agent.data.fundamentals.domain.services.parse_earnings_release import parse_earnings_release


class TestFundamentalsFlash(unittest.TestCase):
    def test_is_earnings_8k_item_detection(self):
        # Item 2.02 detection
        self.assertTrue(is_earnings_8k("8-K", "2.02,9.01"))
        self.assertTrue(is_earnings_8k("8-K", "2.02"))

        # Other items should not match
        self.assertFalse(is_earnings_8k("8-K/A", "Item 2.02, Item 9.01"))
        self.assertFalse(is_earnings_8k("8-K", "5.02,9.01"))
        self.assertFalse(is_earnings_8k("10-Q", "2.02"))
        self.assertFalse(is_earnings_8k("8-K", None))

    def test_fiscal_period_follows_the_company_calendar(self):
        """1월 결산 유통사는 8월 8-K가 FY+1 Q2다. 달력 월로 매기면 FY Q3가 된다."""
        repository = MagicMock()
        repository.load_fiscal_calendar.return_value = [
            {"fiscal_year": 2026, "fiscal_period": "Q4", "period_end": "2026-01-31"},
            {"fiscal_year": 2027, "fiscal_period": "Q1", "period_end": "2026-04-30"},
        ]

        resolved = determine_fiscal_period(
            "WMT", "2026-08-20", "2026-08-20", repository=repository,
        )

        self.assertIsNotNone(resolved)
        fy, fp, pend = resolved
        self.assertEqual((fy, fp), (2027, "Q2"))
        # 실제 분기는 아직 10-Q가 없어 밀어 만든 값이다. 조인 키는 (fy, fp)이므로
        # 종료일은 근사로 충분하다 — WMT 실제 07-31, 밀어 만든 값 07-28.
        self.assertEqual(pend[:7], "2026-07")

    def test_unresolvable_period_returns_none_instead_of_guessing(self):
        """회계력이 없으면 추정하지 않는다. 틀린 분기 카드보다 거르는 쪽이 안전하다."""
        repository = MagicMock()
        repository.load_fiscal_calendar.return_value = []

        self.assertIsNone(
            determine_fiscal_period("XYZ", "2026-08-20", "2026-06-30", repository=repository)
        )

    def test_stale_calendar_is_rejected_instead_of_projected(self):
        """회계력이 1년 넘게 낡으면 밀어 만들지 않는다.

        무한정 밀면 3년 낡은 회계력에서도 12분기를 밀어 자신 있게 틀린 분기를 붙인다.
        """
        repository = MagicMock()
        repository.load_fiscal_calendar.return_value = [
            {"fiscal_year": 2023, "fiscal_period": "Q1", "period_end": "2023-03-31"},
        ]

        self.assertIsNone(
            determine_fiscal_period("ZZZ", "2026-12-01", "2026-12-01", repository=repository)
        )

    def test_one_quarter_ahead_of_the_last_10q_still_resolves(self):
        """8-K는 10-Q보다 앞선다. 한 분기 미래는 정상이라 판정되어야 한다."""
        repository = MagicMock()
        repository.load_fiscal_calendar.return_value = [
            {"fiscal_year": 2026, "fiscal_period": "Q1", "period_end": "2026-03-31"},
        ]

        resolved = determine_fiscal_period(
            "ZZZ", "2026-07-20", "2026-07-20", repository=repository)

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved[:2], (2026, "Q2"))

    def test_reported_eps_uses_only_the_nearby_earnings_date(self):
        reported = {
            "2026-05-20": {"eps_actual": 1.87},
            "2026-08-27": {"eps_actual": 2.22},
        }

        self.assertEqual(reported_eps_for_filing(reported, "2026-08-26"), 2.22)
        self.assertIsNone(reported_eps_for_filing(reported, "2026-08-21"))

    def test_detected_flash_persists_reported_eps(self):
        filing_source = MagicMock()
        filing_source.earnings_8k_filings.return_value = [SimpleNamespace(
            filing_date="2026-08-26",
            report_date="2026-07-26",
            accession_no="0001045810-26-000073",
            primary_document="nvda-20260826.htm",
        )]
        press_release_source = MagicMock()
        press_release_source.press_release_document.return_value = PressReleaseDocument(None, None)
        repository = MagicMock()
        repository.load_fiscal_calendar.return_value = [{
            "fiscal_year": 2026,
            "fiscal_period": "Q1",
            "period_end": "2026-06-30",
        }]
        captured: list[dict] = []
        repository.upsert_earnings_results.side_effect = (
            lambda rows: captured.extend(rows) or len(rows)
        )
        reported_source = MagicMock()
        reported_source.fetch_reported_earnings.return_value = {
            "2026-08-26": {"eps_actual": 2.22},
        }

        detect_earnings_events_for_ticker(
            "NVDA",
            "0001045810",
            filing_source=filing_source,
            press_release_source=press_release_source,
            repository=repository,
            reported_source=reported_source,
            today=date(2026, 8, 27),
        )

        self.assertEqual(captured[0]["eps_actual"], 2.22)

    def test_reported_eps_failure_keeps_sec_row_but_marks_run_failed(self):
        filing_source = MagicMock()
        filing_source.earnings_8k_filings.return_value = [SimpleNamespace(
            filing_date="2026-08-26",
            report_date="2026-07-26",
            accession_no="0001045810-26-000073",
            primary_document="nvda-20260826.htm",
        )]
        press_release_source = MagicMock()
        press_release_source.press_release_document.return_value = PressReleaseDocument(None, None)
        repository = MagicMock()
        repository.load_fiscal_calendar.return_value = [{
            "fiscal_year": 2026,
            "fiscal_period": "Q1",
            "period_end": "2026-06-30",
        }]
        repository.upsert_earnings_results.side_effect = lambda rows: len(rows)
        reported_source = MagicMock()
        reported_source.fetch_reported_earnings.side_effect = RuntimeError(
            "Yahoo unavailable"
        )

        result = detect_earnings_events_for_ticker(
            "NVDA",
            "0001045810",
            filing_source=filing_source,
            press_release_source=press_release_source,
            repository=repository,
            reported_source=reported_source,
            today=date(2026, 8, 27),
        )

        self.assertEqual(result["rows"], 1)
        self.assertEqual(result["failures"][0]["stage"], "reported_earnings")

    def test_uses_edgartools_table_revenue_before_text_fallback(self):
        filing_source = MagicMock()
        filing_source.earnings_8k_filings.return_value = [SimpleNamespace(
            filing_date="2026-08-26",
            report_date="2026-07-26",
            accession_no="0001045810-26-000073",
            primary_document="nvda-20260826.htm",
        )]
        press_release_source = MagicMock()
        press_release_source.press_release_document.return_value = PressReleaseDocument(
            html="<p>Revenue of $96.2 billion.</p>",
            url="https://example.test/ex99",
            revenue_actual=96_221_000_000.0,
            operating_income_actual=32_000_000_000.0,
            net_income_actual=26_000_000_000.0,
        )
        repository = MagicMock()
        repository.load_fiscal_calendar.return_value = [{
            "fiscal_year": 2026,
            "fiscal_period": "Q1",
            "period_end": "2026-06-30",
        }]
        captured: list[dict] = []
        repository.upsert_earnings_results.side_effect = (
            lambda rows: captured.extend(rows) or len(rows)
        )

        detect_earnings_events_for_ticker(
            "NVDA",
            "0001045810",
            filing_source=filing_source,
            press_release_source=press_release_source,
            repository=repository,
            today=date(2026, 8, 27),
        )

        self.assertEqual(captured[0]["revenue_actual"], 96_221_000_000.0)
        self.assertEqual(captured[0]["operating_income_actual"], 32_000_000_000.0)
        self.assertEqual(captured[0]["net_income_actual"], 26_000_000_000.0)

    def test_parses_sales_table_in_millions_when_edgartools_has_no_statement(self):
        revenue, guidance = parse_earnings_release("""
            <table><caption>Three Months Ended (in millions)</caption>
              <tr><th>Net sales</th><td>$ 47,861</td><td>$ 45,277</td></tr>
            </table>
        """)

        self.assertEqual(revenue, 47_861_000_000.0)
        self.assertIsNone(guidance)

    def test_does_not_treat_revenue_guidance_as_reported_revenue(self):
        revenue, _ = parse_earnings_release("""
            <table><caption>Fiscal 2027 guidance (in millions)</caption>
              <tr><th>Total revenue</th><td>$ 23,500</td></tr>
            </table>
            <table><caption>Three Months Ended (in millions)</caption>
              <tr><th>Total revenue</th><td>$ 4,354</td></tr>
            </table>
        """)

        self.assertEqual(revenue, 4_354_000_000.0)

    def test_parses_thousand_dollar_sales_table(self):
        revenue, _ = parse_earnings_release("""
            <table>
              <tr><th colspan="3">Three Months Ended ($000)</th></tr>
              <tr><th>Sales</th><td>$ 6,264,886</td><td>$ 5,529,152</td></tr>
            </table>
        """)

        self.assertEqual(revenue, 6_264_886_000.0)

    def test_does_not_treat_investment_sales_as_company_revenue(self):
        revenue, _ = parse_earnings_release(
            "Investment gains include realized gains on sales of investments of $1.8 billion."
        )

        self.assertIsNone(revenue)


if __name__ == "__main__":
    unittest.main()
