"""PPO 산출물 무결성과 학습/추론 축을 검증한다."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from investment_agent.research.rl.bundle import save_policy_bundle, load_policy_bundle
from investment_agent.research.rl.pipeline import nonoverlapping_dataset
from tests.investment_agent.research.commands.test_continuous_retrain import _StubModel
from investment_agent.research.rl.environment import FeatureDataset

class BundleTest(unittest.TestCase):
    def dataset(self):
        return FeatureDataset(("AAPL",), ("x",), tuple(f"2026-01-{d:02}T00:00:00+00:00" for d in (1,2,6)), np.ones((3,1,1)), np.zeros((3,1)), np.zeros(3), np.ones((3,1), dtype=bool), "v1")

    def test_nonoverlap_removes_duplicate_market_intervals(self):
        result = nonoverlapping_dataset(self.dataset(), ("2026-01-06T00:00:00+00:00", "2026-01-07T00:00:00+00:00", "2026-01-11T00:00:00+00:00"))
        self.assertEqual(len(result.as_of_values), 2)
        self.assertEqual(result.as_of_values[1], self.dataset().as_of_values[2])

    def test_bundle_hash_is_verified_before_deserializing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=save_policy_bundle(_StubModel(1), Path(tmp), dataset=self.dataset(), score={"dsr_probability": .95}, training={"data_hash": "a"*64})
            import json
            metadata=json.loads(path.read_text())
            (path.parent / metadata["model_binary"]).write_bytes(b"corrupt")
            with self.assertRaises(ValueError):
                load_policy_bundle(path)

    def test_bundle_load_uses_exact_binary_and_axes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=save_policy_bundle(_StubModel(1), Path(tmp), dataset=self.dataset(), score={"dsr_probability": .95}, training={"data_hash": "a"*64})
            with patch("investment_agent.research.rl.bundle._load_ppo", return_value=_StubModel(1)) as loader:
                model=load_policy_bundle(path)
            self.assertEqual(model.symbols, ("AAPL",))
            self.assertEqual(model.feature_names, ("x",))
            self.assertEqual(model.dsr_probability, .95)
            self.assertEqual(loader.call_count, 1)

    def test_small_cpu_ppo_save_load_predictions_match(self):
        import importlib.util
        if importlib.util.find_spec("stable_baselines3") is None:
            self.skipTest("optional PPO runtime unavailable")
        from stable_baselines3 import PPO
        from investment_agent.research.rl.environment import make_gym_environment, WeightEnvironmentCore
        dataset=self.dataset()
        model=PPO("MlpPolicy",make_gym_environment(dataset), n_steps=8, batch_size=4, n_epochs=1, device="cpu", seed=3, policy_kwargs={"net_arch":[8]})
        model.learn(total_timesteps=8)
        with tempfile.TemporaryDirectory() as tmp:
            path=save_policy_bundle(model,Path(tmp),dataset=dataset,score={"dsr_probability":.5},training={"data_hash":"a"*64})
            loaded=load_policy_bundle(path)
            observation=WeightEnvironmentCore(dataset).observation()
            np.testing.assert_allclose(model.predict(observation,deterministic=True)[0], loaded.predict(observation)[0])

    def test_adoption_rejects_ineligible_candidate(self):
        from investment_agent.research.commands.continuous_retrain import adopt_candidate
        with tempfile.TemporaryDirectory() as tmp:
            path=save_policy_bundle(_StubModel(1),Path(tmp),dataset=self.dataset(),score={"dsr_probability":.1},training={"eligible_for_adoption":False})
            with patch("investment_agent.research.rl.bundle._load_ppo",return_value=_StubModel(1)):
                with self.assertRaises(ValueError): adopt_candidate(path,policy_dir=Path(tmp)/"active")
            self.assertFalse((Path(tmp)/"active"/"active_policy.json").exists())

    def test_manual_adoption_copies_verified_bundle_only(self):
        from investment_agent.research.commands.continuous_retrain import adopt_candidate
        with tempfile.TemporaryDirectory() as tmp:
            path=save_policy_bundle(_StubModel(1),Path(tmp)/"candidates",dataset=self.dataset(),score={"dsr_probability":.99},training={"eligible_for_adoption":True})
            with patch("investment_agent.research.rl.bundle._load_ppo",return_value=_StubModel(1)):
                active=adopt_candidate(path,policy_dir=Path(tmp)/"active")
                loaded=load_policy_bundle(active)
            import json
            self.assertEqual(loaded.artifact_id,json.loads(path.read_text())["artifact_id"])
