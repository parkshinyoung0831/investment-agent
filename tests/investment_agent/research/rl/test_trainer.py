from __future__ import annotations

import unittest
from unittest.mock import patch

from investment_agent.research.rl.trainer import FinRLTrainer


class _FakeModel:
    last_init = None

    def __init__(self, policy, env, **kwargs):
        self.policy = policy
        self.env = env
        self.kwargs = kwargs
        self.learn_args = None
        _FakeModel.last_init = self

    def learn(self, **kwargs):
        self.learn_args = kwargs
        return self


class FinRLTrainerTest(unittest.TestCase):
    def test_uses_direct_sb3_model_without_finrl_broker_package(self):
        environment = object()
        trainer = FinRLTrainer(environment)
        with patch.object(FinRLTrainer, "_model_class", return_value=_FakeModel):
            result = trainer.train(
                "PPO",
                total_timesteps=123,
                seed=17,
                model_kwargs={"learning_rate": 0.001},
                tensorboard_log="artifacts/tensorboard",
            )
        self.assertIs(result, _FakeModel.last_init)
        self.assertEqual(result.policy, "MlpPolicy")
        self.assertIs(result.env, environment)
        self.assertEqual(result.kwargs["seed"], 17)
        self.assertEqual(result.kwargs["learning_rate"], 0.001)
        self.assertEqual(result.learn_args["total_timesteps"], 123)
        self.assertEqual(result.learn_args["tb_log_name"], "ai_investor_ppo")

    def test_caller_cannot_override_owned_safety_fields(self):
        trainer = FinRLTrainer(object())
        for field in ("env", "policy", "seed", "tensorboard_log"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "trainer-owned"):
                    trainer.train(
                        "ppo",
                        total_timesteps=1,
                        seed=1,
                        model_kwargs={field: object()},
                    )

    def test_unknown_algorithm_and_nonpositive_steps_fail_before_import(self):
        trainer = FinRLTrainer(object())
        with self.assertRaisesRegex(ValueError, "unsupported"):
            trainer.train("dqn", total_timesteps=1, seed=1)
        with self.assertRaisesRegex(ValueError, "positive"):
            trainer.train("ppo", total_timesteps=0, seed=1)


if __name__ == "__main__":
    unittest.main()
