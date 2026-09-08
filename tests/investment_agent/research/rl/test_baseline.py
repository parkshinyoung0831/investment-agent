from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from investment_agent.research.rl.baseline import (
    load_baseline_policy,
    save_baseline_policy,
    train_baseline_policy,
)
from investment_agent.research.rl.features import HistoricalTrainingSet, LiveInferenceFrame
from investment_agent.research.rl.environment import FeatureDataset
from tests.investment_agent.research.rl.fixtures import historical_training_set


class BaselinePolicyTest(unittest.TestCase):
    def test_training_is_deterministic_and_ignores_oos_mutation(self):
        _, training = historical_training_set(10)
        first = train_baseline_policy(training, train_range=(0, 5), seed=42)
        repeated = train_baseline_policy(training, train_range=(0, 5), seed=42)
        self.assertEqual(first.to_dict(), repeated.to_dict())

        features = training.dataset.features.copy()
        returns = training.dataset.forward_returns.copy()
        features[5:] = 999.0
        returns[5:] = -0.9
        changed_dataset = FeatureDataset(
            symbols=training.dataset.symbols,
            feature_names=training.dataset.feature_names,
            as_of_values=training.dataset.as_of_values,
            features=features,
            forward_returns=returns,
            benchmark_forward_returns=training.dataset.benchmark_forward_returns,
            availability=training.dataset.availability,
            feature_version=training.dataset.feature_version,
        )
        changed = HistoricalTrainingSet(
            dataset=changed_dataset,
            forward_end_values=training.forward_end_values,
            membership_hash=training.membership_hash,
            feature_snapshot_ids=training.feature_snapshot_ids,
            label_ids=training.label_ids,
            data_hash="f" * 64,
        )
        oos_changed = train_baseline_policy(changed, train_range=(0, 5), seed=42)
        self.assertEqual(first.to_dict(), oos_changed.to_dict())

    def test_json_artifact_round_trip_and_live_masked_inference(self):
        _, training = historical_training_set(10)
        model = train_baseline_policy(training, train_range=(0, 6), seed=7)
        frame = LiveInferenceFrame(
            symbols=model.symbols,
            feature_names=model.feature_names,
            feature_version=model.feature_version,
            as_of_at="2026-02-01T21:00:00+00:00",
            features=np.asarray([[0.9, 0.5], [-0.9, 0.5]]),
            availability=np.asarray([True, False]),
            membership_hash="a" * 64,
            input_hash="b" * 64,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            artifact = save_baseline_policy(model, path)
            loaded = load_baseline_policy(path, expected_sha256=artifact.sha256)
            self.assertEqual(model.to_dict(), loaded.to_dict())
            weights = loaded.predict_weights(frame)
            self.assertEqual(weights["MSFT"], 0.0)
            self.assertAlmostEqual(sum(weights.values()), 1.0)
            row = artifact.to_model_artifact_row(code_commit="abc123")
            self.assertEqual(row["algorithm"], "rule")
            self.assertEqual(row["artifact_id"], model.artifact_id)
            proposal = loaded.infer_proposal(frame, run_id="run-rl")
            self.assertFalse(proposal.metadata["execution_eligible"])
            self.assertEqual(proposal.metadata["coverage"], "partial_universe")

    def test_tampered_json_is_rejected_by_internal_content_hash(self):
        _, training = historical_training_set(8)
        model = train_baseline_policy(training, train_range=(0, 5), seed=1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            save_baseline_policy(model, path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["intercept"] += 1.0
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "content hash"):
                load_baseline_policy(path)


if __name__ == "__main__":
    unittest.main()
