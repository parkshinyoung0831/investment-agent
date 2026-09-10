"""구독 대상이 캘린더 outbox 행으로 전달되는지 검증한다."""
from __future__ import annotations

import asyncio
import unittest
from datetime import date
from unittest.mock import AsyncMock, Mock, patch

from investment_agent.notifications.earnings_calendar import run


class EarningsCalendarRoutingTest(unittest.TestCase):
    def test_run_uses_injected_subscription_target(self) -> None:
        store = Mock(database=Mock())
        store.sent_weeks.return_value = set()
        service = Mock()
        service.enqueue.return_value = Mock(status="enqueued")
        config = Mock()
        rows = [{"ticker": "ABC", "expected_label": "예정", "confidence": "high"}]

        with (
            patch.object(run, "load_config", return_value=config),
            patch.object(run, "collect", return_value=(rows, date(2026, 9, 4), "2026-W36")),
            patch.object(run, "force_resend", return_value=False),
            patch.object(run.card, "build", return_value=({}, "caption")),
            patch.object(run, "render", return_value="<html />"),
            patch.object(run, "persist_png", return_value="calendar.png"),
            patch.object(run, "shoot_png", new=AsyncMock(return_value="rendered.png")),
            patch.object(run, "DiscordChannel"),
        ):
            result = asyncio.run(run.run(store=store, service=service, target="123"))

        self.assertEqual(result, 0)
        self.assertEqual(service.enqueue.call_args.kwargs["target"], "123")
        service.run_pending.assert_called_once()

    def test_sent_week_still_posts_new_per_ticker_schedule(self) -> None:
        store = Mock(database=Mock())
        store.sent_weeks.return_value = {"2026-W36"}
        service = Mock()
        config = Mock()
        rows = [{"ticker": "ABC", "expected": "2026-09-08", "target_fiscal_year": 2026,
                 "target_fiscal_period": "Q3", "name": "ABC"}]

        with (
            patch.object(run, "load_config", return_value=config),
            patch.object(run, "collect", return_value=(rows, date(2026, 9, 4), "2026-W36")),
            patch.object(run, "force_resend", return_value=False),
            patch.object(run, "_post_schedules", new=AsyncMock(return_value=1)) as post,
            patch.object(run.card, "build") as build,
        ):
            result = asyncio.run(run.run(store=store, service=service, target="123"))

        self.assertEqual(result, 0)
        post.assert_awaited_once()
        build.assert_not_called()
        service.run_pending.assert_called_once()


if __name__ == "__main__":
    unittest.main()
