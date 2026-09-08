"""매니페스트 ↔ 서버 대조 — 여기가 틀리면 채널이 중복 생성된다."""
from __future__ import annotations

import unittest

from investment_agent.notifications.discord_admin import manifest, sync


def _existing(*names_and_types):
    return [{"id": f"{100 + i}", "name": n, "type": t}
            for i, (n, t) in enumerate(names_and_types)]


class PlanTest(unittest.TestCase):
    def test_empty_server_creates_everything(self):
        result = sync.plan([])

        self.assertEqual(len(result["create_categories"]), len(manifest.LAYOUT))
        self.assertEqual(len(result["create_channels"]), len(manifest.channels()))
        self.assertEqual(result["matched"], [])

    def test_existing_channel_is_matched_not_recreated(self):
        result = sync.plan(_existing(("📊 MARKET DESK", manifest.CATEGORY),
                                     ("오늘의-시장", manifest.TEXT)))

        matched = {c["name"] for c in result["matched"]}
        creating = {c["name"] for c in result["create_channels"]}
        self.assertIn("오늘의-시장", matched)
        self.assertNotIn("오늘의-시장", creating)

    def test_forum_channel_is_managed_too(self):
        """포럼을 텍스트로만 찾으면 매번 '없음'으로 잡혀 실적 포럼이 중복 생성된다."""
        result = sync.plan(_existing(("실적-리포트", manifest.FORUM)))

        self.assertIn("실적-리포트", {c["name"] for c in result["matched"]})
        self.assertNotIn("실적-리포트", {c["name"] for c in result["create_channels"]})

    def test_voice_channel_is_managed_too(self):
        """음성 채널을 텍스트로만 찾으면 매번 '없음'으로 잡혀 중복 생성된다."""
        result = sync.plan(_existing(("라운지-보이스", manifest.VOICE)))

        self.assertIn("라운지-보이스", {c["name"] for c in result["matched"]})
        self.assertNotIn("라운지-보이스", {c["name"] for c in result["create_channels"]})

    def test_unknown_channel_is_reported_never_deleted(self):
        """삭제는 구현하지 않는다 — 보고만 하고 사람이 판단한다."""
        result = sync.plan(_existing(("옛날-채널", manifest.TEXT)))

        self.assertEqual([c["name"] for c in result["unmanaged"]], ["옛날-채널"])
        self.assertNotIn("delete", result)

    def test_env_updates_only_cover_bound_channels(self):
        matched = [
            {"name": "시장-브리핑", "id": "1", "env": "DISCORD_CHANNEL_MACRO_DAILY"},
            {"name": "라운지", "id": "2", "env": None},
        ]
        self.assertEqual(sync.env_updates(matched),
                         {"DISCORD_CHANNEL_MACRO_DAILY": "1"})


class ForumTagTest(unittest.TestCase):
    """태그를 잘못 다루면 이미 쓴 스레드에서 태그가 떨어진다."""

    def test_missing_tags_are_reported(self):
        forum = _existing(("실적-리포트", manifest.FORUM))
        forum[0]["available_tags"] = [{"id": "9", "name": "빅테크"}]

        updates = sync.plan(forum)["tag_updates"]

        self.assertEqual([u["name"] for u in updates], ["실적-리포트"])
        self.assertEqual(updates[0]["tags"], manifest.EARNINGS_TAGS)

    def test_complete_tags_are_left_alone(self):
        forum = _existing(("실적-리포트", manifest.FORUM))
        forum[0]["available_tags"] = [
            {"id": str(i), "name": name} for i, name in enumerate(manifest.EARNINGS_TAGS)
        ]

        self.assertEqual(sync.plan(forum)["tag_updates"], [])

    def test_reordered_tags_are_not_a_change(self):
        """순서만 다른 것을 '바뀜'으로 잡으면 사람이 정렬만 고쳐도 매번 다시 쓴다."""
        forum = _existing(("실적-리포트", manifest.FORUM))
        forum[0]["available_tags"] = [
            {"id": str(i), "name": name}
            for i, name in enumerate(reversed(manifest.EARNINGS_TAGS))
        ]

        self.assertEqual(sync.plan(forum)["tag_updates"], [])


