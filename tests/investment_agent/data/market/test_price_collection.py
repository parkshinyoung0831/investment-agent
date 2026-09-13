"""daily와 backfill이 함께 쓰는 수집 절차: 계획의 security_id로만 저장하고 기업행위를 날짜별로 합친다."""
from __future__ import annotations

import unittest

from investment_agent.data.market.application.price_collection import (
    action_rows,
    changed_prices,
    collect_prices,
)
from investment_agent.data.market.domain.models import PriceTarget


def _raw(symbol: str, day: str, **extra) -> dict:
    return {"ticker": symbol, "trade_date": day, "open": 10.0, "high": 11.0, "low": 9.0,
            "close": 10.0, "volume": 100, "source": "yfinance", **extra}


class CollectPricesTest(unittest.TestCase):
    def test_rows_carry_the_security_id_fixed_by_the_plan(self) -> None:
        batch = collect_prices([PriceTarget(1000007, "META")], lookback_days=5,
                               download=lambda symbols, days: [_raw("META", "2026-09-11")])
        self.assertEqual([1000007], [row["security_id"] for row in batch.prices])
        self.assertNotIn("ticker", batch.prices[0])

    def test_a_symbol_outside_the_plan_is_refused(self) -> None:
        """요청하지 않은 종목을 받았으면 어느 ID에 쓸지 추측하지 않는다."""
        with self.assertRaisesRegex(RuntimeError, "outside the collection plan"):
            collect_prices([PriceTarget(1, "AAA")], lookback_days=5,
                           download=lambda symbols, days: [_raw("AAA", "2026-09-11"), _raw("BBB", "2026-09-11")])

    def test_an_empty_response_is_a_failure(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no rows"):
            collect_prices([PriceTarget(1, "AAA")], lookback_days=5, download=lambda symbols, days: [])

    def test_archive_runs_before_rows_are_returned(self) -> None:
        seen: list[int] = []
        collect_prices([PriceTarget(1, "AAA")], lookback_days=5,
                       download=lambda symbols, days: [_raw("AAA", "2026-09-11")],
                       archive=lambda rows: seen.extend(row["security_id"] for row in rows))
        self.assertEqual([1], seen)

    def test_split_and_dividend_on_one_day_become_one_action_row(self) -> None:
        rows = action_rows([{**_raw("AAA", "2024-06-10", split_ratio=10.0, div_amount=0.01), "security_id": 1}])
        self.assertEqual([{"security_id": 1, "action_date": "2024-06-10", "source": "yfinance",
                           "split_ratio": 10.0, "dividend_amount": 0.01, "dividend_currency": "USD"}], rows)

    def test_a_day_without_actions_does_not_send_empty_values(self) -> None:
        """없는 값을 NULL로 보내면 기존 분할·배당을 지운다 — 싣지 않아야 병합이 보존한다."""
        rows = action_rows([{**_raw("AAA", "2024-06-11", div_amount=0.0), "security_id": 1}])
        self.assertEqual([], rows)

    def test_only_changed_prices_are_written(self) -> None:
        batch = collect_prices([PriceTarget(1, "AAA")], lookback_days=5,
                               download=lambda symbols, days: [_raw("AAA", "2026-09-10"), _raw("AAA", "2026-09-11")])
        existing = {(1, "2026-09-10"): dict(batch.prices[0])}
        self.assertEqual(["2026-09-11"], [row["trade_date"] for row in changed_prices(batch.prices, existing)])


if __name__ == "__main__":
    unittest.main()
