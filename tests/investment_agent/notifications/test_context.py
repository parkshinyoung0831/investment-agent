"""운영 알림 조립은 발행 엔진 밖에서 이뤄진다."""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from investment_agent.notifications import context
from investment_agent.notifications.channels.contracts import DeliveryRejected, DeliveryUnknown
from investment_agent.notifications.channels.discord import DiscordChannel
from investment_agent.notifications.engine import PublishContext


class NotificationContextTest(unittest.TestCase):
    def test_default_context_composes_the_existing_ledger_and_discord_adapter(self) -> None:
        config = object()
        database = object()
        ledger = object()
        channel = object()
        with (
            patch.object(context, "configured_database", return_value=database) as database_factory,
            patch.object(context, "PostgresNotificationLedger", return_value=ledger) as ledger_factory,
            patch.object(context, "DiscordChannel", return_value=channel) as channel_factory,
            patch.object(context, "new_owner", return_value="owner"),
        ):
            result = context.default_context(config)

        self.assertEqual(result, PublishContext(ledger, channel, "owner"))
        database_factory.assert_called_once_with(config)
        ledger_factory.assert_called_once_with(database)
        channel_factory.assert_called_once_with(config)

    def test_discord_adapter_uses_the_shared_delivery_outcomes(self) -> None:
        with self.assertRaises(DeliveryRejected):
            DiscordChannel._checked_status(Mock(status_code=429, json=lambda: {"retry_after": 1}))
        self.assertEqual(DeliveryRejected.__module__, "investment_agent.notifications.channels.contracts")
        self.assertEqual(DeliveryUnknown.__module__, "investment_agent.notifications.channels.contracts")


if __name__ == "__main__":
    unittest.main()
