"""fast path 시즌 게이트 — 특히 fail-open 규칙 회귀 테스트.

이 게이트가 잘못 "시즌 아님"을 내면 관심종목 공시 알림이 통째로 늦어진다.
근거가 부족한 모든 경우에 True를 내는지가 핵심이다.
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from investment_agent.data.fundamentals.application import refresh_earnings_season as season

_TODAY = date(2026, 8, 24)


def _row(ticker: str, expected: str | None, *, snapshot: str = "2026-08-23") -> dict:
    return {"ticker": ticker, "snapshot_date": snapshot, "expected_report_date": expected}


class SeasonWindowTest(unittest.TestCase):
    def test_expected_date_inside_window_is_in_season(self):
        state = season.evaluate([_row("NVDA", "2026-08-26")], _TODAY)

        self.assertTrue(state["in_season"])
        self.assertEqual(state["reason"], "within_window")
        self.assertEqual(state["tickers"], ["NVDA"])

    def test_lead_window_opens_before_the_expected_date(self):
        # 기본 lead=5일 — 예정일 5일 전부터 켠다.
        self.assertTrue(season.evaluate([_row("KO", "2026-08-29")], _TODAY)["in_season"])
        self.assertFalse(season.evaluate([_row("KO", "2026-08-30")], _TODAY)["in_season"])

    def test_lag_window_stays_open_after_the_expected_date(self):
        # 기본 lag=10일 — 10-Q 제출이 보도자료보다 늦게 오는 경우를 덮는다.
        self.assertTrue(season.evaluate([_row("KO", "2026-08-14")], _TODAY)["in_season"])
        self.assertFalse(season.evaluate([_row("KO", "2026-08-13")], _TODAY)["in_season"])

    def test_out_of_season_only_when_every_date_is_known(self):
        state = season.evaluate(
            [_row("AAPL", "2026-10-30"), _row("KO", "2026-10-20")], _TODAY
        )

        self.assertFalse(state["in_season"])
        self.assertEqual(state["reason"], "out_of_season")

    def test_one_ticker_in_window_wakes_the_whole_run(self):
        state = season.evaluate(
            [_row("AAPL", "2026-10-30"), _row("NVDA", "2026-08-26")], _TODAY
        )

        self.assertTrue(state["in_season"])
        self.assertEqual(state["tickers"], ["NVDA"])


class FailOpenTest(unittest.TestCase):
    """근거가 없으면 언제나 수집을 돌린다 — 놓치는 쪽이 훨씬 비싸다."""

    def test_no_rows_is_in_season(self):
        state = season.evaluate([], _TODAY)

        self.assertTrue(state["in_season"])
        self.assertEqual(state["reason"], "no_snapshot")

    def test_missing_expected_dates_is_in_season(self):
        state = season.evaluate([_row("AAPL", None), _row("KO", None)], _TODAY)

        self.assertTrue(state["in_season"])
        self.assertEqual(state["reason"], "no_expected_dates")

    def test_stale_snapshot_is_in_season_even_when_dates_are_far_off(self):
        stale = (_TODAY - timedelta(days=30)).isoformat()
        state = season.evaluate([_row("AAPL", "2026-10-30", snapshot=stale)], _TODAY)

        self.assertTrue(state["in_season"])
        self.assertEqual(state["reason"], "stale_snapshot")

    def test_unparseable_dates_do_not_crash(self):
        state = season.evaluate([_row("AAPL", "not-a-date")], _TODAY)

        self.assertTrue(state["in_season"])
        self.assertEqual(state["reason"], "no_expected_dates")


if __name__ == "__main__":
    unittest.main()
