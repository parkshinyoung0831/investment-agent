"""포럼 채널로 카드를 보내는 경로를 굳힌다.

Discord는 포럼 채널의 `/messages`를 **400으로 거절한다** — 첫 글이 곧 스레드라
`/threads`로 만들어야 한다. 선언(`manifest.py`)은 실적·전략·거장 채널을 포럼으로
정해 두었는데 전송은 `/messages`만 쓰고 있었고, 그 실패는 outbox의 실패 행으로만
남아 ETL은 초록으로 보인다.
"""
from __future__ import annotations

import unittest

from investment_agent.config import Config
from investment_agent.notifications.channels.discord import DiscordChannel


class _Response:
    def __init__(self, status: int = 200, payload: dict | None = None) -> None:
        self.status_code = status
        self._payload = payload if payload is not None else {"id": "777"}
        self.headers: dict[str, str] = {}

    def json(self) -> dict:
        return self._payload


def _config() -> Config:
    # 스레드 조회는 길드 단위 API를 쓴다 — 길드 ID가 없으면 조회 자체가 막힌다.
    return Config(env={"DISCORD_BOT_TOKEN": "t", "DISCORD_GUILD_ID": "1"},
                  dotenv_path=None, dotenv_loaded=False)


class ForumDeliveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[dict] = []

    def _post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return _Response()

    def _get(self, url, **kwargs):
        """스레드 조회 스텁. 주입하지 않으면 단위 테스트가 실제 Discord로 나간다."""
        return _Response(payload={"threads": []})

    def _send(self, **kwargs) -> str:
        channel = DiscordChannel(_config(), post=self._post, get=self._get)
        return channel.send(target="123", message={"content": "hi"}, **kwargs)

    def test_a_plain_channel_still_posts_a_message(self) -> None:
        self._send()
        self.assertTrue(self.calls[0]["url"].endswith("/channels/123/messages"))
        self.assertNotIn("name", self.calls[0]["json"])

    def test_a_forum_destination_creates_a_thread(self) -> None:
        self._send(thread_name="2026 Q2 · 워런 버핏")
        call = self.calls[0]
        self.assertTrue(call["url"].endswith("/channels/123/threads"))
        self.assertEqual("2026 Q2 · 워런 버핏", call["json"]["name"])
        # 스레드의 첫 글은 검증을 통과한 그 메시지 그대로다.
        self.assertEqual("hi", call["json"]["message"]["content"])
        self.assertEqual({"parse": []}, call["json"]["message"]["allowed_mentions"])

    def test_thread_titles_are_cut_to_the_discord_limit(self) -> None:
        """100자를 넘기면 Discord가 400으로 거절한다 — 카드가 통째로 안 나간다."""
        self._send(thread_name="가" * 250)
        self.assertEqual(100, len(self.calls[0]["json"]["name"]))

    def test_forum_tags_are_sent_as_ids(self) -> None:
        self._send(thread_name="스레드", thread_tags=("9001", "9002"))
        self.assertEqual(["9001", "9002"], self.calls[0]["json"]["applied_tags"])

    def test_no_tags_means_the_field_is_absent(self) -> None:
        """빈 배열을 보내면 이미 붙은 태그를 지우는 뜻이 될 수 있다."""
        self._send(thread_name="스레드")
        self.assertNotIn("applied_tags", self.calls[0]["json"])

    def test_an_empty_thread_name_is_refused_before_the_request(self) -> None:
        from investment_agent.notifications.channels.discord import DeliveryRejected

        channel = DiscordChannel(_config(), post=self._post, get=self._get)
        with self.assertRaises(DeliveryRejected):
            channel.send(target="123", message={"content": "hi"}, thread_name="   ")
        self.assertEqual([], self.calls)


