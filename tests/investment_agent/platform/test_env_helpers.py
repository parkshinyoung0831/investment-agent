"""빈 환경변수는 미설정과 같다(HC-4)."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from investment_agent.platform.env import env_float, env_int, env_str


class EnvHelpersTest(unittest.TestCase):
    def test_blank_value_takes_the_default(self) -> None:
        with mock.patch.dict(os.environ, {"X_N": "", "X_F": "  ", "X_S": ""}):
            self.assertEqual(env_int("X_N", 7), 7)
            self.assertEqual(env_float("X_F", 0.5), 0.5)
            self.assertEqual(env_str("X_S", "2014-01-01"), "2014-01-01")

    def test_set_value_wins(self) -> None:
        with mock.patch.dict(os.environ, {"X_N": "3", "X_F": "1.5", "X_S": "2020-01-01"}):
            self.assertEqual((env_int("X_N", 7), env_float("X_F", 0.5), env_str("X_S", "d")), (3, 1.5, "2020-01-01"))

    def test_garbage_names_the_variable(self) -> None:
        with mock.patch.dict(os.environ, {"X_N": "abc"}):
            with self.assertRaisesRegex(ValueError, "X_N"):
                env_int("X_N", 7)


if __name__ == "__main__":
    unittest.main()
