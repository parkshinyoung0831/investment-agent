"""발표 세션(BMO/AMC) 분류·타겟 선정과 발송 상호 배제.

하루 한 번 훑던 시절에는 장전 발표가 최대 15시간 늦게 잡혔고, 로컬 하네스와
GitHub Actions가 겹치면 같은 속보가 두 번 나갔다. 아래 테스트가 그 둘을 막는다.
"""
from __future__ import annotations

from datetime import datetime, timezone
import importlib
import unittest
from unittest import mock

from investment_agent.data.fundamentals.application.select_session_targets import (
    latest_schedule_by_ticker,
    select_session_targets,
    select_timed_targets,
)
from investment_agent.data.fundamentals.domain.services.classify_report_session import (
    AMC,
    BMO,
    DMH,
    ET,
    UNKNOWN,
    classify_session,
    collect_window,
    is_placeholder_time,
    is_within_collect_window,
    resolve_session,
    session_from_history,
)


class SessionClassification(unittest.TestCase):
    def test_market_hours_split_bmo_from_amc(self):
        """09:30 개장·16:00 마감이 경계다. 실측 JPM 06:00·NVDA 16:00."""
        cases = {
            6: BMO, 7: BMO, 8: BMO, 9: BMO,
            10: DMH, 12: DMH, 15: DMH,
            16: AMC, 17: AMC, 20: AMC,
        }
        for hour, expected in cases.items():
            got = classify_session(datetime(2026, 10, 13, hour, 0, tzinfo=ET))
            self.assertEqual(got, expected, f"{hour:02d}:00 ET")

    def test_open_and_close_edges(self):
        self.assertEqual(classify_session(datetime(2026, 10, 13, 9, 29, tzinfo=ET)), BMO)
        self.assertEqual(classify_session(datetime(2026, 10, 13, 9, 30, tzinfo=ET)), DMH)
        self.assertEqual(classify_session(datetime(2026, 10, 13, 15, 59, tzinfo=ET)), DMH)
        self.assertEqual(classify_session(datetime(2026, 10, 13, 16, 0, tzinfo=ET)), AMC)

    def test_missing_time_is_unknown_not_guessed(self):
        """시각을 모르면 장전으로 넘겨짚지 않는다 — 넓은 창으로 처리한다."""
        self.assertEqual(classify_session(None), UNKNOWN)
        self.assertTrue(
            is_within_collect_window(UNKNOWN, datetime(2026, 10, 13, 12, 0, tzinfo=ET))
        )

    def test_utc_input_is_converted_not_read_raw(self):
        """UTC 13:00은 ET 09:00이라 장전이다. 변환 없이 읽으면 장중으로 잘못 본다."""
        utc_noon = datetime(2026, 10, 13, 13, 0, tzinfo=timezone.utc)
        self.assertEqual(classify_session(utc_noon), BMO)


class SessionTargetSelection(unittest.TestCase):
    ROWS = [
        {"ticker": "JPM", "snapshot_date": "2026-10-10",
         "expected_report_date": "2026-10-13", "expected_session": BMO},
        {"ticker": "NVDA", "snapshot_date": "2026-10-10",
         "expected_report_date": "2026-10-13", "expected_session": AMC},
        {"ticker": "STALE", "snapshot_date": "2026-09-01",
         "expected_report_date": "2026-09-05", "expected_session": BMO},
    ]

    def _at(self, hour: int) -> list[str]:
        return select_session_targets(
            self.ROWS, datetime(2026, 10, 13, hour, 0, tzinfo=ET)
        )["tickers"]

    def test_only_the_open_session_is_collected(self):
        self.assertEqual(self._at(7), ["JPM"])
        self.assertEqual(self._at(17), ["NVDA"])

    def test_nothing_is_collected_outside_every_window(self):
        self.assertEqual(self._at(23), [])

    def test_expected_date_outside_the_window_is_skipped(self):
        self.assertNotIn("STALE", self._at(7))

    def test_newest_snapshot_wins(self):
        """예정일은 자주 바뀐다. 오래된 관측으로 수집을 걸면 안 된다."""
        rows = [
            {"ticker": "X", "snapshot_date": "2026-10-01",
             "expected_report_date": "2026-10-13", "expected_session": BMO},
            {"ticker": "X", "snapshot_date": "2026-10-11",
             "expected_report_date": "2026-10-20", "expected_session": AMC},
        ]
        self.assertEqual(latest_schedule_by_ticker(rows)["X"]["expected_session"], AMC)
        picked = select_session_targets(
            rows, datetime(2026, 10, 13, 7, 0, tzinfo=ET))["tickers"]
        self.assertEqual(picked, [])

    def test_unknown_session_is_failed_open(self):
        """시간 메타데이터가 없다고 발표를 놓치는 쪽이 더 나쁘다."""
        rows = [{"ticker": "Q", "snapshot_date": "2026-10-12",
                 "expected_report_date": "2026-10-13", "expected_session": UNKNOWN}]
        self.assertEqual(
            select_session_targets(rows, datetime(2026, 10, 13, 12, 0, tzinfo=ET))["tickers"],
            ["Q"],
        )
        self.assertEqual(
            select_session_targets(
                rows, datetime(2026, 10, 13, 12, 0, tzinfo=ET), include_unknown=False
            )["tickers"],
            [],
        )


