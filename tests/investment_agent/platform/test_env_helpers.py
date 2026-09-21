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

    def test_out_of_range_names_the_variable_instead_of_being_clamped(self) -> None:
        """음수 lookback은 조회 창을 미래로 보내 카드가 조용히 0장이 된다 — 고쳐 쓰지 않고 거절한다."""
        with mock.patch.dict(os.environ, {"X_N": "-1", "X_F": "10"}):
            with self.assertRaisesRegex(ValueError, "X_N"):
                env_int("X_N", 7, minimum=1, maximum=365)
            with self.assertRaisesRegex(ValueError, "X_F"):
                env_float("X_F", 1.0, minimum=30.0, maximum=86_400.0)

    def test_default_is_not_range_checked_and_bounds_are_inclusive(self) -> None:
        with mock.patch.dict(os.environ, {"X_N": "1"}):
            self.assertEqual(1, env_int("X_N", 7, minimum=1, maximum=365))
        self.assertEqual(7, env_int("X_UNSET_N", 7, minimum=1, maximum=365))

    def test_notification_lookbacks_reject_negative_values(self) -> None:
        from investment_agent.notifications.earnings_flash import candidates as flash
        from investment_agent.notifications.earnings_report import candidates as report

        with mock.patch.dict(os.environ, {"FLASH_NOTIFY_LOOKBACK_DAYS": "-1", "FUNDAMENTALS_NOTIFY_LOOKBACK_DAYS": "0"}):
            with self.assertRaisesRegex(ValueError, "FLASH_NOTIFY_LOOKBACK_DAYS"):
                flash._lookback_days()
            with self.assertRaisesRegex(ValueError, "FUNDAMENTALS_NOTIFY_LOOKBACK_DAYS"):
                report._lookback_days()


if __name__ == "__main__":
    unittest.main()
