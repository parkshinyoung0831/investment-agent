"""label의 시작 종가는 snapshot 시각에 이미 확정된 봉이다(RS-3), 그리고 label 구간은 하나로 고정된다(RS-13).

UTC 달력일로 자르면 장전·장중 snapshot의 시작 종가가 그날 종가가 되어 as_of 이후에야 알 수 있는 값을 쓴다.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from investment_agent.forecasting import SIGNAL_HORIZON_DAYS
from investment_agent.platform.clock import completed_us_daily_bar_cutoff
from investment_agent.research.commands import build_labels as module
from investment_agent.research.commands.build_labels import _session_close


class SessionCloseTest(unittest.TestCase):
    def test_a_label_is_available_when_feature_side_considers_the_bar_known(self) -> None:
        # 뉴욕 18:00 확정: 여름(EDT)은 22:00Z, 겨울(EST)은 23:00Z.
        self.assertEqual(datetime(2026, 8, 20, 22, tzinfo=timezone.utc), _session_close("2026-08-20"))
        self.assertEqual(datetime(2026, 12, 18, 23, tzinfo=timezone.utc), _session_close("2026-12-18"))


class StartCloseCutoffTest(unittest.TestCase):
    def test_a_pre_open_snapshot_starts_from_the_previous_completed_close(self) -> None:
        pre_open = datetime(2026, 9, 15, 12, 27, tzinfo=timezone.utc)  # 화요일 08:27 ET, 그날 봉은 아직 없다
        self.assertEqual("2026-09-14", completed_us_daily_bar_cutoff(pre_open).isoformat())

    def test_a_post_close_snapshot_starts_from_that_days_close(self) -> None:
        post_close = datetime(2026, 9, 11, 23, 30, tzinfo=timezone.utc)  # 19:30 ET
        self.assertEqual("2026-09-11", completed_us_daily_bar_cutoff(post_close).isoformat())


class _Repository:
    """2026-08-20(목)~08-28 봉. 08-21(금) 봉은 그날 장마감 뒤에야 알 수 있다."""

    CLOSES = {"2026-08-20": 100.0, "2026-08-21": 110.0, "2026-08-24": 111.0, "2026-08-25": 112.0,
              "2026-08-26": 113.0, "2026-08-27": 114.0, "2026-08-28": 115.0}

    def current_tracked_tickers(self):
        return ["AAA"]

    def label_price_rows(self, tickers, *, start, end):
        return [{"ticker": ticker, "trade_date": day, "close": close}
                for ticker in tickers for day, close in self.CLOSES.items()]


class _Store:
    def __init__(self, as_of: str) -> None:
        self.as_of, self.saved = as_of, []

    def rl_feature_snapshot_rows(self, symbols, **kwargs):
        return [{"as_of_at": self.as_of, "ticker": "AAA"}]

    def rl_training_label_rows(self, symbols, **kwargs):
        return []

    def save_rl_training_labels(self, rows):
        self.saved.extend(rows)


class LabelStartsFromTheLastCompletedCloseTest(unittest.TestCase):
    def _label(self, as_of: str) -> dict:
        store = _Store(as_of)
        module.build_labels(
            as_of_at=datetime(2026, 9, 30, tzinfo=timezone.utc), horizon_days=5, lookback_days=90,
            repository=_Repository(), store=store,
        )
        (row,) = store.saved
        return row

    def test_a_pre_open_snapshot_does_not_start_from_that_days_close(self) -> None:
        label = self._label("2026-08-21T12:27:00+00:00")  # 금요일 08:27 ET
        # 시작 = 08-20 종가 100, 5거래일 뒤 = 08-27 종가 114. 08-21 종가(110)는 as_of 이후에야 아는 값이다.
        self.assertAlmostEqual(0.14, label["forward_return"], places=6)

    def test_a_post_close_snapshot_starts_from_that_days_close(self) -> None:
        label = self._label("2026-08-21T23:30:00+00:00")  # 19:30 ET, 08-21 봉 확정
        self.assertAlmostEqual(115.0 / 110.0 - 1.0, label["forward_return"], places=6)


class HorizonIsPinnedTest(unittest.TestCase):
    def test_the_cli_offers_only_the_stored_horizon(self) -> None:
        self.assertEqual(SIGNAL_HORIZON_DAYS, module._parse_args([]).horizon)
        with self.assertRaises(SystemExit):
            module._parse_args(["--horizon", "5"])


if __name__ == "__main__":
    unittest.main()
