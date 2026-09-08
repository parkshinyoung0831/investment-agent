"""feature 컬럼 안정성과 feature/label 생산 잡의 계약을 고정한다."""
from __future__ import annotations

import math
import unittest
from datetime import datetime, timezone

from investment_agent.trading.contracts import EvidenceBundle, EvidenceItem, parse_datetime
from investment_agent.research.commands.build_features import build_features
from investment_agent.research.commands.build_labels import build_labels
from investment_agent.research.features.layer import (
    FEATURE_COLUMNS,
    FEATURE_VERSION,
    MISSING_SUFFIX,
    OPTIONAL_FEATURES,
    REQUIRED_BARS,
    FeatureLayer,
    impute_cross_section,
)

_AS_OF = "2026-08-20T22:00:00+00:00"
_AVAILABLE = "2026-08-20T21:30:00+00:00"


def _item(index: int, domain: str, payload: dict) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=f"EV-{domain}-{index}", domain=domain, source=f"{domain}.source",
        observed_at="2026-08-20", available_at=_AVAILABLE, timing_status="known",
        payload=payload,
    )


def _bars(count: int) -> list[dict]:
    return [
        {"trade_date": f"2026-08-{day:02d}", "close": 100.0 + day}
        for day in range(count, 0, -1)
    ]


def _bundle(ticker: str, items: list[EvidenceItem]) -> EvidenceBundle:
    return EvidenceBundle(
        ticker=ticker, as_of_at=_AS_OF, source_kind="live_shadow", evidence=tuple(items),
    )


class FeatureColumnStabilityTest(unittest.TestCase):
    """컬럼 집합이 흔들리면 dataset 결합이 통째로 실패하므로 여기서 고정한다."""

    def _rich(self) -> EvidenceBundle:
        return _bundle("AAA", [
            _item(1, "market", {"latest_bars": _bars(REQUIRED_BARS)}),
            _item(2, "technical", {"rsi14": 55.0, "macd": 1.0, "macd_signal": 0.5}),
            _item(3, "macro", {"latest_observations": [
                {"series_id": "VIX", "value": 18.0},
                {"series_id": "DGS10", "value": 4.2},
            ]}),
        ])

    def _sparse(self) -> EvidenceBundle:
        return _bundle("BBB", [_item(1, "market", {"latest_bars": _bars(REQUIRED_BARS)})])

    def test_columns_are_identical_regardless_of_domain_coverage(self):
        rich = FeatureLayer().build(self._rich()).snapshot.features
        sparse = FeatureLayer().build(self._sparse()).snapshot.features
        self.assertEqual(set(rich), set(sparse))
        self.assertEqual(set(rich), set(FEATURE_COLUMNS))

    def test_missing_domain_keeps_the_column_and_raises_the_flag(self):
        sparse = FeatureLayer().build(self._sparse()).snapshot.features
        self.assertIsNone(sparse["technical_rsi14"])
        self.assertEqual(sparse[f"technical_rsi14{MISSING_SUFFIX}"], 1.0)
        rich = FeatureLayer().build(self._rich()).snapshot.features
        self.assertEqual(rich["technical_rsi14"], 55.0)
        self.assertEqual(rich[f"technical_rsi14{MISSING_SUFFIX}"], 0.0)

    def test_macro_series_outside_the_allowlist_never_becomes_a_column(self):
        rich = FeatureLayer().build(self._rich()).snapshot.features
        self.assertEqual(rich["macro_vix"], 18.0)
        self.assertNotIn("macro_dgs10", rich)

    def test_twenty_day_return_is_computed_with_the_context_bar_budget(self):
        """ContextBuilder가 넘기는 봉 수로 20일 수익률이 실제로 나와야 한다."""
        features = FeatureLayer().build(self._sparse()).snapshot.features
        self.assertIsNotNone(features["price_return_20d"])
        self.assertEqual(features[f"price_return_20d{MISSING_SUFFIX}"], 0.0)

    def test_one_bar_short_leaves_the_twenty_day_return_missing(self):
        bundle = _bundle("CCC", [_item(1, "market", {"latest_bars": _bars(REQUIRED_BARS - 1)})])
        features = FeatureLayer().build(bundle).snapshot.features
        self.assertIsNone(features["price_return_20d"])
        self.assertEqual(features[f"price_return_20d{MISSING_SUFFIX}"], 1.0)