class TimedTargetSelection(unittest.TestCase):
    """정확 시각·추정 시각·날짜만 아는 일정을 서로 다른 창으로 다룬다."""

    def _rows(self) -> list[dict]:
        return [
            {
                "ticker": "EXACT",
                "snapshot_date": "2026-10-12",
                "expected_report_date": "2026-10-13",
                "expected_report_at": "2026-10-13T08:00:00-04:00",
                "expected_session": BMO,
                "is_estimated": False,
            },
            {
                "ticker": "ESTIMATE",
                "snapshot_date": "2026-10-12",
                "expected_report_date": "2026-10-13",
                "expected_report_at": "2026-10-13T16:00:00-04:00",
                "expected_session": AMC,
                "is_estimated": True,
            },
            {
                "ticker": "DATEONLY",
                "snapshot_date": "2026-10-12",
                "expected_report_date": "2026-10-13",
                "expected_report_at": "2026-10-13T00:00:00-04:00",
                "expected_session": UNKNOWN,
                "is_estimated": False,
            },
        ]

    def test_exact_time_uses_a_short_window(self):
        selected = select_timed_targets(
            self._rows(), datetime(2026, 10, 13, 7, 55, tzinfo=ET)
        )
        self.assertIn("EXACT", selected["tickers"])
        self.assertEqual(selected["by_confidence"]["exact"], ["EXACT"])

    def test_exact_time_does_not_open_too_early(self):
        selected = select_timed_targets(
            self._rows(), datetime(2026, 10, 13, 7, 49, tzinfo=ET)
        )
        self.assertNotIn("EXACT", selected["tickers"])

    def test_estimated_time_gets_a_wider_window(self):
        selected = select_timed_targets(
            self._rows(), datetime(2026, 10, 13, 14, 30, tzinfo=ET)
        )
        self.assertIn("ESTIMATE", selected["tickers"])
        self.assertEqual(selected["by_confidence"]["estimated"], ["ESTIMATE"])

    def test_date_only_anchor_uses_the_safe_day_window(self):
        selected = select_timed_targets(
            self._rows(), datetime(2026, 10, 13, 12, 0, tzinfo=ET)
        )
        self.assertEqual(selected["tickers"], ["DATEONLY"])
        self.assertEqual(selected["by_confidence"], {"date_only": ["DATEONLY"]})

    def test_date_only_anchor_does_not_consume_the_minute_precision_budget(self):
        selected = select_timed_targets(
            self._rows(), datetime(2026, 10, 13, 12, 1, tzinfo=ET)
        )
        self.assertNotIn("DATEONLY", selected["tickers"])


