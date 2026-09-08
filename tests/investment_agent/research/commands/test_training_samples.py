"""비용 반영 학습 표본이 gross label을 그대로 베끼지 않는지 고정한다."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.research.evaluation.costs import TransactionCostModel
from investment_agent.trading.contracts import ContractError
from investment_agent.research.commands.build_training_samples import (
    LABEL_DEFINITION,
    build_training_samples,
)
from investment_agent.research.features.layer import (
    ALWAYS_KNOWN_FEATURES,
    FEATURE_VERSION,
    MISSING_SUFFIX,
    OPTIONAL_FEATURES,
)
from investment_agent.research.evaluation.shadow_fill import round_trip_cost_rate, simulate_shadow_trade

_START = datetime(2026, 4, 1, 22, tzinfo=timezone.utc)
_TICKERS = ("AAA", "BBB")


class ShadowFillTest(unittest.TestCase):
    def _trade(self, gross: float, benchmark: float = 0.0, **kwargs):
        return simulate_shadow_trade(
            ticker="AAA", entry_at=_START.isoformat(),
            exit_at=(_START + timedelta(days=7)).isoformat(),
            entry_price=100.0, exit_price=100.0 * (1.0 + gross),
            benchmark_return=benchmark, **kwargs,
        )

    def test_cost_drag_grows_with_the_exit_price(self):
        """매도 수수료·슬리피지는 매도 시점 금액에 붙으므로 많이 오를수록 더 낸다."""
        up = self._trade(0.05).cost_drag
        flat = self._trade(0.0).cost_drag
        down = self._trade(-0.05).cost_drag
        self.assertGreater(up, flat)
        self.assertGreater(flat, down)

    def test_cost_drag_stays_near_the_round_trip_rate(self):
        """수익률이 흔들려도 비용은 왕복 요율 근처에 머문다 — 예산을 잡을 수 있다."""
        rate = round_trip_cost_rate()
        for gross in (0.05, 0.0, -0.05):
            self.assertAlmostEqual(self._trade(gross).cost_drag, rate, delta=rate * 0.10)

    def test_net_return_is_always_below_gross(self):
        for gross in (0.05, 0.0, -0.05):
            result = self._trade(gross)
            self.assertLess(result.net_return, result.gross_return)

    def test_small_positive_move_becomes_a_loss_after_costs(self):
        """이게 gross label로 학습하면 안 되는 이유다."""
        result = self._trade(0.001)
        self.assertGreater(result.gross_return, 0)
        self.assertLess(result.net_return, 0)

    def test_benchmark_is_not_charged_turnover_costs(self):
        result = self._trade(0.02, benchmark=0.01)
        self.assertEqual(result.benchmark_return, 0.01)
        self.assertAlmostEqual(
            result.gross_excess_return - result.net_excess_return, result.cost_drag,
        )

    def test_outcome_reconciles_gross_fees_and_slippage(self):
        outcome = self._trade(0.03).outcome
        self.assertAlmostEqual(
            outcome.net_pnl,
            outcome.gross_pnl - outcome.fees - outcome.execution_slippage,
        )
        self.assertEqual(outcome.metadata["source"], "shadow_simulation")

    def test_a_cheaper_broker_produces_a_smaller_drag(self):
        cheap = TransactionCostModel(commission_rate=0.0001, slippage_bps=1.0)
        self.assertLess(round_trip_cost_rate(cheap), round_trip_cost_rate())

    def test_zero_or_negative_price_is_refused(self):
        with self.assertRaises(ContractError):
            self._trade(-1.0)  # exit_price == 0


def _features(seed: float) -> dict:
    values = {name: 1.0 for name in ALWAYS_KNOWN_FEATURES}
    for name in OPTIONAL_FEATURES:
        values[name] = seed
        values[f"{name}{MISSING_SUFFIX}"] = 0.0
    return values


class _Repository:
    def __init__(self, *, gross_returns=(0.03, 0.001), periods: int = 3):
        self.gross_returns = gross_returns
        self.periods = periods
        self.saved: list = []

    def current_tracked_tickers(self):
        return list(_TICKERS)

    def _as_of(self, index: int) -> datetime:
        return _START + timedelta(days=7 * index)

    def rl_feature_snapshot_rows(self, symbols, *, start_as_of, end_as_of, feature_version):
        return [{
            "feature_version": feature_version,
            "as_of_at": self._as_of(index).isoformat(),
            "ticker": ticker,
            "available_at": (self._as_of(index) - timedelta(hours=1)).isoformat(),
            "is_available": True,
            "features": _features(0.1 * (index + position)),
            "source_ids": [f"EV-{ticker}-{index}"],
            "provenance": {"definition_hash": "abc", "source_kind": "live_shadow"},
        } for index in range(self.periods) for position, ticker in enumerate(_TICKERS)]

    def rl_training_label_rows(self, symbols, *, start_as_of, end_as_of, feature_version, label_cutoff_at):
        rows = []
        for index in range(self.periods):
            end = self._as_of(index) + timedelta(days=5)
            for position, ticker in enumerate(_TICKERS):
                rows.append({
                    "feature_version": feature_version,
                    "as_of_at": self._as_of(index).isoformat(),
                    "ticker": ticker,
                    "forward_end_at": end.isoformat(),
                    "label_available_at": end.isoformat(),
                    "forward_return": self.gross_returns[position],
                    "benchmark_forward_return": 0.0,
                    "label_id": f"rl_label_{index}{position:023d}"[:33],
                })
        return rows

    def save_training_samples(self, samples):
        self.saved.extend(samples)


class BuildTrainingSamplesTest(unittest.TestCase):
    def _run(self, repository, **kwargs):
        return build_training_samples(
            as_of_at=_START + timedelta(days=60),
            lookback_days=365,
            repository=repository,
            **kwargs,
        )

    def test_every_labeled_pair_becomes_one_sample(self):
        repository = _Repository(periods=3)
        payload = self._run(repository)
        self.assertEqual(payload["detail"]["samples"], 6)
        self.assertEqual(len(repository.saved), 6)
        self.assertEqual(repository.saved[0].label_definition, LABEL_DEFINITION)
        self.assertEqual(repository.saved[0].feature_version, FEATURE_VERSION)

    def test_sample_carries_both_gross_and_net_labels(self):
        repository = _Repository()
        self._run(repository)
        labels = repository.saved[0].labels
        for name in ("gross_return", "net_return", "cost_drag",
                     "gross_excess_return", "net_excess_return", "benchmark_return"):
            self.assertIn(name, labels)
        self.assertLess(labels["net_excess_return"], labels["gross_excess_return"])

    def test_cost_flipping_the_sign_is_counted_and_reported(self):
        """+0.1% 판단은 비용 후 손실이다. 그 개수가 보고돼야 한다."""
        repository = _Repository(gross_returns=(0.03, 0.001), periods=2)
        payload = self._run(repository)
        # BBB(+0.1%)만 뒤집힌다: 2개 시점 x 1종목
        self.assertEqual(payload["detail"]["sign_flipped_by_cost"], 2)
        self.assertLess(payload["detail"]["mean_net_excess"], payload["detail"]["mean_gross_excess"])

    def test_every_sample_links_to_a_reproducible_outcome(self):
        repository = _Repository()
        self._run(repository)
        for sample in repository.saved:
            self.assertTrue(sample.outcome_id.startswith("outcome_"))
            self.assertEqual(sample.provenance["source"], "shadow_simulation")
            self.assertIn("cost_model", sample.provenance)

    def test_minimum_commission_is_refused_for_shadow_samples(self):
        """최소 수수료가 있으면 비율이 주문 금액에 따라 달라져 계산할 수 없다."""
        with self.assertRaises(ContractError):
            self._run(_Repository(), cost_model=TransactionCostModel(minimum_commission=1.0))

    def test_no_label_yet_is_a_quiet_success_not_a_failure(self):
        """적재 첫 며칠은 horizon이 안 지나 label이 0건이다.

        여기서 실패시키면 5거래일 내내 job이 실패로 뜨고, 그 사이 정상 적재된
        feature까지 문제로 보인다. 실제 하네스 첫 가동에서 이 경로로 죽었다.
        """
        repository = _Repository()
        repository.rl_training_label_rows = lambda *a, **k: []
        payload = self._run(repository)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["detail"]["samples"], 0)
        self.assertEqual(payload["detail"]["reason"], "no_confirmed_label_yet")
        self.assertEqual(repository.saved, [])

    def test_dry_run_writes_nothing(self):
        repository = _Repository()
        payload = self._run(repository, dry_run=True)
        self.assertEqual(repository.saved, [])
        self.assertEqual(payload["rows_upserted"], 0)


if __name__ == "__main__":
    unittest.main()
