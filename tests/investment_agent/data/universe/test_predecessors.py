"""지주회사 재편 전 제출자의 재무가 현재 ticker로 이어지는지."""
from __future__ import annotations

import re
import unittest

from investment_agent.data.fundamentals.infrastructure.supabase.expectations import _tickers_by_cik
from investment_agent.data.universe.domain.predecessors import PREDECESSOR_CIKS, with_predecessors


class PredecessorTest(unittest.TestCase):
    def test_a_reorganized_ticker_reads_its_predecessor_filings(self) -> None:
        mapping = _tickers_by_cik([{"ticker": "XOM", "cik": "2115436"}, {"ticker": "AAPL", "cik": "0000320193"}])
        self.assertEqual(["XOM"], mapping["0000034088"])
        self.assertEqual(["XOM"], mapping["0002115436"])
        self.assertNotIn("0000000000", mapping)
        self.assertEqual(["AAPL"], mapping["0000320193"])

    def test_unrelated_ciks_gain_nothing(self) -> None:
        self.assertEqual({"0000320193": "0000320193"}, with_predecessors(["320193"]))

    def test_catalog_ciks_are_ten_digit_and_never_their_own_predecessor(self) -> None:
        for current, previous in PREDECESSOR_CIKS.items():
            self.assertRegex(current, re.compile(r"^\d{10}$"))
            for cik in previous:
                self.assertRegex(cik, re.compile(r"^\d{10}$"))
                self.assertNotEqual(current, cik)
                self.assertNotIn(cik, PREDECESSOR_CIKS, "연쇄 재편은 현재 CIK 한 줄에 모두 적는다")


if __name__ == "__main__":
    unittest.main()
