"""v1 macro core entrypoint의 중복 방지 계약."""
from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from investment_agent.notifications.macro import core as macro_core


class _Config:
    def require(self, *_names):
        return ("123",)


class CoreDedupTest(unittest.TestCase):
    def _run(self, *, already_claimed: bool, force: str = "") -> mock.Mock:
        store = mock.Mock()
        store.already_claimed.return_value = already_claimed
        store.load_core.return_value = [{"series_id": "SPY"}]
        channel = mock.Mock()
        service = mock.Mock()
        service.enqueue.return_value.status = "enqueued"
        env = {"MACRO_NOTIFY_FORCE": force} if force else {}
        with mock.patch.dict(macro_core.os.environ, env, clear=False), \
             mock.patch.object(macro_core, "load_config", return_value=_Config()), \
             mock.patch.object(macro_core, "shoot", new=mock.AsyncMock(return_value="card.png")), \
             mock.patch.object(macro_core, "_persist_png", return_value="card.png"):
            if not force:
                macro_core.os.environ.pop("MACRO_NOTIFY_FORCE", None)
            asyncio.run(macro_core.run(
                store=store, channel=channel, service=service, targets=("123",)
            ))
        channel.service = service
        return channel

    def test_first_send_of_the_day_goes_out(self):
        channel = self._run(already_claimed=False)
        channel.service.enqueue.assert_called_once()
        channel.service.run_pending.assert_called_once()

    def test_second_trigger_on_the_same_day_is_dropped(self):
        self._run(already_claimed=True).send_file.assert_not_called()

    def test_force_overrides_the_record(self):
        channel = self._run(already_claimed=True, force="on")
        channel.service.enqueue.assert_called_once()


if __name__ == "__main__":
    unittest.main()
