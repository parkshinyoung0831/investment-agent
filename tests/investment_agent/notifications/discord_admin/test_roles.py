"""역할·권한 선언이 조용히 잘못 열리거나 잘못 닫히지 않는지 지킨다.

권한은 틀려도 아무것도 실패하지 않는 종류다. 너무 열면 아무 일도 안 일어난 것처럼 보이다가
어느 날 광고가 붙고, 너무 닫으면 카드가 조용히 안 나가면서 CI는 초록이다. 그래서 여기 걸린
규칙은 전부 "무엇이 일어나지 않아야 하는가"다.
"""
from __future__ import annotations

import unittest

from investment_agent.notifications.discord_admin import manifest, onboarding, roles


class EveryoneTest(unittest.TestCase):
    def test_everyone_cannot_speak_anywhere(self):
        """이 설계의 전제. @everyone에 쓰기 권한이 붙으면 모든 카드 채널이 한 번에 열린다."""
        for bit, name in [(roles.SEND_MESSAGES, "메시지 보내기"),
                          (roles.SEND_MESSAGES_IN_THREADS, "스레드에 쓰기"),
                          (roles.CREATE_PUBLIC_THREADS, "스레드 만들기"),
                          (roles.ATTACH_FILES, "파일 첨부"),
                          (roles.CREATE_INSTANT_INVITE, "초대 만들기")]:
            with self.subTest(permission=name):
                self.assertFalse(roles.EVERYONE_PERMISSIONS & bit)

    def test_everyone_can_still_read_and_react(self):
        """읽지도 못하면 서버가 아니다 — '반응만 가능'이 기본값이라는 뜻."""
        for bit in (roles.VIEW_CHANNEL, roles.READ_MESSAGE_HISTORY, roles.ADD_REACTIONS):
            self.assertTrue(roles.EVERYONE_PERMISSIONS & bit)

    def test_everyone_has_nothing_dangerous(self):
        self.assertFalse(roles.EVERYONE_PERMISSIONS & roles.FORBIDDEN)


class RoleTest(unittest.TestCase):
    def test_no_role_carries_server_control(self):
        """모더레이터에게도 서버 구조·차단은 주지 않는다 — 되돌릴 수 없는 것은 사람에게."""
        for declared in roles.ROLES:
            with self.subTest(role=declared["name"]):
                self.assertFalse(declared["permissions"] & roles.FORBIDDEN)

    def test_role_keys_are_unique(self):
        keys = [d["key"] for d in roles.ROLES]
        self.assertEqual(len(keys), len(set(keys)))

    def test_bot_can_do_everything_the_notify_code_does(self):
        """카드 봇 권한이 하나라도 빠지면 그 알림만 조용히 실패한다.

        근거: src/investment_agent/notifications/channels/discord.py(첨부·embed·포럼 스레드)와
        src/investment_agent/operations/discord.py(도착 확인을 위해 /messages를 읽는다).
        """
        needed = (roles.VIEW_CHANNEL | roles.READ_MESSAGE_HISTORY | roles.SEND_MESSAGES
                  | roles.SEND_MESSAGES_IN_THREADS | roles.CREATE_PUBLIC_THREADS
                  | roles.EMBED_LINKS | roles.ATTACH_FILES)
        self.assertEqual(roles.BOT_PERMISSIONS & needed, needed)

    def test_only_the_brand_color_is_used(self):
        """DESIGN-system.md — 색 voltage는 하나다."""
        self.assertEqual({d["color"] for d in roles.ROLES}, {0x3182F6})


