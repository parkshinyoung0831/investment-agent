"""실적 알림 — 속보·정밀 카드·주간 캘린더·발표 예정이 원장을 거쳐 한 번씩 닿는다."""
from __future__ import annotations

import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

if "supabase" not in sys.modules:
    supabase = types.ModuleType("supabase")
    supabase.Client = object
    supabase.create_client = lambda *_args, **_kwargs: None
    sys.modules["supabase"] = supabase

from investment_agent.notifications.earnings_calendar import candidates as calendar_candidates
from investment_agent.notifications.earnings_calendar import pending as calendar_pending
from investment_agent.notifications.earnings_calendar import run as calendar_run
from investment_agent.notifications.earnings_flash import run as flash_run
from investment_agent.notifications.earnings_report import run as report_run
from tests.investment_agent.notifications.fakes import memory_context

FORUM = "424242"


def _flash(accession_no: str = "0001045810-26-000101", ticker: str = "NVDA") -> dict:
    return {
        "flash": {"ticker": ticker, "accession_no": accession_no, "filed_at": "2026-08-26",
                  "available_at": "2026-08-26T20:05:00+00:00", "revenue_actual": 10.0, "eps_actual": 1.2},
        "names": {"name_ko": "엔비디아"},
    }


class FlashTest(unittest.TestCase):
    def _run(self, items, context) -> int:
        with (
            patch.object(flash_run, "load_config", return_value=None),
            patch.object(flash_run, "load_flash_candidates", return_value=items),
            patch.object(flash_run, "discord_target", return_value=FORUM),
            patch.object(flash_run, "build_flash_embed", return_value={"title": "flash"}),
        ):
            return flash_run.run(store=Mock(), context=context)

    def test_one_8k_reaches_its_ticker_thread_once(self) -> None:
        context, ledger, channel = memory_context()

        first = self._run([_flash()], context)
        again = self._run([_flash()], context)

        self.assertEqual((first, again), (1, 0))
        sent, = channel.created
        self.assertEqual((sent["target"], sent["thread"].key), (FORUM, "NVDA"))
        self.assertTrue(sent["thread"].name.startswith("NVDA · 엔비디아"))
        self.assertEqual(ledger.thread(FORUM, "NVDA"), "1001")


def _report_item(accession_no: str = "0001730168-26-000099") -> dict:
    return {
        "row": {"ticker": "AVGO", "accession_no": accession_no, "fiscal_year": 2026,
                "fiscal_period": "Q3", "period_end": "2026-08-02", "filed_at": "2026-09-10"},
        "names": {"sic_division": "Manufacturing"},
    }


class ReportTest(unittest.TestCase):
    def _run(self, items, context, *, target=None):
        shoot = AsyncMock(return_value="card.png")
        with (
            patch.object(report_run.candidates, "load_ready_filings", return_value=items),
            patch.object(report_run, "_extras_by_ticker", return_value={}),
            patch.object(report_run, "load_config", return_value=None),
            patch.object(report_run, "discord_target", return_value=FORUM) as discord_target,
            patch.object(report_run.card, "build", return_value=({"ticker": "AVGO"}, "caption")),
            patch.object(report_run.render, "render", return_value="<html></html>"),
            patch.object(report_run.render, "shoot_png", new=shoot),
            patch.object(report_run, "persist_png", return_value="card.png"),
            patch.object(report_run.embeds, "build_segments", return_value=[]),
            patch.object(report_run.routing, "thread_title", return_value="AVGO · Broadcom · 실적 기록"),
            patch.object(report_run, "_forum_tags", return_value=("9",)),
        ):
            delivered = report_run.run(context=context, target=target)
        return delivered, shoot, discord_target

    def test_the_card_goes_to_the_configured_forum_without_a_caller_target(self) -> None:
        """CLI와 하네스는 목적지를 넘기지 않는다. 해석된 포럼이 곧 목적지다."""
        context, _ledger, channel = memory_context()

        delivered, _shoot, discord_target = self._run([_report_item()], context)

        self.assertEqual(delivered, 1)
        discord_target.assert_called_once()
        sent, = channel.created
        self.assertEqual((sent["target"], sent["attachment_path"]), (FORUM, "card.png"))
        self.assertEqual((sent["thread"].key, sent["thread"].tags), ("AVGO", ("9",)))

    def test_an_already_sent_filing_is_not_rendered_again(self) -> None:
        """PNG 렌더는 원장이 이 실행에 맡긴 공시만 한다 — 이미 보낸 공시로 Playwright를 띄우지 않는다."""
        context, _ledger, _channel = memory_context()
        self._run([_report_item()], context)

        delivered, shoot, _ = self._run([_report_item()], context)

        self.assertEqual(delivered, 0)
        shoot.assert_not_awaited()


