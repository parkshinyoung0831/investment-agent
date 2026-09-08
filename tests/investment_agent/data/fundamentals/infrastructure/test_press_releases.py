"""SEC archive 8-K 보도자료 어댑터의 네트워크 없는 계약 테스트."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from investment_agent.data.fundamentals.infrastructure.sec.press_releases import (
    press_release_document,
)


class PressReleaseAdapterTest(unittest.TestCase):
    def test_selects_archive_exhibit_and_extracts_table_value(self) -> None:
        with (
            patch("investment_agent.data.fundamentals.infrastructure.sec.press_releases.sec.filing_archive_items", return_value=[
                {"name": "8-k.htm", "description": "8-K"},
                {"name": "ex99-1.htm", "description": "EX-99.1 earnings release"},
            ]),
            patch("investment_agent.data.fundamentals.infrastructure.sec.press_releases.sec.filing_document_url", return_value="https://sec.test/ex99-1.htm"),
            patch("investment_agent.data.fundamentals.infrastructure.sec.press_releases.sec.get_bytes_optional", return_value=b"<table><caption>Three Months Ended (in millions)</caption><tr><th>Net Sales</th><td>$ 47,861</td></tr></table>"),
        ):
            document = press_release_document("1234", "0001234-26-000001", "8-k.htm")

        self.assertEqual(document.revenue_actual, 47_861_000_000.0)
        self.assertEqual(document.url, "https://sec.test/ex99-1.htm")

    def test_archive_failure_is_not_converted_to_an_empty_release(self) -> None:
        with (
            patch(
                "investment_agent.data.fundamentals.infrastructure.sec.press_releases.sec.filing_archive_items",
                side_effect=RuntimeError("SEC unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "SEC unavailable"),
        ):
            press_release_document("1234", "0001234-26-000001", "8-k.htm")


if __name__ == "__main__":
    unittest.main()
