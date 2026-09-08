"""자동매매 보고 채널 선언 — 카드가 조용히 안 나가는 배치를 막는다."""
from __future__ import annotations

import unittest

from investment_agent.notifications.discord_admin import manifest, roles

CATEGORY = "🤖 AI INVESTOR"


def _by_key():
    return {channel["key"]: channel for channel in manifest.channels()}


class InvestmentChannelsTest(unittest.TestCase):
    def test_report_and_trade_channels_are_declared(self):
        channels = _by_key()

        self.assertEqual(channels["ai_reports"]["env"], "DISCORD_CHANNEL_AI_REPORTS")
        self.assertEqual(channels["ai_trades"]["env"], "DISCORD_CHANNEL_AI_TRADES")

    def test_they_live_in_the_ai_investor_category(self):
        channels = _by_key()

        self.assertEqual(channels["ai_reports"]["category"], CATEGORY)
        self.assertEqual(channels["ai_trades"]["category"], CATEGORY)

    def test_the_approval_channel_moves_in_beside_them(self):
        """판단 → 승인 → 체결이 한 카테고리에서 순서대로 읽히게 한다."""
        channels = _by_key()

        self.assertEqual(channels["ai_approvals"]["category"], CATEGORY)
        self.assertEqual(channels["ai_approvals"]["env"], "DISCORD_CHANNEL_AI_APPROVALS")

    def test_the_category_is_private(self):
        channels = _by_key()

        self.assertTrue(channels["ai_reports"]["private"])
        self.assertTrue(channels["ai_trades"]["private"])

    def test_card_bot_can_still_see_the_report_channels(self):
        """private 채널에 봇 allow가 안 붙으면 카드가 에러 없이 사라진다."""
        names = {_by_key()[key]["name"] for key in ("ai_reports", "ai_trades")}
        allowed = {
            item["target"] for item in roles.overwrites()
            if item["role"] == "cardbot" and item["allow"] & roles.VIEW_CHANNEL
        }

        self.assertEqual(names - allowed, set())

    def test_card_bot_is_still_shut_out_of_the_approval_channel(self):
        approval_name = _by_key()["ai_approvals"]["name"]
        declared = [item for item in roles.overwrites() if item["target"] == approval_name]
        cardbot = next(item for item in declared if item["role"] == "cardbot")

        self.assertTrue(cardbot["deny"] & roles.VIEW_CHANNEL)

    def test_no_everyone_deny_is_attached_to_the_card_channels_themselves(self):
        """@everyone 채널 deny는 카테고리 private 처리로만 붙어야 한다."""
        names = {_by_key()[key]["name"] for key in ("ai_reports", "ai_trades")}
        denied = [
            item for item in roles.overwrites()
            if item["target"] in names
            and item["role"] == roles.EVERYONE_KEY
            and item["kind"] == "channel"
        ]

        # private 카테고리 처리로 붙는 deny 외에 추가 deny를 손으로 달지 않았는지 본다.
        self.assertTrue(all(item["deny"] == roles.PRIVATE_DENY for item in denied))


if __name__ == "__main__":
    unittest.main()
