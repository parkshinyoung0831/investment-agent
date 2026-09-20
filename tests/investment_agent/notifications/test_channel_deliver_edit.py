"""원장 기반 전송(`deliver`)과 정정(`edit`)이 Discord에 어떤 요청을 보내는지 굳힌다."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from investment_agent.config import Config
from investment_agent.notifications.channels.contracts import DeliveryRejected, ForumThread
from investment_agent.notifications.channels.discord import DiscordChannel


class _Response:
    def __init__(self, status: int = 200, payload: dict | None = None) -> None:
        self.status_code = status
        self._payload = payload if payload is not None else {"id": "777"}
        self.headers: dict[str, str] = {}

    def json(self) -> dict:
        return self._payload


def _config() -> Config:
    return Config(env={"DISCORD_BOT_TOKEN": "t", "DISCORD_GUILD_ID": "1"}, dotenv_path=None, dotenv_loaded=False)


class DeliverEditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.posts: list[dict] = []
        self.patches: list[dict] = []
        self.listed_threads: list[dict] = []
        self.responses: list[_Response] = []

    def _post(self, url, **kwargs):
        self.posts.append({"url": url, **kwargs})
        return self.responses.pop(0) if self.responses else _Response()

    def _patch(self, url, **kwargs):
        self.patches.append({"url": url, **kwargs})
        return _Response()

    def _get(self, url, **kwargs):
        return _Response(payload={"threads": self.listed_threads})

    def _channel(self) -> DiscordChannel:
        return DiscordChannel(_config(), post=self._post, get=self._get, patch=self._patch)

    def test_a_plain_message_carries_an_enforced_nonce(self) -> None:
        delivery = self._channel().deliver(target="123", message={"content": "hi"}, nonce="abc")

        self.assertEqual((delivery.location_id, delivery.message_id, delivery.thread_id), ("123", "777", None))
        self.assertTrue(self.posts[0]["url"].endswith("/channels/123/messages"))
        self.assertEqual((self.posts[0]["json"]["nonce"], self.posts[0]["json"]["enforce_nonce"]), ("abc", True))

    def test_a_known_thread_receives_the_message_without_listing_threads(self) -> None:
        self.listed_threads = [{"id": "999", "parent_id": "123", "name": "avgo · old"}]

        delivery = self._channel().deliver(
            target="123", message={"content": "hi"}, thread=ForumThread("AVGO", "AVGO · Broadcom · 실적 기록"),
            known_thread_id="555", nonce="n",
        )

        self.assertTrue(self.posts[0]["url"].endswith("/channels/555/messages"))
        self.assertEqual((delivery.location_id, delivery.thread_id), ("555", "555"))

    def test_an_unknown_thread_is_found_by_its_title_before_creating_one(self) -> None:
        self.listed_threads = [{"id": "999", "parent_id": "123", "name": "AVGO · 브로드컴 · 실적 기록"}]

        delivery = self._channel().deliver(
            target="123", message={"content": "hi"}, thread=ForumThread("AVGO", "AVGO · Broadcom · 실적 기록"),
        )

        self.assertTrue(self.posts[0]["url"].endswith("/channels/999/messages"))
        self.assertEqual(delivery.thread_id, "999")

    def test_a_missing_thread_is_created_with_tags_and_no_nonce(self) -> None:
        delivery = self._channel().deliver(
            target="123", message={"content": "hi"}, thread=ForumThread("AVGO", "AVGO · Broadcom", ("7",)),
            nonce="n",
        )

        request = self.posts[0]
        self.assertTrue(request["url"].endswith("/channels/123/threads"))
        self.assertEqual(request["json"]["applied_tags"], ["7"])
        self.assertNotIn("nonce", request["json"]["message"])
        self.assertEqual((delivery.location_id, delivery.message_id, delivery.thread_id), ("777", "777", "777"))

    def test_a_vanished_known_thread_is_replaced_by_a_new_one(self) -> None:
        self.responses = [_Response(404, {"message": "Unknown Channel"}), _Response(payload={"id": "888"})]

        delivery = self._channel().deliver(
            target="123", message={"content": "hi"}, thread=ForumThread("AVGO", "AVGO · Broadcom"),
            known_thread_id="555",
        )

        self.assertEqual([p["url"].rsplit("/", 2)[-2:] for p in self.posts], [["555", "messages"], ["123", "threads"]])
        self.assertEqual(delivery.thread_id, "888")

    def test_edit_patches_the_existing_message(self) -> None:
        delivery = self._channel().edit(location_id="555", message_id="777", message={"content": "new"})

        self.assertTrue(self.patches[0]["url"].endswith("/channels/555/messages/777"))
        self.assertEqual(self.patches[0]["json"]["content"], "new")
        self.assertEqual((delivery.location_id, delivery.message_id), ("555", "777"))

    def test_edit_replaces_the_card_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            card = Path(folder) / "card.png"
            card.write_bytes(b"png")

            self._channel().edit(location_id="555", message_id="777", message={"content": "new"},
                                 attachment_path=str(card))

        request = self.patches[0]
        self.assertIn("files[0]", request["files"])
        self.assertIn('"attachments":[{"filename":"card.png","id":0}]', request["data"]["payload_json"])

    def test_a_rate_limit_is_a_retryable_rejection(self) -> None:
        self.responses = [_Response(429, {"retry_after": 12.5})]

        with self.assertRaises(DeliveryRejected) as caught:
            self._channel().deliver(target="123", message={"content": "hi"})

        self.assertTrue(caught.exception.is_retryable)
        self.assertEqual(caught.exception.retry_after, 12.5)


if __name__ == "__main__":
    unittest.main()