class GrantTest(unittest.TestCase):
    def test_grants_point_at_declared_channels(self):
        keys = {c["key"] for c in manifest.channels()}
        self.assertEqual(set(roles.GRANTS) - keys, set())

    def test_grants_and_private_allow_name_real_roles(self):
        keys = {d["key"] for d in roles.ROLES}
        for grants in roles.GRANTS.values():
            self.assertEqual(set(grants) - keys, set())
        self.assertEqual(set(roles.PRIVATE_ALLOW) - keys, set())
        for denied in roles.PRIVATE_CHANNEL_DENY.values():
            self.assertEqual(set(denied) - keys, set())

    def test_earnings_forum_grants_replies_but_not_new_posts(self):
        """포럼에서 SEND_MESSAGES는 '새 글 쓰기'다. 주면 공시 1건 = 스레드 1개가 깨진다."""
        grant = roles.GRANTS["earnings"]["member"]
        self.assertTrue(grant & roles.SEND_MESSAGES_IN_THREADS)
        self.assertFalse(grant & roles.SEND_MESSAGES)

    def test_no_deny_is_placed_on_a_card_channel(self):
        """@everyone 채널 deny는 그 채널에서 봇의 길드 권한까지 무력화한다.

        private 카테고리(사람이 볼 일 없는 곳)에서만 쓰고, 카드가 나가는 채널에는 절대
        달지 않는다 — 달면 카드가 조용히 안 나가고 CI는 초록이다.
        """
        private = {c["name"] for c in manifest.private_categories()}
        private |= {c["name"] for c in manifest.channels() if c["private"]}
        for item in roles.overwrites():
            if item["deny"]:
                with self.subTest(target=item["target"]):
                    self.assertIn(item["target"], private)


class PrivateCategoryTest(unittest.TestCase):
    def test_hidden_channels_all_get_a_bot_override(self):
        """숨긴 채널마다 봇 allow가 따라붙어야 한다 — 하나 빠지면 랩 카드가 조용히 죽는다."""
        wanted = {c["name"] for c in manifest.private_categories()}
        wanted |= {
            c["name"] for c in manifest.channels()
            if c["private"] and c["key"] != "ai_approvals"
        }
        covered = {item["target"] for item in roles.overwrites()
                   if item["role"] == "cardbot" and item["allow"] & roles.VIEW_CHANNEL}
        self.assertEqual(wanted - covered, set())

    def test_approval_channel_is_isolated_to_the_approval_bot(self):
        approval_name = next(
            c["name"] for c in manifest.channels() if c["key"] == "ai_approvals"
        )
        declared = [item for item in roles.overwrites() if item["target"] == approval_name]
        cardbot = next(item for item in declared if item["role"] == "cardbot")
        approvalbot = next(item for item in declared if item["role"] == "approvalbot")
        self.assertTrue(cardbot["deny"] & roles.VIEW_CHANNEL)
        self.assertFalse(cardbot["allow"] & roles.VIEW_CHANNEL)
        self.assertTrue(approvalbot["allow"] & roles.VIEW_CHANNEL)

    def test_hidden_channels_are_hidden_from_everyone(self):
        wanted = {c["name"] for c in manifest.channels() if c["private"]}
        hidden = {item["target"] for item in roles.overwrites()
                  if item["role"] == roles.EVERYONE_KEY and item["deny"] & roles.VIEW_CHANNEL}
        self.assertEqual(wanted - hidden, set())

    def test_the_private_category_list_is_exactly_these_three(self):
        """공개 채널을 실수로 숨기면 사람들은 그 채널이 있는 줄도 모른다.

        ai_investor는 보유종목·비중·체결가가 드러나므로 숨긴다.
        """
        self.assertEqual({c["key"] for c in manifest.private_categories()},
                         {"ai_investor", "lab", "operations"})