class CalendarTest(unittest.TestCase):
    ROWS = [{"ticker": "ABC", "expected": "2026-09-08", "target_fiscal_year": 2026,
             "target_fiscal_period": "Q3", "name": "ABC Corp", "form_expected": "10-Q", "confidence": "estimated"}]

    def _run(self, rows, context, today=date(2026, 9, 7)) -> int:
        with (
            patch.object(calendar_run, "load_config", return_value=None),
            patch.object(calendar_run, "collect", return_value=(rows, date(2026, 9, 4), "2026-W37")),
            patch.object(calendar_run, "discord_target", side_effect=lambda kind, **_k: {"fundamentals_calendar": "123"}.get(kind, FORUM)),
            patch.object(calendar_run.card, "build", return_value=({}, "caption")),
            patch.object(calendar_run, "render", return_value="<html />"),
            patch.object(calendar_run, "persist_png", return_value="calendar.png"),
            patch.object(calendar_run, "shoot_png", new=AsyncMock(return_value="rendered.png")),
            patch.object(calendar_run, "_schedule_tags", return_value=()),
        ):
            return calendar_run.run(store=Mock(), context=context, today=today)

    def test_the_week_card_and_each_schedule_go_out_once(self) -> None:
        context, _ledger, channel = memory_context()

        self.assertEqual(self._run(self.ROWS, context), 2)
        self.assertEqual(self._run(self.ROWS, context, today=date(2026, 9, 8)), 0)
        week, schedule = channel.created
        self.assertEqual((week["target"], week["attachment_path"]), ("123", "calendar.png"))
        self.assertEqual((schedule["target"], schedule["thread"].key), (FORUM, "ABC"))

    def test_a_moved_date_edits_the_week_card_and_notes_the_ticker_thread(self) -> None:
        context, _ledger, channel = memory_context()
        self._run(self.ROWS, context)
        moved = [{**self.ROWS[0], "expected": "2026-09-10"}]

        self.assertEqual(self._run(moved, context, today=date(2026, 9, 8)), 2)
        self.assertEqual(len(channel.edited), 1)
        self.assertEqual(len(channel.created), 3)

    def test_preflight_reports_what_the_ledger_has_not_sent(self) -> None:
        context, ledger, _channel = memory_context()
        store = Mock()
        with patch.object(calendar_candidates, "collect", return_value=(self.ROWS, None, "2026-W37")):
            before = calendar_candidates.pending_state(ledger, date(2026, 9, 7), store=store)
            self._run(self.ROWS, context)
            after = calendar_candidates.pending_state(ledger, date(2026, 9, 7), store=store)

        self.assertEqual(set(before), {"iso_week", "upcoming_releases", "schedule_updates", "should_notify"})
        self.assertTrue(before["should_notify"])
        self.assertFalse(after["should_notify"])

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "github-output.txt"
            with (
                patch.object(calendar_pending, "pending_state", return_value=before),
                patch.object(calendar_pending, "default_context", return_value=context),
                patch.object(calendar_pending, "load_config", return_value=None),
            ):
                self.assertEqual(calendar_pending.main(["--github-output", str(output)]), 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "should_notify=true\n")


if __name__ == "__main__":
    unittest.main()
