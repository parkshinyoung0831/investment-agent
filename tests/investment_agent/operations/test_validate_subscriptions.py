"""workflow용 subscription read-only validation을 검증한다."""
from __future__ import annotations

import unittest

from investment_agent.config import Config
from investment_agent.operations.commands.validate_subscriptions import validate


def _config(**env: str) -> Config:
    return Config(env=env, dotenv_path=None, dotenv_loaded=False)


class ValidateSubscriptionsTest(unittest.TestCase):
    def test_validates_selected_kind_without_writing(self) -> None:
        config = _config(DISCORD_CHANNEL_MACRO_DAILY="123")

        self.assertEqual(validate(config, ["macro_core"]), {"macro_core": "123"})

    def test_rejects_unknown_kind(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown subscription kind"):
            validate(_config(), ["not_a_real_kind"])

    def test_fails_when_env_var_is_missing(self) -> None:
        with self.assertRaises(RuntimeError):
            validate(_config(), ["macro_core"])


if __name__ == "__main__":
    unittest.main()
