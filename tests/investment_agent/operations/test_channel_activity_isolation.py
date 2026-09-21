"""채널 하나의 설정 오류가 일일 점검의 채널 절 전체를 없애지 않는다.

`activity`의 docstring은 "채널 하나를 못 읽었다고 일일 점검 전체가 사라지면, 점검이
없는 것보다 나쁘다"라고 적는다. 그런데 `created_at = snowflake_time(channel_id)`가
`try` **밖**에 있어, 채널 ID에 이름·URL을 넣은 설정 오류에서 `int()`가 그대로 터지고
16개 채널 점검이 통째로 빠졌다(감사 OP2-18).
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from investment_agent.operations.monitoring import discord as monitoring_discord


class ChannelActivityIsolationTest(unittest.TestCase):
    SINCE = datetime(2026, 9, 20, tzinfo=timezone.utc)

    def test_a_non_numeric_channel_id_becomes_an_error_row(self):
        row = monitoring_discord.activity("오늘의-시장", self.SINCE)
        self.assertIsNotNone(row["error"])
        self.assertIsNone(row["created_at"])
        self.assertIsNone(row["last_at"])

    def test_it_does_not_call_discord_for_an_invalid_id(self):
        with mock.patch.object(monitoring_discord, "requests") as requests:
            monitoring_discord.activity("not-a-snowflake", self.SINCE)
            requests.get.assert_not_called()

    def test_a_valid_id_still_reports_created_at(self):
        """조회가 실패해도 채널 생성 시각은 ID에서 나온다 — 그 행이 사라지면 안 된다."""
        with mock.patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "t"}, clear=False):
            with mock.patch.object(monitoring_discord, "requests") as requests:
                requests.get.return_value.json.return_value = {"last_message_id": None}
                requests.get.return_value.raise_for_status.return_value = None
                row = monitoring_discord.activity("1539250099999999999", self.SINCE, forum=True)
        self.assertIsNone(row["error"])
        self.assertIsNotNone(row["created_at"])


if __name__ == "__main__":
    unittest.main()