class ManifestTest(unittest.TestCase):
    def test_env_variables_are_unique(self):
        """두 채널이 같은 변수를 쓰면 카드가 엉뚱한 방으로 간다."""
        envs = [c["env"] for c in manifest.channels() if c.get("env")]
        self.assertEqual(len(envs), len(set(envs)))

    def test_channel_names_are_unique(self):
        names = [c["name"] for c in manifest.channels()]
        self.assertEqual(len(names), len(set(names)))

    def test_forum_tags_match_the_notify_routing_table(self):
        """발송 코드가 아는 태그 이름과 서버에 만드는 태그가 어긋나면 태그 없이 나간다."""
        from investment_agent.notifications.channels import routing

        declared = set(manifest.EARNINGS_TAGS)
        used = set(routing.SIC_DIVISION_TAGS.values()) | {routing.ANNUAL_TAG}
        self.assertEqual(used - declared, set())

    def test_strategy_forum_tags_match_the_notify_routing_table(self):
        """전략 태그 선언과 발송 routing 대응표가 일치해야 한다."""
        from investment_agent.notifications.channels import routing

        declared = set(manifest.STRATEGY_TAGS)
        used = set(routing.STRATEGY_TAGS_MAP.values())
        self.assertEqual(used - declared, set())

    def test_guru_tags_match_the_forum_declaration(self):
        """발송이 다는 태그와 포럼에 선언된 태그가 같아야 한다.

        어긋나면 카드가 태그 없이 나가고, 포럼 목록에서 그 사람만 걸러 읽을 수 없다.
        """
        from investment_agent.notifications.channels import routing

        forum, = [c for c in manifest.channels() if c["key"] == "guru_forum"]
        self.assertEqual(set(forum["tags"]), set(routing.guru_names().values()))

    def test_gurus_live_in_one_forum_not_one_channel_each(self):
        """사람마다 채널을 두면 13F 연 4건을 위해 채널·권한·감시가 하나씩 는다.

        늘리는 자리가 여럿이면 그중 하나를 빠뜨리고, 그 사람의 카드는 조용히
        요약 채널로 떨어진다.
        """
        from investment_agent.data.institutional.domain.managers import guru_tags

        forum = [c for c in manifest.channels() if c["key"] == "guru_forum"]
        self.assertEqual(1, len(forum))
        self.assertEqual(manifest.FORUM, forum[0]["kind"])
        # 거장 수와 무관하게 GURUS 카테고리의 채널 수는 그대로다(요약 + 포럼).
        category = [c for c in manifest.channels() if c["category_key"] == "gurus"]
        self.assertEqual(2, len(category))
        self.assertGreaterEqual(len(guru_tags()), 7)

    def test_community_required_channels_are_declared(self):
        """포럼을 쓰려면 길드가 Community여야 하고, 전환에는 이 두 채널이 필요하다."""
        if not manifest.needs_community():
            self.skipTest("포럼을 쓰지 않는 매니페스트")
        self.assertIsNotNone(manifest.role_channel("rules"))
        self.assertIsNotNone(manifest.role_channel("updates"))

    def test_lab_channels_are_separated_from_production(self):
        """운영 카드와 실험 카드가 같은 방에 섞이면 처음 보는 사람은 구분하지 못한다."""
        lab = [c for c in manifest.channels() if c["category_key"] == "lab"]
        self.assertTrue(lab)
        for channel in lab:
            self.assertNotEqual(channel["category_key"], "intelligence")


if __name__ == "__main__":
    unittest.main()


class PositionTest(unittest.TestCase):
    """재생성 시 배치가 무너지지 않아야 한다."""

    def test_channels_carry_their_declared_order(self):
        for category in manifest.LAYOUT:
            names = [c["name"] for c in category["channels"]]
            flat = [c for c in manifest.channels() if c["category"] == category["name"]]
            with self.subTest(category=category["name"]):
                self.assertEqual([c["position"] for c in flat], list(range(len(names))))
