"""원본 판단 feature와 사후 시장 label의 분리를 검증한다."""
from __future__ import annotations
import unittest
from investment_agent.research.rl.decision_dataset import decision_training_set, decision_features

class DecisionDatasetTest(unittest.TestCase):
    def test_preserves_original_features_and_excludes_future_labels(self):
        row={"record_key":"d1", "ticker":"AAPL", "as_of_at":"2026-01-01T10:00:00+00:00", "decision_available_at":"2026-01-01T11:00:00+00:00", "available_at":"2026-01-08T00:00:00+00:00", "end_trade_date":"2026-01-07", "features":decision_features({"confidence":.7,"probability_up":.6,"expected_excess_return":.02,"signal":"watch"}), "asset_return":.05,"benchmark_return":.01}
        future=dict(row, record_key="d2", as_of_at="2026-02-01T10:00:00+00:00", available_at="2026-02-08T00:00:00+00:00")
        result=decision_training_set([row,future], as_of_at="2026-01-10T00:00:00+00:00", max_symbols=30)
        self.assertEqual(result.dataset.as_of_values, (row["decision_available_at"],))
        self.assertEqual(result.dataset.forward_returns[0,0], .05)
        self.assertEqual(result.label_ids, ("d1",))
        self.assertEqual(row["features"]["decision_action_watch"], 1.)


class SymbolSelectionTest(unittest.TestCase):
    """종목 상한은 이름순이 아니라 판단 경험이 많은 종목을 남긴다(RS-8)."""

    def _row(self, key, ticker, day):
        features = decision_features({"confidence": .7, "probability_up": .6, "expected_excess_return": .02, "signal": "watch"})
        return {"record_key": key, "ticker": ticker, "as_of_at": f"2026-01-{day:02d}T10:00:00+00:00",
                "decision_available_at": f"2026-01-{day:02d}T11:00:00+00:00", "available_at": f"2026-01-{day:02d}T20:00:00+00:00",
                "end_trade_date": f"2026-01-{day:02d}", "features": features, "asset_return": .01, "benchmark_return": .0}

    def test_the_most_observed_tickers_survive_a_cap_not_the_alphabetically_first(self):
        rows = [self._row("a1", "AAA", 2),
                self._row("z1", "ZZZ", 3), self._row("z2", "ZZZ", 4), self._row("z3", "ZZZ", 5),
                self._row("m1", "MMM", 6), self._row("m2", "MMM", 7)]
        result = decision_training_set(rows, as_of_at="2026-02-01T00:00:00+00:00", max_symbols=2)
        self.assertEqual(("MMM", "ZZZ"), result.dataset.symbols)
