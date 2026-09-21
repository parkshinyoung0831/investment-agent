"""페이지 조회의 정렬은 유일해야 한다 — 같은 값이 여럿이면 `range()` 경계에서 행이 중복·누락된다(RP-08)."""
from __future__ import annotations

import logging
import unittest
from typing import Any

from investment_agent.reporting.readers.financial import VIEWS
from investment_agent.reporting.readers.select_only import SelectOnlyGateway, security_identity

# 시각·기간만으로 정렬하던 뷰가 동률에서 흔들리지 않도록 마지막에 붙인 유일 키.
UNIQUE_TIEBREAK = {
    "execution_control_state": "scope",
    "execution_intents": "intent_id",
    "execution_approvals": "approval_id",
    "execution_orders": "client_order_id",
    "execution_fills": "broker_fill_id",
    "institutional_filings": "accession_no",
}


class ViewOrderIsUniqueTest(unittest.TestCase):
    def test_event_views_end_their_order_with_a_unique_key(self) -> None:
        for view, key in UNIQUE_TIEBREAK.items():
            with self.subTest(view=view):
                self.assertIn(key, VIEWS[view].order_by.split(","))


class _Response:
    def __init__(self, data: list[dict]) -> None:
        self.data = data


class _Query:
    def __init__(self, total: int) -> None:
        self._total = total
        self._range = (0, 0)

    def select(self, *_a: Any, **_k: Any): return self
    def eq(self, *_a: Any, **_k: Any): return self
    def in_(self, *_a: Any, **_k: Any): return self
    def order(self, *_a: Any, **_k: Any): return self
    def limit(self, *_a: Any, **_k: Any): return self

    def range(self, start: int, end: int):
        self._range = (start, end)
        return self

    def execute(self):
        start, end = self._range
        return _Response([{"n": n} for n in range(start, min(end + 1, self._total))])


class _Client:
    def __init__(self, total: int) -> None:
        self._total = total

    def schema(self, _name: str): return self
    def table(self, _name: str): return _Query(self._total)


class CeilingWarningTest(unittest.TestCase):
    def _read(self, total: int) -> list[dict]:
        gateway = SelectOnlyGateway(_Client(total))
        return gateway.select_rows(
            schema="reporting", table="prices_daily", columns="n",
            order=(("n", False),), page_size=100, max_rows=250,
        )

    def test_hitting_the_row_ceiling_is_logged_not_silent(self) -> None:
        with self.assertLogs("investment_agent.reporting.readers.select_only", level=logging.WARNING) as logs:
            rows = self._read(1_000)
        self.assertEqual(250, len(rows))
        self.assertIn("row ceiling", logs.output[0])

    def test_a_result_below_the_ceiling_is_not_flagged(self) -> None:
        with self.assertNoLogs("investment_agent.reporting.readers.select_only", level=logging.WARNING):
            self.assertEqual(120, len(self._read(120)))


class SharedCikTest(unittest.TestCase):
    def test_two_tickers_of_one_company_are_reported(self) -> None:
        class Gateway:
            def select_rows(self, **_k: Any) -> list[dict]:
                return [
                    {"security_id": 1, "ticker": "GOOG", "cik": "1652044", "is_active_listing": True},
                    {"security_id": 2, "ticker": "GOOGL", "cik": "1652044", "is_active_listing": True},
                ]

        with self.assertLogs("investment_agent.reporting.readers.select_only", level=logging.WARNING) as logs:
            by_ticker, by_cik = security_identity(Gateway(), ["GOOG", "GOOGL"])
        self.assertEqual(2, len(by_ticker))
        self.assertEqual(1, len(by_cik))
        self.assertIn("1652044".zfill(10), logs.output[0])


if __name__ == "__main__":
    unittest.main()
