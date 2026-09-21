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


class _ResearchStore:
    def __init__(self, owner=None):
        self.owner = owner
        self.saved: list = []
        self.save_calls = 0
        self.sample_runs: dict[str, dict] = {}
        self.full_feature_reads: list[tuple[str, ...] | None] = []
        self.full_label_reads: list[tuple[str, ...] | None] = []
        self.feature_symbols: list[tuple[str, ...]] = []
        self.label_symbols: list[tuple[str, ...]] = []

    def rl_feature_snapshot_rows(self, symbols, *, as_of_values=None, **_kwargs):
        self.full_feature_reads.append(None if as_of_values is None else tuple(as_of_values))
        self.feature_symbols.append(tuple(symbols))
        rows = [{
            "as_of_at": self.owner._as_of(index).isoformat(),
            "ticker": ticker,
            "available_at": (self.owner._as_of(index) - timedelta(hours=1)).isoformat(),
            "is_available": True,
            "features": _features(0.1 * (index + position)),
            "source_ids": [f"EV-{ticker}-{index}"],
            "provenance": {"definition_hash": "abc", "source_kind": "live_shadow"},
            "input_hash": f"input-{index}-{ticker}-{'changed' if index in self.owner.changed_input_periods else 'base'}",
        } for index in range(self.owner.periods) for position, ticker in enumerate(_TICKERS)]
        return rows if as_of_values is None else [
            row for row in rows if row["as_of_at"] in as_of_values
        ]

    def rl_training_label_rows(self, symbols, *, as_of_values=None, **_kwargs):
        self.full_label_reads.append(None if as_of_values is None else tuple(as_of_values))
        self.label_symbols.append(tuple(symbols))
        rows = []
        for index in range(self.owner.periods):
            end = self.owner._as_of(index) + timedelta(days=5)
            for position, ticker in enumerate(_TICKERS):
                rows.append({
                    "as_of_at": self.owner._as_of(index).isoformat(),
                    "ticker": ticker,
                    "forward_end_at": end.isoformat(),
                    "label_available_at": end.isoformat(),
                    "forward_return": self.owner.gross_returns[position],
                    "benchmark_forward_return": 0.0,
                    "label_id": f"rl_label_{index}{position:023d}"[:33],
                })
        return rows if as_of_values is None else [
            row for row in rows if row["as_of_at"] in as_of_values
        ]

    def save_training_samples(self, samples):
        self.save_calls += 1
        self.saved.extend(samples)

    def training_sample_run_rows(self, **_kwargs):
        return list(self.sample_runs.values())

    def save_training_sample_runs(self, rows):
        for row in rows:
            self.sample_runs[row["record_key"]] = dict(row)
        return len(rows)


class _Repository:
    def __init__(self, *, gross_returns=(0.03, 0.001), periods: int = 3):
        self.gross_returns = gross_returns
        self.periods = periods
        self.store = _ResearchStore(self)
        self.changed_input_periods: set[int] = set()

    def current_tracked_tickers(self):
        return list(_TICKERS)

    def _as_of(self, index: int) -> datetime:
        return _START + timedelta(days=7 * index)

