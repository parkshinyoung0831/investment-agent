"""채널 도착 확인 — '워크플로 초록인데 카드 없음'을 잡는 유일한 장치다.

여기가 틀리면 조용히 틀린다: 거짓 경보를 내면 며칠 만에 아무도 안 읽게 되고,
경보를 안 내면 채널이 죽어도 모른다. 그 둘의 경계만 검증한다.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.operations.monitoring import channels, digest, discord

UTC = timezone.utc
NOW = datetime(2026, 8, 19, 6, 30, tzinfo=UTC)


def _row(**overrides):
    base = {
        "label": "오늘의-시장", "cadence": "월~토 12:20", "quiet_hours": 52,
        "configured": True, "error": None, "count": 1,
        "last_at": NOW - timedelta(hours=2),
        "created_at": NOW - timedelta(days=200),
    }
    base.update(overrides)
    return base


class SnowflakeTest(unittest.TestCase):
    def test_snowflake_round_trips_through_time(self):
        moment = datetime(2026, 8, 18, 13, 5, tzinfo=UTC)
        restored = discord.snowflake_time(discord.time_snowflake(moment))

        self.assertLess(abs((restored - moment).total_seconds()), 1)

    def test_known_message_id_resolves_to_its_post_time(self):
        """실측값 — 2026-08-19 01:45:21 UTC에 올라간 매크로 카드."""
        resolved = discord.snowflake_time("1539450169437847613")

        self.assertEqual(resolved.strftime("%Y-%m-%d %H:%M"), "2026-08-19 01:45")


class JudgeTest(unittest.TestCase):
    def test_recent_card_is_quiet_success(self):
        judged = digest.judge_channels([_row()], NOW)[0]

        self.assertFalse(judged["alert"])
        self.assertEqual(judged["verdict"], "")

    def test_stale_channel_alerts(self):
        judged = digest.judge_channels(
            [_row(last_at=NOW - timedelta(hours=60))], NOW)[0]

        self.assertTrue(judged["alert"])
        self.assertIn("조용함", judged["verdict"])

    def test_event_driven_channel_never_alerts_on_silence(self):
        """발표·공시가 있어야 우는 채널을 조용하다고 경보하면 매일 거짓 경보가 뜬다."""
        judged = digest.judge_channels(
            [_row(label="지표-발표", quiet_hours=None, last_at=None, count=0)], NOW)[0]

        self.assertFalse(judged["alert"])

    def test_young_channel_waits_for_its_first_card(self):
        """어제 만든 채널을 '오래 조용하다'고 울면 첫 카드까지 며칠을 거짓으로 운다."""
        judged = digest.judge_channels(
            [_row(last_at=None, created_at=NOW - timedelta(hours=20))], NOW)[0]

        self.assertFalse(judged["alert"])
        self.assertEqual(judged["verdict"], "첫 카드 대기")

    def test_old_channel_that_never_received_alerts(self):
        judged = digest.judge_channels(
            [_row(last_at=None, created_at=NOW - timedelta(days=90))], NOW)[0]

        self.assertTrue(judged["alert"])
        self.assertEqual(judged["verdict"], "받은 적 없음")

    def test_unconfigured_channel_alerts_instead_of_disappearing(self):
        """시크릿을 빠뜨린 날 감시 대상에서 조용히 빠지면 아무도 모른다."""
        judged = digest.judge_channels([_row(configured=False)], NOW)[0]

        self.assertTrue(judged["alert"])
        self.assertIn("채널 ID", judged["verdict"])

    def test_read_failure_alerts(self):
        judged = digest.judge_channels([_row(error="403 Forbidden")], NOW)[0]

        self.assertTrue(judged["alert"])


class RenderTest(unittest.TestCase):
    def _clean(self):
        return digest.evaluate([], NOW - timedelta(hours=24), NOW)

    def test_channel_table_is_rendered_with_counts(self):
        body = digest.render(
            self._clean(), NOW, digest.judge_channels([_row(count=2)], NOW))

        self.assertIn("채널 도착", body)
        self.assertIn("오늘의-시장", body)

    def test_forum_shows_no_count_but_still_shows_last_activity(self):
        """포럼의 글은 메시지가 아니라 스레드라 셀 수 없다 — 없는 수를 지어내지 않는다."""
        body = digest.render(
            self._clean(), NOW,
            digest.judge_channels(
                [_row(label="실적-리포트", count=None, quiet_hours=None)], NOW),
        )

        self.assertIn("실적-리포트", body)
        self.assertIn("—", body)

    def test_channel_alert_suppresses_the_all_clear_line(self):
        """워크플로가 전부 초록이어도 채널이 비었으면 '이상 없음'이라고 하면 안 된다."""
        judged = digest.judge_channels([_row(last_at=NOW - timedelta(hours=60))], NOW)
        body = digest.render(self._clean(), NOW, judged)

        self.assertNotIn("이상 없습니다", body)


class ManifestDriftTest(unittest.TestCase):
    def test_every_watched_channel_says_how_to_find_itself(self):
        """`env`(시크릿) 아니면 `name`(봇이 길드에서 찾음) 중 하나는 있어야 한다."""
        for entry in channels.WATCHED:
            with self.subTest(channel=entry["label"]):
                self.assertTrue(
                    bool(entry.get("env")) ^ bool(entry.get("name")),
                    "찾는 방법이 없거나 둘 다인 항목",
                )

    def test_watched_channels_use_env_vars_the_notifiers_read(self):
        """여기만 따로 두면 채널을 옮길 때 한쪽만 고치게 된다."""
        from investment_agent.notifications.discord_admin import manifest

        declared = {c["env"] for c in manifest.channels() if c.get("env")}
        for entry in channels.WATCHED:
            if not entry.get("env"):
                continue
            with self.subTest(channel=entry["label"]):
                self.assertIn(entry["env"], declared)

    def test_watched_labels_match_the_real_channel_names(self):
        from investment_agent.notifications.discord_admin import manifest

        by_env = {c["env"]: c["name"] for c in manifest.channels() if c.get("env")}
        declared_names = {c["name"] for c in manifest.channels()}
        for entry in channels.WATCHED:
            with self.subTest(channel=entry["label"]):
                if entry.get("env"):
                    self.assertEqual(entry["label"], by_env[entry["env"]])
                else:
                    # 이름으로 찾는 항목은 그 이름이 선언에 실제로 있어야 한다.
                    self.assertIn(entry["name"], declared_names)
                    self.assertEqual(entry["label"], entry["name"])

    def test_every_production_card_channel_is_watched(self):
        """감시 목록에서 빠진 채널은 죽어도 아무도 모른다. 랩은 제외한다."""
        from investment_agent.notifications.discord_admin import manifest

        watched_envs = {e["env"] for e in channels.WATCHED if e.get("env")}
        watched_names = {e["name"] for e in channels.WATCHED if e.get("name")}
        missing = set()
        for channel in manifest.channels():
            if channel["category_key"] == "lab":
                continue
            if channel.get("env"):
                if channel["env"] not in watched_envs:
                    missing.add(channel["env"])
            elif channel.get("resolve") == "name" and channel["name"] not in watched_names:
                # 카드 목적지인데 ID를 env로 받지 않는 채널. 감시에서 빠지면
                # 그 거장의 카드가 끊겨도 아무도 모른다.
                missing.add(channel["name"])
        self.assertEqual(set(), missing)


if __name__ == "__main__":
    unittest.main()