class ValuationFeatureTest(unittest.TestCase):
    """밸류에이션은 EvidenceBundle이 아니라 PIT 원장에서 오므로 따로 검사한다."""

    def _observation(self, **overrides) -> dict:
        payload = {
            "available_at": _AVAILABLE, "market_cap": 50000.0,
            "pe_ttm": 12.5, "pb": 3.0, "ps_ttm": 2.0, "fcf_yield": 0.05,
        }
        payload.update(overrides)
        return payload

    def _build(self, valuation):
        bundle = _bundle("AAA", [_item(1, "market", {"latest_bars": _bars(REQUIRED_BARS)})])
        return FeatureLayer().build(bundle, valuation=valuation).snapshot.features

    def test_ratios_and_log_size_become_features(self):
        features = self._build(self._observation())
        self.assertEqual(features["valuation_pe_ttm"], 12.5)
        self.assertEqual(features["valuation_pb"], 3.0)
        self.assertAlmostEqual(features["valuation_market_cap_log"], math.log(50000.0))
        self.assertEqual(features[f"valuation_pe_ttm{MISSING_SUFFIX}"], 0.0)

    def test_no_observation_leaves_the_columns_missing_not_zero(self):
        features = self._build(None)
        self.assertIsNone(features["valuation_pe_ttm"])
        self.assertEqual(features[f"valuation_pe_ttm{MISSING_SUFFIX}"], 1.0)
        self.assertEqual(set(features), set(FEATURE_COLUMNS))

    def test_observation_available_after_as_of_is_discarded(self):
        features = self._build(self._observation(available_at="2026-08-21T02:00:00+00:00"))
        for name in ("valuation_pe_ttm", "valuation_pb", "valuation_market_cap_log"):
            self.assertIsNone(features[name], name)
            self.assertEqual(features[f"{name}{MISSING_SUFFIX}"], 1.0)

    def test_loss_making_company_keeps_pe_missing_and_others_known(self):
        """적자로 PER이 N/M인 종목도 PBR·규모는 그대로 쓴다."""
        features = self._build(self._observation(pe_ttm=None, fcf_yield=None))
        self.assertIsNone(features["valuation_pe_ttm"])
        self.assertEqual(features[f"valuation_pe_ttm{MISSING_SUFFIX}"], 1.0)
        self.assertEqual(features["valuation_pb"], 3.0)
        self.assertEqual(features[f"valuation_pb{MISSING_SUFFIX}"], 0.0)

    def test_nonpositive_market_cap_does_not_produce_a_log(self):
        features = self._build(self._observation(market_cap=0.0))
        self.assertIsNone(features["valuation_market_cap_log"])


class ImputationTest(unittest.TestCase):
    def test_cross_section_median_fills_missing_and_keeps_the_flag(self):
        known = FeatureLayer().build(_bundle("AAA", [
            _item(1, "market", {"latest_bars": _bars(REQUIRED_BARS)}),
            _item(2, "technical", {"rsi14": 40.0, "macd": 1.0, "macd_signal": 0.5}),
        ])).snapshot
        other = FeatureLayer().build(_bundle("BBB", [
            _item(1, "market", {"latest_bars": _bars(REQUIRED_BARS)}),
            _item(2, "technical", {"rsi14": 60.0, "macd": 1.0, "macd_signal": 0.5}),
        ])).snapshot
        missing = FeatureLayer().build(_bundle("CCC", [
            _item(1, "market", {"latest_bars": _bars(REQUIRED_BARS)}),
        ])).snapshot
        rows = impute_cross_section([known, other, missing])
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[2]["technical_rsi14"], 50.0)
        self.assertEqual(rows[2][f"technical_rsi14{MISSING_SUFFIX}"], 1.0)
        self.assertEqual(rows[0][f"technical_rsi14{MISSING_SUFFIX}"], 0.0)

    def test_every_imputed_value_is_finite_for_model_input(self):
        snapshot = FeatureLayer().build(
            _bundle("AAA", [_item(1, "market", {"latest_bars": _bars(REQUIRED_BARS)})])
        ).snapshot
        rows = impute_cross_section([snapshot])
        self.assertEqual(set(rows[0]), set(FEATURE_COLUMNS))
        for name, value in rows[0].items():
            self.assertIsInstance(value, float, name)

    def test_column_missing_across_the_whole_cross_section_uses_the_fallback(self):
        snapshot = FeatureLayer().build(
            _bundle("AAA", [_item(1, "market", {"latest_bars": _bars(REQUIRED_BARS)})])
        ).snapshot
        rows = impute_cross_section([snapshot], fallback=-1.0)
        self.assertEqual(rows[0]["technical_rsi14"], -1.0)
        self.assertEqual(rows[0][f"technical_rsi14{MISSING_SUFFIX}"], 1.0)


class _FeatureRepository:
    """ContextBuilder가 요구하는 조회만 최소로 흉내낸다."""

    def __init__(self, tickers: list[str]):
        self.tickers = tickers
        self.saved: list[dict] = []

    def current_tracked_tickers(self):
        return list(self.tickers)

    def market_prices(self, ticker, as_of_at, limit=260):
        return [
            {"ticker": ticker, "trade_date": row["trade_date"], "close": row["close"],
             "ingested_at": "2026-08-20T21:30:00+00:00"}
            for row in _bars(min(limit, REQUIRED_BARS))
        ]

    def technical_snapshot(self, ticker, as_of_at):
        return []

    def fundamentals(self, ticker, as_of_at, limit=12):
        return []

    def fundamentals_pit(self, ticker, as_of_at, limit=12):
        return []

    def estimates(self, ticker, as_of_at, limit=12):
        return {"consensus": [], "analysts": []}

    def macro_snapshot(self, as_of_at):
        return {"run": {"finished_at": "2026-08-20T21:00:00+00:00"}, "observations": []}

    def segment_snapshot(self, ticker, as_of_at):
        return {"filings": [], "metrics": []}

    def guru_snapshot(self, ticker, as_of_at):
        return {"filings": [], "positions": []}

    def econ_snapshot(self, as_of_at, lookback_days=14):
        return {"results": [], "forecasts": []}

    def save_rl_feature_snapshots(self, rows):
        self.saved.extend(rows)