class ForumThreadsAreReusedTest(unittest.TestCase):
    """포럼은 "종목 1개 = 스레드 1개에 누적"이 설계다.

    `/threads`는 부를 때마다 새 스레드를 만든다. 그대로 두면 같은 종목의 분기
    공시가 제목만 같은 별개 스레드로 흩어지고, 누적해 읽는다는 이유가 사라진다.
    """

    def setUp(self) -> None:
        self.calls: list[dict] = []

    def _channel(self, threads: dict) -> DiscordChannel:
        def post(url, **kwargs):
            self.calls.append({"url": url, **kwargs})
            return _Response(payload={"id": "555"})

        def get(url, **kwargs):
            payload = {"threads": threads.get("active" if "guilds" in url else "archived", [])}
            return _Response(payload=payload)

        return DiscordChannel(_config(), post=post, get=get)

    def test_an_existing_thread_receives_the_message(self) -> None:
        channel = self._channel({"active": [
            {"id": "900", "name": "AAPL · Apple · 실적 기록", "parent_id": "123"},
        ]})
        channel.send(target="123", message={"content": "hi"},
                     thread_name="AAPL · Apple · 실적 기록")
        self.assertTrue(self.calls[0]["url"].endswith("/channels/900/messages"))
        self.assertNotIn("name", self.calls[0]["json"])

    def test_an_archived_thread_still_counts_as_existing(self) -> None:
        """분기마다 오는 공시 사이에 스레드는 보관 상태가 된다."""
        channel = self._channel({"archived": [
            {"id": "901", "name": "MSFT · Microsoft · 실적 기록"},
        ]})
        channel.send(target="123", message={"content": "hi"},
                     thread_name="MSFT · Microsoft · 실적 기록")
        self.assertTrue(self.calls[0]["url"].endswith("/channels/901/messages"))

    def test_a_thread_from_another_forum_is_not_reused(self) -> None:
        channel = self._channel({"active": [
            {"id": "902", "name": "AAPL · Apple · 실적 기록", "parent_id": "999"},
        ]})
        channel.send(target="123", message={"content": "hi"},
                     thread_name="AAPL · Apple · 실적 기록")
        self.assertTrue(self.calls[0]["url"].endswith("/channels/123/threads"))

    def test_a_new_thread_is_reused_within_the_same_run(self) -> None:
        """같은 실행에서 두 장을 보내면 두 번째는 방금 만든 스레드로 간다."""
        channel = self._channel({})
        for _ in range(2):
            channel.send(target="123", message={"content": "hi"},
                         thread_name="NVDA · NVIDIA · 실적 기록")
        self.assertTrue(self.calls[0]["url"].endswith("/channels/123/threads"))
        self.assertTrue(self.calls[1]["url"].endswith("/channels/555/messages"))

    def test_a_lookup_failure_creates_rather_than_dropping_the_card(self) -> None:
        """스레드가 하나 느는 것이 카드가 아예 안 나가는 것보다 낫다."""
        def get(url, **kwargs):
            raise RuntimeError("boom")

        def post(url, **kwargs):
            self.calls.append({"url": url, **kwargs})
            return _Response()

        DiscordChannel(_config(), post=post, get=get).send(
            target="123", message={"content": "hi"}, thread_name="T")
        self.assertTrue(self.calls[0]["url"].endswith("/channels/123/threads"))


class OutboxCarriesForumDestinationTest(unittest.TestCase):
    """전송은 나중에 일어난다. 목적지를 그때 다시 계산하면 선언이 바뀐 사이
    같은 알림이 다른 채널로 간다."""

    def test_thread_fields_travel_in_the_stored_payload(self) -> None:
        from investment_agent.notifications import outbox

        captured: dict = {}

        class _Outbox(outbox.Outbox):
            def __init__(self) -> None:  # noqa: D107 - 저장 없이 payload만 본다
                pass

            def enqueue(self, **kwargs):
                captured.update(kwargs)
                return True

        from investment_agent.notifications.service import NotificationService

        service = NotificationService(_Outbox(), object(), clock=lambda: __import__(
            "datetime").datetime(2026, 9, 8, tzinfo=__import__("datetime").timezone.utc))
        service.enqueue(
            producer="institutional", notification_key="k", kind="filing",
            target="123", message={"content": "hi"}, thread_name="2026 Q2 · 워런 버핏",
        )
        self.assertEqual("2026 Q2 · 워런 버핏", captured["thread_name"])


if __name__ == "__main__":
    unittest.main()


class ThreadIdentityTest(unittest.TestCase):
    """스레드를 다시 찾는 키는 표시명이 바뀌어도 같아야 한다.

    제목 전체를 키로 쓰던 동안, 한글명을 채우자 `AAPL · Apple Inc. · 실적 기록`
    옆에 `AAPL · 애플 · 실적 기록`이 새로 생겨 종목마다 스레드가 둘이 됐다.
    카드는 정상 발송되므로 오류로는 드러나지 않고, 포럼을 열어야 보인다.
    """

    EXISTING = {"threads": [
        {"id": "555", "name": "AAPL · Apple Inc. · 실적 기록", "parent_id": "123"},
    ]}

    def setUp(self) -> None:
        self.calls: list[dict] = []

    def _send(self, thread_name: str) -> None:
        def post(url, **kwargs):
            self.calls.append({"url": url, **kwargs})
            return _Response()

        def get(url, **kwargs):
            return _Response(payload=self.EXISTING)

        DiscordChannel(_config(), post=post, get=get).send(
            target="123", message={"content": "hi"}, thread_name=thread_name,
        )

    def test_a_renamed_company_keeps_its_thread(self) -> None:
        self._send("AAPL · 애플 · 실적 기록")
        # 새 스레드를 만들지 않고 기존 스레드 안에 이어 붙인다.
        self.assertTrue(self.calls[0]["url"].endswith("/channels/555/messages"))
        self.assertNotIn("name", self.calls[0]["json"])

    def test_a_different_ticker_still_gets_its_own_thread(self) -> None:
        self._send("MSFT · 마이크로소프트 · 실적 기록")
        self.assertTrue(self.calls[0]["url"].endswith("/channels/123/threads"))

    def test_the_match_key_drops_the_display_name(self) -> None:
        from investment_agent.notifications.channels.discord import _thread_match_key
        self.assertEqual("aapl", _thread_match_key("AAPL · Apple Inc. · 실적 기록"))
        self.assertEqual("aapl", _thread_match_key("AAPL · 애플 · 실적 기록"))
        # 거장 포럼은 사람 이름이 곧 첫 마디다.
        self.assertEqual("워런 버핏", _thread_match_key("워런 버핏 · 13F 기록"))
