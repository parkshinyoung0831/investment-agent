"""승격된 RL 정책을 판단 시점에 불러 challenger 목표비중을 만드는 배선.

못박는 것: 정책이 없거나 feature가 비어도 예외 없이 이유를 남기고, 오래된 snapshot으로
추론하지 않는다. 목표비중은 판단 신호에 섞이지 않는다(`test_effective_signals.py`).
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from investment_agent.research.rl import serving
from investment_agent.research.rl.baseline import (
    BaselinePolicyConfig,
    BaselinePolicyModel,
    save_baseline_policy,
)
from investment_agent.research.features.layer import FEATURE_COLUMNS, FEATURE_VERSION

SYMBOLS = ("AAPL", "MSFT")
NOW = datetime(2026, 9, 4, 21, 0, tzinfo=timezone.utc)


def _model() -> BaselinePolicyModel:
    """AAPL 쪽 계수를 크게 준 결정적 ridge 정책."""
    names = tuple(FEATURE_COLUMNS)
    return BaselinePolicyModel(
        feature_version=FEATURE_VERSION,
        feature_names=names,
        symbols=SYMBOLS,
        feature_means=tuple(0.0 for _ in names),
        feature_scales=tuple(1.0 for _ in names),
        coefficients=tuple(1.0 if index == 0 else 0.0 for index in range(len(names))),
        intercept=0.0,
        seed=7,
        train_start="2026-01-01T00:00:00+00:00",
        train_end="2026-08-01T00:00:00+00:00",
        training_data_hash="0" * 64,
        config=BaselinePolicyConfig(),
    )


class _Repository:
    """`rl_feature_snapshot_rows`만 흉내 내는 저장소. 네트워크·DB를 쓰지 않는다."""

    def __init__(self, rows: list[dict] | None = None, *, error: Exception | None = None) -> None:
        self._rows = rows if rows is not None else _snapshot_rows()
        self._error = error
        self.calls: list[tuple] = []

    def rl_feature_snapshot_rows(self, symbols, *, start_as_of, end_as_of, feature_version):
        self.calls.append((tuple(symbols), start_as_of, end_as_of, feature_version))
        if self._error is not None:
            raise self._error
        return self._rows


def _snapshot_rows(as_of: datetime = NOW - timedelta(hours=2)) -> list[dict]:
    rows = []
    for index, ticker in enumerate(SYMBOLS):
        features = {name: 0.0 for name in FEATURE_COLUMNS}
        features[FEATURE_COLUMNS[0]] = 1.0 if ticker == "AAPL" else -1.0
        rows.append(
            {
                "feature_version": FEATURE_VERSION,
                "as_of_at": as_of.isoformat(),
                "ticker": ticker,
                "available_at": as_of.isoformat(),
                "is_available": True,
                "features": features,
                "source_ids": (f"src-{index}",),
                "provenance": {"pipeline": "test"},
            }
        )
    return rows


class ComputeRlTargetWeightsTest(unittest.TestCase):
    def _policy_file(self, directory: str) -> Path:
        path = Path(directory) / "active_baseline_policy.json"
        save_baseline_policy(_model(), path)
        return path

    def test_missing_artifact_is_not_an_error(self) -> None:
        outcome = serving.compute_rl_target_weights(
            _Repository(), as_of_at=NOW, policy_path=Path("does/not/exist.json")
        )
        self.assertFalse(outcome.available)
        self.assertIn("no promoted RL policy", outcome.reason or "")
        self.assertEqual({}, outcome.weights)

    def test_weights_exclude_cash_and_follow_the_policy(self) -> None:
        with TemporaryDirectory() as directory:
            outcome = serving.compute_rl_target_weights(
                _Repository(), as_of_at=NOW, policy_path=self._policy_file(directory)
            )
        self.assertTrue(outcome.available)
        self.assertEqual(set(SYMBOLS), set(outcome.weights))
        # 현금은 목표비중에서 빠진다.
        self.assertNotIn("CASH", outcome.weights)
        # 계수가 큰 쪽에 더 큰 비중이 간다.
        self.assertGreater(outcome.weights["AAPL"], outcome.weights["MSFT"])

    def test_outcome_carries_reproducible_identity(self) -> None:
        with TemporaryDirectory() as directory:
            outcome = serving.compute_rl_target_weights(
                _Repository(), as_of_at=NOW, policy_path=self._policy_file(directory)
            )
        self.assertTrue(outcome.available)
        self.assertIsNone(outcome.reason)
        self.assertEqual(_model().artifact_id, outcome.policy_artifact_id)
        self.assertEqual(64, len(outcome.inference_input_hash or ""))

    def test_empty_or_failing_feature_store_degrades_instead_of_raising(self) -> None:
        with TemporaryDirectory() as directory:
            path = self._policy_file(directory)
            empty = serving.compute_rl_target_weights(
                _Repository(rows=[]), as_of_at=NOW, policy_path=path
            )
            broken = serving.compute_rl_target_weights(
                _Repository(error=RuntimeError("supabase down")),
                as_of_at=NOW,
                policy_path=path,
            )
        for outcome in (empty, broken):
            self.assertFalse(outcome.available)
            self.assertTrue(outcome.reason)

    def test_stale_snapshots_are_not_used_for_live_inference(self) -> None:
        """하루보다 오래된 snapshot은 마스킹되어 비중이 현금으로 간다."""
        stale = _snapshot_rows(NOW - timedelta(days=5))
        with TemporaryDirectory() as directory:
            outcome = serving.compute_rl_target_weights(
                _Repository(rows=stale),
                as_of_at=NOW,
                policy_path=self._policy_file(directory),
                lookback_days=10,
            )
        self.assertTrue(outcome.available)
        self.assertEqual([0.0, 0.0], [outcome.weights[s] for s in SYMBOLS])


class LiveMembershipTest(unittest.TestCase):
    def test_live_membership_refuses_historical_purposes(self) -> None:
        timeline = serving.live_membership(SYMBOLS, as_of_at=NOW.isoformat(), source_id="t")
        self.assertEqual(frozenset(SYMBOLS), timeline.members_at(NOW, purpose="live_inference"))
        with self.assertRaises(Exception):
            timeline.members_at(NOW, purpose="historical_training")


if __name__ == "__main__":
    unittest.main()
