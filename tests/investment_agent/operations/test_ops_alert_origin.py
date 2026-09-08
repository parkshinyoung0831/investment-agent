"""운영 알림은 **실행된 곳**으로 목적지를 가른다.

Actions 워크플로 실패와 로컬 하네스 실패는 고치는 방법이 완전히 다르다 —
전자는 재실행이나 워크플로 수정, 후자는 그 컴퓨터다. 전에는 둘 다
`DISCORD_WEBHOOK_OPS` 하나로 나가 한 채널에서 섞였고, "지금 내가 할 수 있는 것"이
보이지 않았다.

부르는 쪽이 목적지를 고르게 하면 한 자리만 빠뜨려도 그 알림이 조용히 엉뚱한 곳으로
간다. 그래서 런타임이 이미 아는 사실(`GITHUB_ACTIONS`)로 정한다.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from investment_agent.operations.runtime import _ops_webhook

_ENV = ("GITHUB_ACTIONS", "DISCORD_WEBHOOK_OPS",
        "DISCORD_WEBHOOK_OPS_ACTIONS", "DISCORD_WEBHOOK_OPS_LOCAL")


def _with(**values: str):
    base = {name: "" for name in _ENV}
    return mock.patch.dict(os.environ, {**base, **values}, clear=False)


class OpsWebhookOriginTest(unittest.TestCase):
    def test_on_actions_it_uses_the_actions_webhook(self) -> None:
        with _with(GITHUB_ACTIONS="true", DISCORD_WEBHOOK_OPS_ACTIONS="A",
                   DISCORD_WEBHOOK_OPS_LOCAL="L"):
            self.assertEqual(("A", "actions", "DISCORD_WEBHOOK_OPS_ACTIONS"), _ops_webhook())

    def test_off_actions_it_uses_the_local_webhook(self) -> None:
        with _with(DISCORD_WEBHOOK_OPS_ACTIONS="A", DISCORD_WEBHOOK_OPS_LOCAL="L"):
            self.assertEqual(("L", "local", "DISCORD_WEBHOOK_OPS_LOCAL"), _ops_webhook())

    def test_it_falls_back_rather_than_going_quiet(self) -> None:
        """갈라 두기 전에 알림이 먼저 조용해지는 것이 더 나쁘다."""
        with _with(GITHUB_ACTIONS="true", DISCORD_WEBHOOK_OPS="OLD"):
            self.assertEqual(("OLD", "actions", "DISCORD_WEBHOOK_OPS"), _ops_webhook())

    def test_with_nothing_configured_it_reports_the_name_it_wanted(self) -> None:
        with _with():
            webhook, origin, name = _ops_webhook()
            self.assertEqual("", webhook)
            self.assertEqual("local", origin)
            self.assertEqual("DISCORD_WEBHOOK_OPS", name)


class OriginTravelsWithTheMessageTest(unittest.TestCase):
    """전용 webhook이 아직 없으면 둘이 한 채널로 떨어진다 — 그때도 구분돼야 한다."""

    def test_the_sender_name_carries_the_origin(self) -> None:
        from investment_agent.operations import runtime

        sent: dict = {}

        class _Response:
            def raise_for_status(self) -> None: ...

        def post(url, json, timeout):  # noqa: A002 - requests 시그니처
            sent.update(url=url, payload=json)
            return _Response()

        with _with(DISCORD_WEBHOOK_OPS="OLD"), mock.patch.object(runtime.requests, "post", post):
            self.assertTrue(runtime.notify_ops("boom"))
        self.assertEqual("ATLAS ops · local", sent["payload"]["username"])


if __name__ == "__main__":
    unittest.main()
