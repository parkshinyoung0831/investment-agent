"""프롬프트에 실리는 원자료 양을 못박는다.

Azure gpt-5-mini 배포 실측(2026-09-03): 50,000 토큰/분, 50 요청/분.
한 종목이 LLM 호출 15건을 쓰므로 호출당 프롬프트가 작아야 한 종목이 끝난다.
통계는 전체 행으로 계산하되, 원자료 행은 최근 것만 싣는다.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.trading.evidence.context import FILING_ROWS_IN_PROMPT, ContextBuilder


BASE = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _filing(index: int) -> dict:
    """as_of(2026-09-03)보다 과거인 분기 공시. 최신이 index 0이다."""
    filed = BASE - timedelta(days=90 * index)
    return {
        "filed_at": filed.date().isoformat(),
        "ingested_at": (filed + timedelta(days=1)).isoformat(),
        "period_end": filed.date().isoformat(),
        "fiscal_period": "Q1",
        "revenue": 1000 + index,
        "net_income": 100 + index,
    }


class _Repository:
    def __init__(self, filings: int):
        self._filings = [_filing(i) for i in range(filings)]

    def market_prices(self, ticker, as_of_at, limit=None):
        return []

    def technical_snapshot(self, ticker, as_of_at):
        return []

    def fundamentals(self, ticker, as_of_at):
        return list(self._filings)

    def estimates(self, ticker, as_of_at):
        return {"consensus": []}

    def macro_snapshot(self, as_of_at):
        return {}

    def segment_snapshot(self, ticker, as_of_at):
        return {}

    def guru_snapshot(self, ticker, as_of_at):
        return {}

    def econ_snapshot(self, as_of_at):
        return {"events": [], "results": [], "forecasts": []}


class FilingRowCapTest(unittest.TestCase):
    def _fundamentals_item(self, filings: int):
        bundle = ContextBuilder(_Repository(filings)).build(
            "AAPL", datetime(2026, 9, 3, tzinfo=timezone.utc),
        )
        return next(item for item in bundle.evidence if item.domain == "fundamentals")

    def test_only_the_most_recent_filings_reach_the_prompt(self):
        item = self._fundamentals_item(12)

        self.assertEqual(len(item.payload["filings"]), FILING_ROWS_IN_PROMPT)

    def test_the_kept_filings_are_the_newest_ones(self):
        item = self._fundamentals_item(12)

        kept = [row["filed_at"] for row in item.payload["filings"]]
        self.assertEqual(kept, [_filing(i)["filed_at"] for i in range(FILING_ROWS_IN_PROMPT)])

    def test_the_card_says_how_many_filings_were_left_out(self):
        """자른 것을 숨기면 모델이 '이게 전부'라고 읽는다."""
        item = self._fundamentals_item(12)

        self.assertEqual(item.payload["filings_total"], 12)
        self.assertLess(len(item.payload["filings"]), item.payload["filings_total"])

    def test_a_short_history_is_left_alone(self):
        item = self._fundamentals_item(2)

        self.assertEqual(len(item.payload["filings"]), 2)


if __name__ == "__main__":
    unittest.main()
