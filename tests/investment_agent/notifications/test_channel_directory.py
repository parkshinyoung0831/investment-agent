"""채널을 이름으로 찾는 경로를 굳힌다.

거장 채널 ID를 시크릿으로 들고 있던 것을 봇 조회로 바꿨다. 그 조회가 틀리면 카드가
엉뚱한 채널로 가거나(같은 이름이 둘일 때) 요약 채널로 조용히 떨어진다 — 둘 다
런타임에만 드러나므로 여기서 그 경계를 못박는다.
"""
from __future__ import annotations

import unittest

from investment_agent.config import Config
from investment_agent.notifications.channels import directory, routing

FORUM = directory.FORUM


def _config(**env: str) -> Config:
    return Config(env={"DISCORD_GUILD_ID": "1", "DISCORD_BOT_TOKEN": "t", **env},
                  dotenv_path=None, dotenv_loaded=False)


def _rows() -> list[dict]:
    return [
        {"id": "100", "name": "13f-요약", "type": 0},
        {"id": "200", "name": "워런-버핏", "type": FORUM,
         "available_tags": [{"id": "9001", "name": "제조"}, {"id": "9002", "name": "금융·부동산"}]},
        {"id": "300", "name": "빌-애크먼", "type": FORUM},
    ]


class BuildDirectoryTest(unittest.TestCase):
    def test_finds_a_channel_by_its_declared_name(self) -> None:
        found = directory.build_directory(_rows()).find("워런-버핏")
        self.assertIsNotNone(found)
        self.assertEqual("200", found.channel_id)
        self.assertTrue(found.is_forum)

    def test_name_matching_ignores_case_like_discord_does(self) -> None:
        """Discord는 채널 이름을 소문자로 정규화한다. 대소문자로 못 찾으면 안 된다."""
        rows = [{"id": "400", "name": "Guru-Test", "type": FORUM}]
        self.assertIsNotNone(directory.build_directory(rows).find("guru-test"))

    def test_a_duplicated_name_is_refused_rather_than_guessed(self) -> None:
        """이름이 겹치는데 하나를 찍으면 절반이 엉뚱한 채널로 가고 로그에도 안 남는다."""
        rows = _rows() + [{"id": "999", "name": "워런-버핏", "type": FORUM}]
        built = directory.build_directory(rows)
        self.assertIsNone(built.find("워런-버핏"))
        self.assertIn("워런-버핏", built.duplicated_names)

    def test_rows_without_a_usable_id_are_skipped(self) -> None:
        rows = [{"id": "", "name": "빈-채널", "type": 0}, {"id": "abc", "name": "이상한-id", "type": 0}]
        self.assertEqual({}, dict(directory.build_directory(rows).channels))

    def test_forum_tags_resolve_by_name(self) -> None:
        """태그는 이름이 아니라 snowflake로 지정해야 한다."""
        built = directory.build_directory(_rows())
        self.assertEqual(["9001"], built.tag_ids("워런-버핏", ("제조",)))

    def test_an_undeclared_tag_is_dropped_not_sent(self) -> None:
        built = directory.build_directory(_rows())
        self.assertEqual([], built.tag_ids("워런-버핏", ("없는태그",)))


class GuildDirectoryCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        directory.reset_cache()
        self.addCleanup(directory.reset_cache)

    def test_the_guild_is_fetched_once_per_process(self) -> None:
        """카드 한 장마다 길드 전체를 다시 받으면 rate limit에 먼저 걸린다."""
        calls = []

        def fetch(config):
            calls.append(config)
            return _rows()

        for _ in range(3):
            directory.guild_directory(_config(), fetch=fetch)
        self.assertEqual(1, len(calls))

    def test_refresh_reads_the_guild_again(self) -> None:
        calls = []

        def fetch(config):
            calls.append(config)
            return _rows()

        directory.guild_directory(_config(), fetch=fetch)
        directory.guild_directory(_config(), fetch=fetch, refresh=True)
        self.assertEqual(2, len(calls))


class GuruRoutingTest(unittest.TestCase):
    """거장은 포럼 하나에 사람마다 스레드 하나다.

    전에는 사람마다 포럼 채널이 있었다. 13F는 분기 공시라 한 사람이 연 4건인데
    그 4건을 위해 채널·권한·감시 대상이 하나씩 늘었고, 늘리는 자리 중 하나를
    빠뜨리면 그 사람의 카드가 조용히 요약 채널로 떨어졌다.
    """

    #: 거장 포럼 하나. 태그는 사람 이름이다.
    FORUM_ID = "300"

    def setUp(self) -> None:
        directory.reset_cache()
        self.addCleanup(directory.reset_cache)

    @staticmethod
    def _guild():
        return [
            {"id": "100", "name": "13f-요약", "type": 0},
            {"id": "300", "name": "거장-13f", "type": FORUM, "available_tags": [
                {"id": "9101", "name": "워런 버핏"},
                {"id": "9102", "name": "빌 애크먼"},
            ]},
        ]

    def test_every_tracked_guru_has_a_display_name(self) -> None:
        """이름이 없는 거장은 태그도 스레드 제목도 만들 수 없다."""
        names = routing.guru_names()
        self.assertEqual(7, len(names))
        self.assertTrue(all(name and name.strip() for name in names.values()))

    def test_a_guru_resolves_to_the_tag_on_the_forum(self) -> None:
        directory.guild_directory(_config(), fetch=lambda _c: self._guild())
        # 워런 버핏의 CIK.
        self.assertEqual(
            ("9101",), routing.guru_tag_ids("0001067983", self.FORUM_ID, config=_config()))

    def test_an_unknown_guru_gets_no_tag(self) -> None:
        directory.guild_directory(_config(), fetch=lambda _c: self._guild())
        self.assertEqual(
            (), routing.guru_tag_ids("9999999999", self.FORUM_ID, config=_config()))

    def test_a_guru_without_a_declared_tag_sends_untagged(self) -> None:
        """태그 하나 때문에 그 분기 공시를 통째로 막지 않는다."""
        directory.guild_directory(_config(), fetch=lambda _c: [self._guild()[0]])
        self.assertEqual(
            (), routing.guru_tag_ids("0001067983", self.FORUM_ID, config=_config()))

    def test_the_thread_is_the_person_not_the_quarter(self) -> None:
        """분기마다 새 스레드를 만들면 7명 × 4분기 = 연 28개가 되어 흐름이 끊긴다."""
        self.assertEqual("워런 버핏 · 13F 기록", routing.guru_thread_title("워런 버핏"))


if __name__ == "__main__":
    unittest.main()