class PlanTest(unittest.TestCase):
    def _roles(self, **overrides):
        out = [{"id": "9", "name": "@everyone", "permissions": str(roles.EVERYONE_PERMISSIONS)}]
        for index, declared in enumerate(roles.ROLES):
            out.append({"id": str(100 + index), "name": declared["name"],
                        "permissions": str(overrides.get(declared["key"],
                                                         declared["permissions"]))})
        return out

    def test_matching_server_needs_no_change(self):
        plan = roles.plan_roles(self._roles())
        self.assertEqual(plan["create"], [])
        self.assertEqual(plan["update"], [])
        self.assertIsNone(roles.plan_everyone(self._roles(), "9"))

    def test_drifted_permissions_are_reported_for_update(self):
        drifted = self._roles(member=roles.EVERYONE_PERMISSIONS | roles.SEND_MESSAGES)
        plan = roles.plan_roles(drifted)
        self.assertEqual([r["key"] for r in plan["update"]], ["member"])

    def test_missing_roles_are_created_not_deleted(self):
        plan = roles.plan_roles([])
        self.assertEqual(len(plan["create"]), len(roles.ROLES))
        self.assertNotIn("delete", plan)

    def test_everyone_diff_names_what_is_taken_away(self):
        loose = [{"id": "9", "name": "@everyone",
                  "permissions": str(roles.EVERYONE_PERMISSIONS | roles.SEND_MESSAGES)}]
        diff = roles.plan_everyone(loose, "9")
        self.assertEqual(diff["removing"], roles.SEND_MESSAGES)
        self.assertEqual(diff["adding"], 0)

    def test_existing_overwrite_is_not_rewritten(self):
        """같은 값을 매번 다시 쓰면 감사 로그가 우리 소음으로 덮인다."""
        channels = [{"id": "1", "name": "라운지", "permission_overwrites": [
            {"id": "200", "allow": str(roles.CHAT), "deny": "0"}]}]
        plan = roles.plan_overwrites(channels, {"member": "200"})
        self.assertEqual([i["target"] for i in plan["ok"]], ["라운지"])
        self.assertEqual(plan["apply"], [])

    def test_unknown_channel_is_reported_not_guessed(self):
        plan = roles.plan_overwrites([], {"member": "200"})
        self.assertTrue(all(i["why"] == "채널 없음" for i in plan["missing"]
                            if i["role"] == "member"))
        self.assertEqual(plan["apply"], [])


class OnboardingGateTest(unittest.TestCase):
    def test_lounge_option_grants_the_member_role(self):
        """이 옵션이 역할을 주지 않으면 라운지는 아무에게도 열리지 않는다."""
        options = [o for prompt in onboarding.PROMPTS for o in prompt["options"]]
        granting = [o for o in options if o.get("roles")]
        self.assertTrue(granting)
        self.assertEqual({r for o in granting for r in o["roles"]}, {"member"})

    def test_option_drops_out_when_the_role_is_missing(self):
        """역할이 없는데 옵션만 남으면 눌러도 아무 일이 없는 버튼이 된다."""
        ids = {c["key"]: str(i) for i, c in enumerate(manifest.channels())}

        payload = onboarding.build(ids, role_ids={})

        titles = [o["title"] for p in payload["prompts"] for o in p["options"]]
        self.assertNotIn("네, 라운지에서 이야기할래요", titles)

    def test_role_ids_reach_the_payload(self):
        ids = {c["key"]: str(i) for i, c in enumerate(manifest.channels())}

        payload = onboarding.build(ids, role_ids={"member": "777"})

        granted = [o for p in payload["prompts"] for o in p["options"] if o["role_ids"]]
        self.assertEqual([o["role_ids"] for o in granted], [["777"]])

    def test_option_emoji_are_real_emoji(self):
        """서버 이름에 쓰는 ◆·✦ 같은 기하 기호는 Discord가 이모지로 받지 않는다(50035)."""
        for prompt in onboarding.PROMPTS:
            for option in prompt["options"]:
                with self.subTest(option=option["title"]):
                    self.assertGreaterEqual(ord(option["emoji_name"][0]), 0x1F000)

    def test_onboarding_never_points_at_a_hidden_channel(self):
        """숨긴 채널을 가리키는 옵션은 처음 온 사람에게 '없는 문'이다."""
        hidden = {c["key"] for c in manifest.channels() if c["private"]}
        declared = set(onboarding.DEFAULT_CHANNELS)
        for prompt in onboarding.PROMPTS:
            for option in prompt["options"]:
                declared |= set(option["channels"])
        self.assertEqual(declared & hidden, set())


if __name__ == "__main__":
    unittest.main()