class EarningsFlashOutbox(unittest.TestCase):
    """속보는 전송 전에 outbox에 스냅샷을 등록한다."""

    def test_claim_is_taken_before_sending(self):
        """outbox 스냅샷 등록이 디스패치보다 먼저 일어난다."""
        flash_run = importlib.import_module("investment_agent.notifications.earnings_flash.run")

        order: list[str] = []
        item = {
            "flash": {"ticker": "NVDA", "accession_no": "ACC-1",
                      "fiscal_year": 2026, "fiscal_period": "Q3", "filed_at": "2026-08-26"},
            "names": {"name_ko": "엔비디아"},
        }
        service = mock.MagicMock()
        service.enqueue.side_effect = lambda **_kwargs: (
            order.append("enqueue"), mock.Mock(status="enqueued")
        )[1]
        service.run_pending.side_effect = lambda: (
            order.append("dispatch"), []
        )[1]
        with (
            mock.patch.object(flash_run, "load_pending_flash", return_value=[item]),
            mock.patch.object(flash_run, "build_flash_embed", return_value={}),
        ):
            flash_run.run(store=mock.Mock(database=mock.Mock()), service=service, targets=("1",))
        self.assertEqual(order, ["enqueue", "dispatch"])

    def test_failed_send_releases_the_claim(self):
        """디스패치 결과가 불명이어도 실행기는 성공으로 세지 않는다."""
        flash_run = importlib.import_module("investment_agent.notifications.earnings_flash.run")

        item = {
            "flash": {"ticker": "NVDA", "accession_no": "ACC-1",
                      "fiscal_year": 2026, "fiscal_period": "Q3", "filed_at": "2026-08-26"},
            "names": {},
        }
        service = mock.MagicMock()
        service.enqueue.return_value = mock.Mock(status="enqueued")
        service.run_pending.return_value = [mock.Mock(status="unknown", producer="fundamentals")]
        with (
            mock.patch.object(flash_run, "load_pending_flash", return_value=[item]),
            mock.patch.object(flash_run, "build_flash_embed", return_value={}),
        ):
            sent = flash_run.run(store=mock.Mock(database=mock.Mock()), service=service, targets=("1",))
        self.assertEqual(sent, 0)
        service.enqueue.assert_called_once()
        service.run_pending.assert_called_once()


class EarningsWatchStatus(unittest.TestCase):
    """재시도 뒤에도 남은 수집·매핑 실패만 최종 상태에 반영한다."""

    @staticmethod
    def _watch_module():
        return importlib.import_module("investment_agent.operations.commands.watch_earnings")

    @staticmethod
    def _empty_report() -> dict:
        return {
            "company": {"filings": [], "failures": []},
            "segments": {},
            "report_ready": False,
            "failures": [],
        }

    def test_missing_cik_is_a_failed_run(self):
        watch = self._watch_module()
        from investment_agent.data.fundamentals.infrastructure.supabase import company_financials
        from investment_agent.data.fundamentals.application import detect_earnings_events

        with (
            mock.patch.object(watch, "configure_logging"),
            mock.patch.object(
                watch, "_targets", return_value=(["MISS"], {"any": ["MISS"]}, {})
            ),
            mock.patch.object(company_financials, "gating_universe", return_value=[]),
            mock.patch.object(
                detect_earnings_events,
                "detect_earnings_events",
                return_value={"rows": 0, "filings_discovered": 0, "failures": []},
            ),
            mock.patch.object(watch, "_sync_detected_reports", return_value=self._empty_report()),
        ):
            self.assertEqual(watch.main(["--session", "any"]), 1)

    def test_recovered_collection_failure_does_not_poison_final_attempt(self):
        watch = self._watch_module()
        from investment_agent.data.fundamentals.infrastructure.supabase import company_financials
        from investment_agent.data.fundamentals.application import detect_earnings_events

        first = {
            "rows": 0,
            "filings_discovered": 0,
            "failures": [{"ticker": "AAA", "error": "temporary"}],
        }
        recovered = {"rows": 0, "filings_discovered": 0, "failures": []}
        with (
            mock.patch.object(watch, "configure_logging"),
            mock.patch.object(
                watch, "_targets", return_value=(["AAA"], {"any": ["AAA"]}, {})
            ),
            mock.patch.object(
                company_financials,
                "gating_universe",
                return_value=[{"ticker": "AAA", "cik": "1"}],
            ),
            mock.patch.object(
                detect_earnings_events,
                "detect_earnings_events",
                side_effect=[first, recovered],
            ),
            mock.patch.object(watch, "_sync_detected_reports", return_value=self._empty_report()),
            mock.patch.object(watch.time, "sleep"),
        ):
            result = watch.main([
                "--session", "any", "--poll-attempts", "2",
                "--poll-interval-seconds", "15",
            ])

        self.assertEqual(result, 0)

    def test_terminal_collection_failure_returns_nonzero(self):
        watch = self._watch_module()
        from investment_agent.data.fundamentals.infrastructure.supabase import company_financials
        from investment_agent.data.fundamentals.application import detect_earnings_events

        failed = {
            "rows": 0,
            "filings_discovered": 0,
            "failures": [{"ticker": "AAA", "error": "SEC unavailable"}],
        }
        with (
            mock.patch.object(watch, "configure_logging"),
            mock.patch.object(
                watch, "_targets", return_value=(["AAA"], {"any": ["AAA"]}, {})
            ),
            mock.patch.object(
                company_financials,
                "gating_universe",
                return_value=[{"ticker": "AAA", "cik": "1"}],
            ),
            mock.patch.object(
                detect_earnings_events, "detect_earnings_events", return_value=failed
            ),
            mock.patch.object(watch, "_sync_detected_reports", return_value=self._empty_report()),
        ):
            self.assertEqual(watch.main(["--session", "any"]), 1)


