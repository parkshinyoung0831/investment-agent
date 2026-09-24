"""로컬 긴 가격 이력으로 과거 RSI·MACD를 채우는 명령."""
from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from investment_agent.research.features.long_history import build_long_history


class LongHistoryTest(unittest.TestCase):
    def test_indicators_are_written_from_the_start_date_with_earlier_bars_as_warmup(self):
        days = pd.bdate_range(date(2014, 1, 2), date(2015, 6, 30)).date
        prices = pd.DataFrame({"ticker": ["AAA"] * len(days) + ["BBB"] * len(days),
                               "trade_date": list(days) * 2,
                               "close": [100 + (i % 11) for i in range(len(days))] * 2})
        calls: list[pd.DataFrame] = []
        written = build_long_history(start=date(2015, 1, 2), prices=prices,
                                     upsert=lambda frame: calls.append(frame) or len(frame))
        self.assertEqual(1, len(calls))  # 분할을 한 번만 다시 쓴다
        stored = calls[0]
        self.assertEqual(written, len(stored))
        self.assertEqual({"AAA", "BBB"}, set(stored["ticker"]))
        self.assertEqual(date(2015, 1, 2), min(pd.to_datetime(stored["trade_date"]).dt.date))
        self.assertTrue(stored[["rsi14", "macd", "macd_signal"]].notna().all().all())
        self.assertTrue(stored["rsi14"].between(0, 100).all())


if __name__ == "__main__":
    unittest.main()
