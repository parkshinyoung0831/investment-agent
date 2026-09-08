"""후보 선정은 feature 창을 한 번만 읽는다.

전에는 tracked 종목마다 `features_for_ticker`를 불렀다 — 실측으로 한 번의 후보
선정이 DuckDB를 **463번** 열었고, 그때마다 DDL과 legacy 마이그레이션까지 돌았다.
파일 잠금도 그만큼 잡혀서 같은 파일을 보던 다른 조회가 IOException으로 죽었다.

종목 수는 지수 구성에 따라 늘어난다. "종목마다 한 번"은 늘어나는 쪽으로 조용히
나빠지는 모양이라, 횟수가 종목 수에 붙지 않는다는 것을 여기서 못박는다.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from investment_agent.trading.supabase_repository import SupabaseRepository

AS_OF = datetime(2026, 9, 1, 21, tzinfo=timezone.utc)
TICKERS = [f"T{index:03d}" for index in range(120)]


def _feature_rows() -> list[dict]:
    rows = []
    for ticker in TICKERS:
        for day in range(3):
            trade_date = (AS_OF.date() - timedelta(days=day)).isoformat()
            rows.append({"ticker": ticker, "trade_date": trade_date, "rsi14": 50.0,
                         "macd": 0.1, "macd_signal": 0.05,
                         "ingested_at": "2026-09-01T00:00:00+00:00"})
    return rows


class CandidateFeatureReadTest(unittest.TestCase):
    def setUp(self) -> None:
        self.window_calls: list[str] = []
        self.per_ticker_calls: list[str] = []

    def _read(self) -> list[dict]:
        def features_since(since: str) -> list[dict]:
            self.window_calls.append(since)
            return _feature_rows()

        def features_for_ticker(ticker: str, **_kwargs) -> list[dict]:
            self.per_ticker_calls.append(ticker)
            return []

        with (
            patch("investment_agent.research.features.db.features_since", features_since),
            patch("investment_agent.research.features.db.features_for_ticker", features_for_ticker),
        ):
            return SupabaseRepository()._candidate_technical_rows(TICKERS, AS_OF)

    def test_the_window_is_read_once_no_matter_how_many_tickers(self) -> None:
        self._read()
        self.assertEqual(1, len(self.window_calls))
        self.assertEqual([], self.per_ticker_calls)

    def test_every_requested_ticker_still_comes_back(self) -> None:
        rows = self._read()
        self.assertEqual(set(TICKERS), {row["ticker"] for row in rows})

    def test_rows_ingested_after_the_cutoff_are_left_out(self) -> None:
        """시점 근거다 — cutoff 뒤에 들어온 값이 섞이면 미래를 보게 된다."""
        late = [{**row, "ingested_at": "2026-09-05T00:00:00+00:00"} for row in _feature_rows()]
        with patch("investment_agent.research.features.db.features_since", lambda _s: late):
            self.assertEqual([], SupabaseRepository()._candidate_technical_rows(TICKERS, AS_OF))

    def test_rows_after_the_as_of_date_are_left_out(self) -> None:
        future = [{**row, "trade_date": "2026-09-30"} for row in _feature_rows()]
        with patch("investment_agent.research.features.db.features_since", lambda _s: future):
            self.assertEqual([], SupabaseRepository()._candidate_technical_rows(TICKERS, AS_OF))


if __name__ == "__main__":
    unittest.main()