class YahooPlaceholderTime(unittest.TestCase):
    """야후는 시각 미공지 발표에 15:00 ET를 넣는다. 그대로 믿으면 창이 어긋난다."""

    def _at(self, hour: int, day: int = 13) -> datetime:
        return datetime(2026, 10, day, hour, 0, tzinfo=ET)

    def test_placeholder_hour_is_recognised(self):
        self.assertTrue(is_placeholder_time(self._at(15)))
        self.assertFalse(is_placeholder_time(self._at(16)))
        self.assertFalse(is_placeholder_time(self._at(8)))

    def test_history_overrides_the_placeholder(self):
        """실측: AMAT는 과거 24회가 16:00인데 다음 예정만 15:00이었다."""
        amc_history = [self._at(16, d) for d in (1, 2, 3)]
        self.assertEqual(resolve_session(self._at(15), amc_history), AMC)

        bmo_history = [self._at(8, d) for d in (1, 2, 3)]  # BRK-B 패턴
        self.assertEqual(resolve_session(self._at(15), bmo_history), BMO)

    def test_confirmed_time_ignores_history(self):
        """확정 시각이 있으면 과거 습관이 달라도 그대로 믿는다."""
        self.assertEqual(resolve_session(self._at(16), [self._at(8, 1)] * 5), AMC)

    def test_no_history_falls_back_to_a_wide_window(self):
        """이력이 없으면 장중으로 남지만, 창은 하루 전체다 — 놓치는 쪽이 더 나쁘다."""
        self.assertEqual(resolve_session(self._at(15), []), DMH)
        start, end = collect_window(DMH)
        self.assertEqual((start.hour, end.hour), (6, 20))
        self.assertTrue(is_within_collect_window(DMH, self._at(16)))

    def test_history_ignores_its_own_placeholders(self):
        """과거 행에 섞인 자리표시는 최빈값 계산에서 빠진다."""
        self.assertEqual(
            session_from_history([self._at(15, 1), self._at(16, 2), self._at(16, 3)]),
            AMC,
        )
        self.assertEqual(session_from_history([self._at(15, 1)]), UNKNOWN)


class WorkflowSchedule(unittest.TestCase):
    def test_both_sessions_have_a_safety_net_cron(self):
        from pathlib import Path

        text = Path(".github/workflows/fundamentals_earnings_watch.yml").read_text(
            encoding="utf-8"
        )
        # 13:00 UTC = 22:00 KST(장전 마감 후), 21:30 UTC = 06:30 KST(장후 마감 후)
        self.assertIn('cron: "0 13 * * 1-5"', text)
        self.assertIn('cron: "0 22 * * 1-5"', text)
        self.assertIn("investment_agent.operations.commands.watch_earnings", text)


if __name__ == "__main__":
    unittest.main()
