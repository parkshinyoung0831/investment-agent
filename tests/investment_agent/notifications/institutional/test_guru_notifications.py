"""거장 13F 알림 — 제출은 사람 스레드에 한 번, 분기 요약은 한 장을 고쳐 가며 닿는다."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from investment_agent.notifications.institutional import run as guru_run
from investment_agent.notifications.institutional import state
from tests.investment_agent.notifications.fakes import memory_context

SUMMARY, FORUM = "111", "222"
PERIOD = "2026-06-30"


def _filing(cik: str, accession_no: str, name: str) -> dict:
    return {"manager_cik": cik, "accession_no": accession_no, "name": name, "period_end": PERIOD,
            "filing_date": "2099-08-14", "accepted_at": "2099-08-14T16:00:00+00:00"}


class GuruNotificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context, self.ledger, self.channel = memory_context()

    def _run(self, filings, *, forum: str | None = FORUM) -> int:
        def target(kind, **kwargs):
            if kind == "gurus_forum":
                if forum is None:
                    raise RuntimeError("not configured")
                return forum
            return kwargs.get("override") or SUMMARY

        with (
            patch.object(guru_run, "load_config", return_value=None),
            patch.object(guru_run, "discord_target", side_effect=target),
            patch.object(guru_run.dataset, "load_snapshot", return_value={}),
            patch.object(guru_run.card, "_latest_period", return_value=PERIOD),
            patch.object(guru_run.card, "_latest_filings", return_value=filings),
            patch.object(guru_run.card, "build_filing", side_effect=lambda _d, name: next(
                {"manager_cik": f["manager_cik"], "name": name} for f in filings if f["name"] == name)),
            patch.object(guru_run.card, "build_quarterly", return_value={}),
            patch.object(guru_run.embeds, "build_filing", side_effect=lambda ctx: {"title": ctx["name"]}),
            patch.object(guru_run.embeds, "build_quarterly", return_value={"title": "summary"}),
            patch.object(guru_run, "guru_tag_ids", return_value=[]),
        ):
            return guru_run.run(context=self.context)

    def test_each_filing_goes_to_its_managers_thread_once(self) -> None:
        filings = [_filing("0001067983", "0000950123-26-000001", "Warren Buffett")]

        self.assertEqual(self._run(filings), 2)
        self.assertEqual(self._run(filings), 0)
        filing, summary = self.channel.created
        self.assertEqual((filing["target"], filing["thread"].key), (FORUM, "0001067983"))
        self.assertEqual((summary["target"], summary["thread"]), (SUMMARY, None))

    def test_a_later_filing_edits_the_quarter_summary_instead_of_repeating_it(self) -> None:
        first = [_filing("0001067983", "0000950123-26-000001", "Warren Buffett")]
        self._run(first)

        delivered = self._run(first + [_filing("0001649339", "0001172661-26-000002", "Michael Burry")])

        self.assertEqual(delivered, 2)
        self.assertEqual(len(self.channel.edited), 1)
        self.assertEqual([c["message"]["embeds"][0]["title"] for c in self.channel.created],
                         ["Warren Buffett", "summary", "Michael Burry"])

    def test_without_a_forum_filings_fall_back_to_the_summary_channel(self) -> None:
        self._run([_filing("0001067983", "0000950123-26-000001", "Warren Buffett")], forum=None)

        filing = self.channel.created[0]
        self.assertEqual((filing["target"], filing["thread"]), (SUMMARY, None))

    def test_preflight_counts_what_the_ledger_has_not_sent(self) -> None:
        filings = [_filing("0001067983", "0000950123-26-000001", "Warren Buffett")]
        with (
            patch.object(state.dataset, "load_snapshot", return_value={}),
            patch.object(state.card, "_latest_period", return_value=PERIOD),
            patch.object(state.card, "_latest_filings", return_value=filings),
        ):
            before = state.pending_state(self.ledger)
            self._run(filings)
            after = state.pending_state(self.ledger)

        self.assertEqual((before["pending_filings"], before["summary_pending"], before["should_notify"]), (1, True, True))
        self.assertEqual((after["pending_filings"], after["summary_pending"], after["should_notify"]), (0, False, False))


if __name__ == "__main__":
    unittest.main()