class BuildFeaturesEntryTest(unittest.TestCase):
    def test_every_saved_row_shares_the_same_feature_columns(self):
        repository = _FeatureRepository(["AAA", "BBB"])
        payload = build_features(
            as_of_at=parse_datetime(_AS_OF),
            tickers=["AAA", "BBB"],
            repository=repository,
        )
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["rows_upserted"], 2)
        self.assertEqual(len(repository.saved), 2)
        column_sets = {frozenset(row["features"]) for row in repository.saved}
        self.assertEqual(len(column_sets), 1)
        self.assertEqual(column_sets.pop(), frozenset(FEATURE_COLUMNS))

    def test_dry_run_writes_nothing(self):
        repository = _FeatureRepository(["AAA"])
        payload = build_features(
            as_of_at=parse_datetime(_AS_OF), tickers=["AAA"],
            dry_run=True, repository=repository,
        )
        self.assertEqual(repository.saved, [])
        self.assertEqual(payload["rows_upserted"], 0)
        self.assertTrue(payload["detail"]["dry_run"])

    def test_one_failing_ticker_does_not_stop_the_run(self):
        repository = _FeatureRepository(["AAA", "BAD"])
        original = repository.market_prices

        def _market_prices(ticker, as_of_at, limit=260):
            if ticker == "BAD":
                raise RuntimeError("upstream unavailable")
            return original(ticker, as_of_at, limit)

        repository.market_prices = _market_prices
        payload = build_features(
            as_of_at=parse_datetime(_AS_OF), tickers=["AAA", "BAD"], repository=repository,
        )
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["rows_upserted"], 1)
        self.assertEqual(payload["detail"]["failed"], ["BAD"])


class _LabelRepository:
    """label 생산 경로가 쓰는 조회만 흉내낸다."""

    def __init__(self, *, forward_days: int):
        self.forward_days = forward_days
        self.saved: list[dict] = []

    def current_tracked_tickers(self):
        return ["AAA"]

    def rl_feature_snapshot_rows(self, symbols, *, start_as_of, end_as_of, feature_version):
        return [{
            "feature_version": feature_version,
            "as_of_at": _AS_OF,
            "ticker": "AAA",
        }]

    def rl_training_label_rows(self, symbols, *, start_as_of, end_as_of, feature_version, label_cutoff_at):
        return []

    def market_prices(self, ticker, as_of_at, limit=260):
        return [{"ticker": ticker, "trade_date": "2026-08-20", "close": 100.0,
                 "ingested_at": "2026-08-20T21:30:00+00:00"}]

    def forward_prices_for_labels(self, ticker, *, after_date, limit=40):
        return [
            {"ticker": ticker, "trade_date": f"2026-08-{20 + offset:02d}",
             "close": 100.0 + offset,
             "ingested_at": f"2026-08-{20 + offset:02d}T21:30:00+00:00"}
            for offset in range(1, self.forward_days + 1)
        ]

    def save_rl_training_labels(self, rows):
        self.saved.extend(rows)


class BuildLabelsEntryTest(unittest.TestCase):
    def _run(self, repository, horizon=5):
        return build_labels(
            as_of_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
            horizon_days=horizon,
            lookback_days=90,
            repository=repository,
        )

    def test_open_forward_window_is_left_pending_and_never_saved(self):
        repository = _LabelRepository(forward_days=3)
        payload = self._run(repository, horizon=5)
        self.assertEqual(repository.saved, [])
        self.assertEqual(payload["detail"]["pending_window_open"], 1)
        self.assertEqual(payload["detail"]["built"], 0)

    def test_closed_window_produces_a_label_available_after_the_window_end(self):
        repository = _LabelRepository(forward_days=8)
        payload = self._run(repository, horizon=5)
        self.assertEqual(payload["detail"]["built"], 1)
        self.assertEqual(len(repository.saved), 1)
        row = repository.saved[0]
        self.assertEqual(row["feature_version"], FEATURE_VERSION)
        self.assertGreaterEqual(
            parse_datetime(row["label_available_at"]),
            parse_datetime(row["forward_end_at"]),
        )
        self.assertGreater(parse_datetime(row["forward_end_at"]), parse_datetime(row["as_of_at"]))

    def test_label_carries_no_feature_value(self):
        repository = _LabelRepository(forward_days=8)
        self._run(repository, horizon=5)
        stored = set(repository.saved[0])
        self.assertFalse(stored & set(OPTIONAL_FEATURES))


if __name__ == "__main__":
    unittest.main()
