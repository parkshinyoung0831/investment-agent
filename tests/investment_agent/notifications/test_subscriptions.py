"""notifications.subscriptions 읽기 계약을 검증한다."""
from __future__ import annotations

import unittest

from investment_agent.config import Config
from investment_agent.notifications.subscriptions import (
    KIND_ENV,
    SubscriptionConfigurationError,
    discord_target,
)


def _config(**env: str) -> Config:
    return Config(env=env, dotenv_path=None, dotenv_loaded=False)


class DiscordTargetTests(unittest.TestCase):
    def test_reads_target_from_the_kind_s_env_var(self) -> None:
        config = _config(DISCORD_CHANNEL_MACRO_DAILY="123")

        self.assertEqual(discord_target("macro_core", config=config), "123")

    def test_every_kind_maps_to_a_distinct_env_var_or_a_shared_one_on_purpose(self) -> None:
        # 실적 포럼 셋(예정·속보·정밀 분석)은 **같은 종목 스레드**에 쌓이려고
        # 한 채널을 공유한다. investment_portfolio/candidates도 의도된 공유다.
        # 그 외 중복은 실수다.
        shared_pairs = (
            frozenset({"fundamentals_schedule", "fundamentals_flash",
                       "fundamentals_earnings"}),
            frozenset({"investment_portfolio", "investment_candidates"}),
        )
        by_env: dict[str, set[str]] = {}
        for kind, env_name in KIND_ENV.items():
            by_env.setdefault(env_name, set()).add(kind)
        for env_name, kinds in by_env.items():
            if len(kinds) > 1:
                self.assertIn(frozenset(kinds), shared_pairs, f"unexpected shared env {env_name}: {kinds}")

    def test_fails_closed_when_unknown_kind(self) -> None:
        with self.assertRaises(SubscriptionConfigurationError):
            discord_target("not_a_real_kind", config=_config())

    def test_fails_closed_when_env_var_is_missing(self) -> None:
        with self.assertRaises(SubscriptionConfigurationError):
            discord_target("macro_core", config=_config())

    def test_override_wins_without_touching_the_environment(self) -> None:
        """테스트·CLI가 채널을 직접 지정하는 자리. env가 비어도 통과해야 한다."""
        self.assertEqual(
            discord_target("macro_core", config=_config(), override="999"), "999",
        )


if __name__ == "__main__":
    unittest.main()
