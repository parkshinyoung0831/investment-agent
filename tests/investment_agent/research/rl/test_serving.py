"""승격된 RL 정책을 판단 시점에 불러 목표비중을 만드는 배선.

이 배선이 없어서 `blend()`가 RL 목표비중 없이 불렸고, 그러면 RL 신호가 LLM 신호로
대체되어 융합이 아무것도 바꾸지 못했다(`test_signal_blender.py` 참고).

여기서 못박는 것은 두 가지다.

1. **기본은 꺼져 있다.** 플래그가 없으면 목표비중을 만들어도 판단에 반영하지 않는다.
2. **꺼져 있어도 비교는 남긴다.** 켰다면 무엇이 얼마나 달라졌을지를 계산해 둔다.
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from investment_agent.research.rl import serving
from investment_agent.trading.decision.signal_blender import SignalBlender
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


class BlendFlagTest(unittest.TestCase):
    def test_flag_is_off_unless_explicitly_set(self) -> None:
        self.assertFalse(serving.blend_enabled({}))
        self.assertFalse(serving.blend_enabled({serving.BLEND_FLAG: ""}))
        # 오타·모르는 값은 꺼진 것으로 읽는다.
        self.assertFalse(serving.blend_enabled({serving.BLEND_FLAG: "ture"}))
        self.assertFalse(serving.blend_enabled({serving.BLEND_FLAG: "0"}))
        for value in ("1", "true", "TRUE", "yes", "on", " On "):
            with self.subTest(value=value):
                self.assertTrue(serving.blend_enabled({serving.BLEND_FLAG: value}))


class ComputeRlBlendTest(unittest.TestCase):
    def _policy_file(self, directory: str) -> Path:
        path = Path(directory) / "active_baseline_policy.json"
        save_baseline_policy(_model(), path)
        return path

    def test_missing_artifact_is_not_an_error(self) -> None:
        outcome = serving.compute_rl_blend(
            _Repository(), as_of_at=NOW, policy_path=Path("does/not/exist.json"), enabled=True
        )
        self.assertFalse(outcome.available)
        self.assertFalse(outcome.applied)
        self.assertIn("no promoted RL policy", outcome.reason or "")
        self.assertEqual({}, outcome.weights)

    def test_weights_are_produced_but_not_applied_while_the_flag_is_off(self) -> None:
        with TemporaryDirectory() as directory:
            outcome = serving.compute_rl_blend(
                _Repository(), as_of_at=NOW, policy_path=self._policy_file(directory), enabled=False
            )
        self.assertTrue(outcome.available)
        self.assertFalse(outcome.applied)
        self.assertIn(serving.BLEND_FLAG, outcome.reason or "")
        self.assertEqual(set(SYMBOLS), set(outcome.weights))
        # 현금은 목표비중에서 빠진다 — blend()는 종목 비중만 본다.
        self.assertNotIn("CASH", outcome.weights)
        # 계수가 큰 쪽에 더 큰 비중이 간다.
        self.assertGreater(outcome.weights["AAPL"], outcome.weights["MSFT"])

    def test_enabled_flag_marks_the_outcome_as_applied(self) -> None:
        with TemporaryDirectory() as directory:
            outcome = serving.compute_rl_blend(
                _Repository(), as_of_at=NOW, policy_path=self._policy_file(directory), enabled=True
            )
        self.assertTrue(outcome.applied)
        self.assertIsNone(outcome.reason)
        self.assertEqual(_model().artifact_id, outcome.policy_artifact_id)
        self.assertEqual(64, len(outcome.inference_input_hash or ""))

    def test_empty_or_failing_feature_store_degrades_instead_of_raising(self) -> None:
        with TemporaryDirectory() as directory:
            path = self._policy_file(directory)
            empty = serving.compute_rl_blend(
                _Repository(rows=[]), as_of_at=NOW, policy_path=path, enabled=True
            )
            broken = serving.compute_rl_blend(
                _Repository(error=RuntimeError("supabase down")),
                as_of_at=NOW,
                policy_path=path,
                enabled=True,
            )
        for outcome in (empty, broken):
            self.assertFalse(outcome.available)
            self.assertFalse(outcome.applied)
            self.assertTrue(outcome.reason)

    def test_stale_snapshots_are_not_used_for_live_inference(self) -> None:
        """하루보다 오래된 snapshot은 마스킹되어 비중이 현금으로 간다."""
        stale = _snapshot_rows(NOW - timedelta(days=5))
        with TemporaryDirectory() as directory:
            outcome = serving.compute_rl_blend(
                _Repository(rows=stale),
                as_of_at=NOW,
                policy_path=self._policy_file(directory),
                enabled=True,
                lookback_days=10,
            )
        self.assertTrue(outcome.available)
        self.assertEqual([0.0, 0.0], [outcome.weights[s] for s in SYMBOLS])


class ComparisonRecordTest(unittest.TestCase):
    def test_comparison_reports_what_turning_it_on_would_change(self) -> None:
        outcome = serving.with_comparison(
            serving.unavailable("test"),
            baseline={"AAPL": 0.05, "MSFT": 0.04},
            blended={"AAPL": 0.07, "MSFT": 0.04},
        )
        self.assertEqual(("AAPL",), outcome.changed_symbols)
        self.assertAlmostEqual(0.02, outcome.max_abs_delta)

    def test_identical_sides_report_no_change(self) -> None:
        outcome = serving.with_comparison(
            serving.unavailable("test"),
            baseline={"AAPL": 0.05},
            blended={"AAPL": 0.05},
        )
        self.assertEqual((), outcome.changed_symbols)
        self.assertEqual(0.0, outcome.max_abs_delta)

    def test_log_payload_carries_counts_not_raw_weights(self) -> None:
        payload = serving.with_comparison(
            serving.unavailable("no policy"),
            baseline={"AAPL": 0.05},
            blended={"AAPL": 0.06},
        ).log_payload()
        self.assertEqual(1, payload["changed_symbols"])
        self.assertEqual(1, payload["compared_symbols"])
        self.assertNotIn("weights", payload)


@dataclass(frozen=True)
class _Proposal:
    """`expected_return_5d`/`confidence`만 쓰는 최소 제안."""

    ticker: str
    expected_return_5d: float
    confidence: float


class BlendProposalsTest(unittest.TestCase):
    """플래그가 꺼져 있으면 제안이 배선 이전과 완전히 같아야 한다."""

    PROPOSALS = (
        _Proposal("AAPL", 0.05, 0.80),
        _Proposal("MSFT", 0.02, 0.70),
    )

    def _blend_outcome(self, *, applied: bool) -> serving.RlBlendOutcome:
        return serving.RlBlendOutcome(
            available=True,
            applied=applied,
            weights={"AAPL": 0.60, "MSFT": 0.10},
        )

    def test_flag_off_leaves_proposals_exactly_as_they_were(self) -> None:
        blender = SignalBlender(base_rl_weight=0.25, max_rl_weight=0.50)
        updated, outcome = serving.blend_proposals(
            self.PROPOSALS,
            blender=blender,
            dsr_probability=0.95,
            outcome=self._blend_outcome(applied=False),
        )
        # 배선이 없던 때의 동작: 목표비중 없이 blend -> 입력과 같은 값.
        for before, after in zip(self.PROPOSALS, updated, strict=True):
            self.assertAlmostEqual(before.expected_return_5d, after.expected_return_5d)
            self.assertAlmostEqual(before.confidence, after.confidence)
        # 그래도 켰다면 달라졌을 것이라는 사실은 기록된다.
        self.assertTrue(outcome.changed_symbols)
        self.assertGreater(outcome.max_abs_delta, 0.0)

    def test_flag_on_actually_moves_the_expected_returns(self) -> None:
        blender = SignalBlender(base_rl_weight=0.25, max_rl_weight=0.50)
        updated, outcome = serving.blend_proposals(
            self.PROPOSALS,
            blender=blender,
            dsr_probability=0.95,
            outcome=self._blend_outcome(applied=True),
        )
        changed = [
            after.expected_return_5d
            for before, after in zip(self.PROPOSALS, updated, strict=True)
            if abs(after.expected_return_5d - before.expected_return_5d) > 1e-12
        ]
        self.assertTrue(changed, "융합을 켰는데 아무것도 바뀌지 않았다")
        # RL이 평균보다 낮게 준 MSFT는 아래로 내려간다. (AAPL은 이 표본에서 RL이 함의하는
        # 기대수익률이 LLM 값과 우연히 같아 움직이지 않는다 — 그래서 방향이 분명한 쪽으로 본다.)
        self.assertLess(updated[1].expected_return_5d, self.PROPOSALS[1].expected_return_5d)
        self.assertTrue(outcome.applied)

    def test_unavailable_policy_still_returns_todays_proposals(self) -> None:
        blender = SignalBlender(base_rl_weight=0.25, max_rl_weight=0.50)
        updated, outcome = serving.blend_proposals(
            self.PROPOSALS,
            blender=blender,
            dsr_probability=0.95,
            outcome=serving.unavailable("no policy"),
        )
        for before, after in zip(self.PROPOSALS, updated, strict=True):
            self.assertAlmostEqual(before.expected_return_5d, after.expected_return_5d)
        self.assertEqual((), outcome.changed_symbols)


class LiveMembershipTest(unittest.TestCase):
    def test_live_membership_refuses_historical_purposes(self) -> None:
        timeline = serving.live_membership(SYMBOLS, as_of_at=NOW.isoformat(), source_id="t")
        self.assertEqual(frozenset(SYMBOLS), timeline.members_at(NOW, purpose="live_inference"))
        with self.assertRaises(Exception):
            timeline.members_at(NOW, purpose="historical_training")


if __name__ == "__main__":
    unittest.main()
