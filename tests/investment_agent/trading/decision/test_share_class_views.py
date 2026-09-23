"""같은 회사의 다른 주식은 논지를 함께 쓴다 — 회사당 한 번만 분석한다."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.trading.decision.alpha import ThesisView
from investment_agent.trading.decision.candidate_ranker import collapse_share_classes, share_twin_views

NOW = datetime(2026, 9, 21, tzinfo=timezone.utc)
COMPANY = {"GOOGL": "0001652044", "GOOG": "0001652044", "BRK.B": "0001067983"}


def _view(ticker, *, days_ago=1, thesis="positive"):
    return ThesisView(ticker, NOW - timedelta(days=days_ago), "open", 0.02, 0.6, 0.7, thesis=thesis)


class CollapseShareClassesTest(unittest.TestCase):
    def test_the_first_share_class_is_kept_in_order(self):
        kept, dropped = collapse_share_classes(["GOOG", "AAA", "GOOGL", "BRK.B"], COMPANY)
        self.assertEqual(["GOOG", "AAA", "BRK.B"], kept)
        self.assertEqual({"GOOGL": "GOOG"}, dropped)

    def test_tickers_without_a_company_are_never_collapsed(self):
        self.assertEqual((["X", "Y"], {}), collapse_share_classes(["X", "Y"], {}))


class ShareTwinViewsTest(unittest.TestCase):
    def test_a_missing_twin_gets_the_company_view_under_its_own_ticker(self):
        views = share_twin_views({"GOOGL": _view("GOOGL")}, ["GOOGL", "GOOG"], COMPANY)
        self.assertEqual("GOOG", views["GOOG"].ticker)
        self.assertEqual(views["GOOGL"].as_of_at, views["GOOG"].as_of_at)
        self.assertEqual("positive", views["GOOG"].thesis)

    def test_an_own_view_is_never_overwritten_and_the_latest_company_view_wins(self):
        own = _view("GOOG", days_ago=5, thesis="negative")
        views = share_twin_views({"GOOG": own, "GOOGL": _view("GOOGL", days_ago=1)}, ["GOOG", "GOOGL"], COMPANY)
        self.assertIs(own, views["GOOG"])
        views = share_twin_views({"GOOGL": _view("GOOGL", days_ago=9, thesis="negative"),
                                  "GOOG": _view("GOOG", days_ago=2)}, ["GOOGL", "GOOG", "BRK.B"],
                                 {**COMPANY, "X": "0001652044"})
        self.assertNotIn("BRK.B", views)


if __name__ == "__main__":
    unittest.main()