class BuildTrainingSamplesTest(unittest.TestCase):
    def _run(self, repository, **kwargs):
        repository.store.owner = repository
        return build_training_samples(
            as_of_at=_START + timedelta(days=60),
            lookback_days=365,
            repository=repository,
            store=repository.store,
            **kwargs,
        )

    def test_every_labeled_pair_becomes_one_sample(self):
        repository = _Repository(periods=3)
        payload = self._run(repository)
        self.assertEqual(payload["detail"]["samples"], 6)
        self.assertEqual(len(repository.store.saved), 6)
        self.assertEqual(repository.store.saved[0].label_definition, LABEL_DEFINITION)

    def test_all_samples_are_persisted_in_one_repository_write(self):
        repository = _Repository(periods=60)
        payload = self._run(repository)
        self.assertEqual(payload["detail"]["samples"], 120)
        self.assertEqual(repository.store.save_calls, 1)
        self.assertEqual(set(payload["detail"]["timings_sec"]), {"load", "compute", "write"})

    def test_reported_upserts_exclude_samples_already_in_the_store(self):
        class AlreadyStoredStore(_ResearchStore):
            def save_training_samples(self, samples):
                super().save_training_samples(samples)
                return 0

        repository = _Repository(periods=3)
        repository.store = AlreadyStoredStore()
        payload = self._run(repository)
        self.assertEqual(payload["detail"]["samples"], 6)
        self.assertEqual(payload["rows_upserted"], 0)

    def test_complete_periods_are_skipped_but_new_periods_are_computed(self):
        repository = _Repository(periods=2)
        first = self._run(repository)
        second = self._run(repository)
        repository.periods = 3
        third = self._run(repository)
        changed_cost = self._run(
            repository, cost_model=TransactionCostModel(commission_rate=0.0001),
        )

        self.assertEqual(first["detail"]["samples"], 4)
        self.assertEqual(second["detail"]["samples"], 0)
        self.assertEqual(second["rows_upserted"], 0)
        self.assertEqual(second["detail"]["already_sampled"], 4)
        self.assertEqual(third["detail"]["samples"], 2)
        self.assertEqual(third["detail"]["already_sampled"], 4)
        self.assertEqual(changed_cost["detail"]["samples"], 6)
        self.assertEqual(changed_cost["detail"]["already_sampled"], 0)
        self.assertEqual(repository.store.save_calls, 3)
        self.assertEqual(len(repository.store.sample_runs), 3)

    def test_changed_feature_input_invalidates_only_its_period(self):
        repository = _Repository(periods=3)
        self._run(repository)
        repository.changed_input_periods.add(1)

        changed = self._run(repository)

        self.assertEqual(changed["detail"]["samples"], 2)
        self.assertEqual(changed["detail"]["already_sampled"], 4)

    def test_unchanged_manifest_avoids_full_feature_and_label_reads(self):
        class LightweightStore(_ResearchStore):
            def __init__(self, reader):
                super().__init__(reader)
                self.reader = reader
                self.metadata_calls = 0

            def training_sample_period_inputs(self, symbols, **kwargs):
                self.metadata_calls += 1
                snapshots = super().rl_feature_snapshot_rows(
                    symbols,
                    start_as_of=kwargs["start_as_of"], end_as_of=kwargs["end_as_of"],
                )
                labels = super().rl_training_label_rows(
                    symbols,
                    start_as_of=kwargs["start_as_of"], end_as_of=kwargs["end_as_of"],
                    label_cutoff_at=kwargs["label_cutoff_at"],
                )
                # metadata projection을 만드는 fixture 동작은 full payload read 계수에서 제외한다.
                self.full_feature_reads.pop()
                self.full_label_reads.pop()
                return {
                    "snapshots": [{
                        key: row[key] for key in ("as_of_at", "ticker", "input_hash")
                    } for row in snapshots],
                    "labels": [{
                        key: row[key] for key in ("as_of_at", "ticker", "label_id")
                    } for row in labels],
                }

        class LightweightRepository(_Repository):
            def __init__(self):
                super().__init__(periods=2)

            def training_sample_period_inputs(self, symbols, **kwargs):
                raise AssertionError("metadata must be read from the Research store")

        repository = LightweightRepository()
        repository.store = LightweightStore(repository)
        self._run(repository)
        repository.store.full_feature_reads.clear()
        repository.store.full_label_reads.clear()

        repeated = self._run(repository)

        self.assertEqual(repeated["detail"]["samples"], 0)
        self.assertEqual(repeated["detail"]["already_sampled"], 4)
        self.assertEqual(repository.store.full_feature_reads, [])
        self.assertEqual(repository.store.full_label_reads, [])
        self.assertEqual(repository.store.metadata_calls, 2)

    def test_window_includes_former_members_not_only_current_tracked_names(self):
        """과거 편출 종목 BBB를 조회 범위에서 빼면 학습 표본이 조용히 사라진다."""
        class FormerMemberRepository(_Repository):
            def current_tracked_tickers(self):
                return ["AAA"]

            def historical_sp500_membership(self, *, start_date, end_date):
                return [{"symbols": ["AAA", "BBB"]}]

        repository = FormerMemberRepository(periods=1)
        payload = self._run(repository)
        self.assertIn("BBB", repository.store.feature_symbols[0])
        self.assertIn("BBB", repository.store.label_symbols[0])
        self.assertEqual(payload["detail"]["samples"], 2)

    def test_sample_carries_both_gross_and_net_labels(self):
        repository = _Repository()
        self._run(repository)
        labels = repository.store.saved[0].labels
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
        for sample in repository.store.saved:
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
        repository.store.rl_training_label_rows = lambda *a, **k: []
        payload = self._run(repository)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["detail"]["samples"], 0)
        self.assertEqual(payload["detail"]["reason"], "no_confirmed_label_yet")
        self.assertEqual(repository.store.saved, [])

    def test_dry_run_writes_nothing(self):
        repository = _Repository()
        payload = self._run(repository, dry_run=True)
        self.assertEqual(repository.store.saved, [])
        self.assertEqual(repository.store.sample_runs, {})
        self.assertEqual(payload["rows_upserted"], 0)

    def test_sample_write_failure_does_not_record_completion_manifest(self):
        class FailingStore(_ResearchStore):
            def save_training_samples(self, samples):
                raise RuntimeError("sample writer unavailable")

        repository = _Repository()
        repository.store = FailingStore()
        with self.assertRaisesRegex(RuntimeError, "sample writer unavailable"):
            self._run(repository)
        self.assertEqual(repository.store.sample_runs, {})

    def test_completion_manifest_follows_the_sample_batch_write(self):
        calls: list[str] = []

        class OrderedStore(_ResearchStore):
            def save_training_samples(self, samples):
                calls.append("samples")
                return super().save_training_samples(samples)

            def save_training_sample_runs(self, rows):
                calls.append("runs")
                return super().save_training_sample_runs(rows)

        repository = _Repository()
        repository.store = OrderedStore()
        self._run(repository)
        self.assertEqual(calls, ["samples", "runs"])


if __name__ == "__main__":
    unittest.main()
