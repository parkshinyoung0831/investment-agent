"""발표 예정 카드의 주 선택·불확실성 표기 회귀 테스트."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from investment_agent.notifications.earnings_calendar import card, palette
from investment_agent.reporting.services.earnings import schedule as metrics

# 2026-08-24는 월요일. 그 주는 8/24 ~ 8/30이다.
_MONDAY = date(2026, 8, 24)


def _snap(
    ticker: str, expected: str, *, snapshot: str, target: str = "2026-07-31",
    last_seen: str | None = None, is_estimated: bool | None = None,
) -> dict:
    row = {
        "ticker": ticker,
        "snapshot_date": snapshot,
        "target_period_end": target,
        "expected_report_date": expected,
        "eps_avg": 1.23,
        "eps_analysts": 42,
        "revenue_avg": 46_500_000_000,
    }
    if last_seen is not None:
        row["last_seen_at"] = last_seen
    if is_estimated is not None:
        row["is_estimated"] = is_estimated
    return row


class WeekWindowTest(unittest.TestCase):
    def test_window_is_monday_to_sunday(self):
        self.assertEqual(metrics.week_window(_MONDAY), (date(2026, 8, 24), date(2026, 8, 30)))

    def test_window_is_stable_when_cron_drifts_into_the_week(self):
        # cron이 밀려 수요일에 돌아도 같은 주를 가리켜야 중복 발송이 안 난다.
        self.assertEqual(metrics.week_window(date(2026, 8, 26)), metrics.week_window(_MONDAY))
        self.assertEqual(metrics.iso_week(date(2026, 8, 26)), metrics.iso_week(_MONDAY))

    def test_only_this_week_is_selected(self):
        rows = metrics.build_rows(
            [
                _snap("NVDA", "2026-08-26", snapshot="2026-08-23"),
                _snap("AAPL", "2026-10-30", snapshot="2026-08-23", target="2026-09-30"),
            ],
            [],
            {},
            _MONDAY,
        )

        self.assertEqual([row["ticker"] for row in rows], ["NVDA"])
        self.assertEqual(rows[0]["days_until"], 2)


class ConfidenceTest(unittest.TestCase):
    def test_fresh_single_observation_is_estimated(self):
        rows = metrics.build_rows(
            [_snap("NVDA", "2026-08-26", snapshot="2026-08-23")], [], {}, _MONDAY
        )

        self.assertEqual(rows[0]["confidence"], "estimated")
        self.assertIsNone(rows[0]["previous_expected"])

    def test_stale_snapshot_is_flagged(self):
        rows = metrics.build_rows(
            [_snap("NVDA", "2026-08-26", snapshot="2026-08-01")], [], {}, _MONDAY
        )

        self.assertEqual(rows[0]["confidence"], "stale")

    def test_a_state_first_seen_long_ago_but_reconfirmed_recently_is_not_stale(self):
        # 예정 상태는 바뀔 때만 새 행이 생겨 snapshot_date는 "처음 본 날"에 머문다.
        # 매일 다시 확인되는 일정을 처음 본 날로만 재면 8일째부터 항상 stale이 된다.
        rows = metrics.build_rows(
            [_snap("NVDA", "2026-08-26", snapshot="2026-08-01",
                   last_seen="2026-08-23T01:30:00+00:00")],
            [], {}, _MONDAY,
        )

        self.assertEqual(rows[0]["confidence"], "estimated")
        self.assertEqual(rows[0]["last_seen_date"], date(2026, 8, 23))
        # 처음 본 날은 그대로 남는다 — 다른 화면이 관측 이력으로 읽는다.
        self.assertEqual(rows[0]["snapshot_date"], date(2026, 8, 1))

    def test_a_state_not_reconfirmed_for_over_a_week_is_stale(self):
        rows = metrics.build_rows(
            [_snap("NVDA", "2026-08-26", snapshot="2026-08-01",
                   last_seen="2026-08-10T01:30:00+00:00")],
            [], {}, _MONDAY,
        )

        self.assertEqual(rows[0]["confidence"], "stale")

    def test_missing_last_seen_falls_back_to_the_first_seen_date(self):
        # last_seen_at을 못 읽는 경로(대시보드 등)도 기존 규칙 그대로 판정한다.
        rows = metrics.build_rows(
            [_snap("NVDA", "2026-08-26", snapshot="2026-08-23")], [], {}, _MONDAY
        )

        self.assertEqual(rows[0]["confidence"], "estimated")
        self.assertEqual(rows[0]["last_seen_date"], date(2026, 8, 23))

    def test_unreadable_last_seen_never_breaks_the_card(self):
        rows = metrics.build_rows(
            [_snap("NVDA", "2026-08-26", snapshot="2026-08-23", last_seen="not-a-time")],
            [], {}, _MONDAY,
        )

        self.assertEqual(rows[0]["last_seen_date"], date(2026, 8, 23))

    def test_changed_expected_date_is_flagged_with_the_old_value(self):
        rows = metrics.build_rows(
            [
                _snap("NVDA", "2026-08-25", snapshot="2026-08-10"),
                _snap("NVDA", "2026-08-26", snapshot="2026-08-23"),
            ],
            [],
            {},
            _MONDAY,
        )

        self.assertEqual(rows[0]["confidence"], "shifted")
        self.assertEqual(rows[0]["previous_expected"], date(2026, 8, 25))
        self.assertEqual(rows[0]["expected"], date(2026, 8, 26))

    def test_a_date_the_source_marks_as_company_announced_gets_its_own_grade(self):
        """COST·NKE는 출처가 isEarningsDateEstimate=False로 준다. 그 사실을 버리고 전부
        "추정"으로 그리면 회사가 이미 공지한 일정도 불확실한 것처럼 읽힌다."""
        rows = metrics.build_rows(
            [_snap("COST", "2026-08-26", snapshot="2026-08-23", is_estimated=False)], [], {}, _MONDAY
        )

        self.assertEqual(rows[0]["confidence"], "announced")

    def test_an_unknown_flag_stays_estimated_rather_than_announced(self):
        rows = metrics.build_rows(
            [_snap("NVDA", "2026-08-26", snapshot="2026-08-23")], [], {}, _MONDAY
        )
        estimated = metrics.build_rows(
            [_snap("NVDA", "2026-08-26", snapshot="2026-08-23", is_estimated=True)], [], {}, _MONDAY
        )

        self.assertEqual(rows[0]["confidence"], "estimated")
        self.assertEqual(estimated[0]["confidence"], "estimated")

    def test_a_shifted_or_stale_date_is_never_shown_as_announced(self):
        shifted = metrics.build_rows(
            [
                _snap("NVDA", "2026-08-25", snapshot="2026-08-10", is_estimated=False),
                _snap("NVDA", "2026-08-26", snapshot="2026-08-23", is_estimated=False),
            ], [], {}, _MONDAY,
        )
        stale = metrics.build_rows(
            [_snap("NVDA", "2026-08-26", snapshot="2026-08-01", is_estimated=False)], [], {}, _MONDAY
        )

        self.assertEqual(shifted[0]["confidence"], "shifted")
        self.assertEqual(stale[0]["confidence"], "stale")

    def test_no_grade_claims_the_date_is_confirmed(self):
        self.assertNotIn("confirmed", palette.CONFIDENCE_LABELS)
        self.assertEqual(set(palette.CONFIDENCE_LABELS), {"estimated", "announced", "shifted", "stale"})
        self.assertNotIn("확정", "".join(palette.CONFIDENCE_LABELS.values()))


class PriorFilingTest(unittest.TestCase):
    def test_prior_year_actual_filing_is_attached(self):
        filings = [{
            "ticker": "NVDA",
            "fiscal_year": 2025,
            "fiscal_period": "Q2",
            "period_end": "2025-07-31",
            "filed_at": "2025-08-27",
        }]
        rows = metrics.build_rows(
            [_snap("NVDA", "2026-08-26", snapshot="2026-08-23")], filings, {}, _MONDAY
        )

        self.assertEqual(rows[0]["prior_filed_at"], date(2025, 8, 27))
        self.assertEqual(rows[0]["prior_period"], "2025 Q2")

    def test_estimated_target_period_end_still_finds_last_years_quarter(self):
        # 일정의 target_period_end는 추정이다. COST는 실제 분기말(8/30)보다 20일 이른
        # 8/10으로 들어와 작년 분기말(2025-08-31)과 21일 벌어졌고, 허용 폭 20일에 하루
        # 모자라 "기록 없음"이 됐다.
        filings = [{
            "ticker": "COST",
            "fiscal_year": 2025,
            "fiscal_period": "Q4",
            "period_end": "2025-08-31",
            "filed_at": "2025-10-08",
        }]
        rows = metrics.build_rows(
            [_snap("COST", "2026-08-26", snapshot="2026-08-23", target="2026-08-10")],
            filings, {}, _MONDAY,
        )

        self.assertEqual(rows[0]["prior_filed_at"], date(2025, 10, 8))

    def test_the_closest_quarter_wins_over_a_neighbouring_one(self):
        # 허용 폭을 넓혀도 인접 분기(약 91일 간격)와 헷갈리면 안 된다.
        filings = [
            {"ticker": "NVDA", "fiscal_year": 2025, "fiscal_period": "Q1",
             "period_end": "2025-04-30", "filed_at": "2025-05-28"},
            {"ticker": "NVDA", "fiscal_year": 2025, "fiscal_period": "Q2",
             "period_end": "2025-07-31", "filed_at": "2025-08-27"},
            {"ticker": "NVDA", "fiscal_year": 2025, "fiscal_period": "Q3",
             "period_end": "2025-10-31", "filed_at": "2025-11-20"},
        ]
        rows = metrics.build_rows(
            [_snap("NVDA", "2026-08-26", snapshot="2026-08-23", target="2026-08-10")],
            filings, {}, _MONDAY,
        )

        self.assertEqual(rows[0]["prior_period"], "2025 Q2")

    def test_a_quarter_beyond_half_a_quarter_away_is_not_last_years_quarter(self):
        # 넓힌 허용 폭에도 위쪽 경계가 있어야 한다. 멀리 있는 다른 분기를 "작년 같은
        # 분기"로 내밀면 없는 것보다 나쁘다. 기준은 작년 같은 날(2025-08-10)이다.
        for label, period_end in (("50일 뒤", "2025-09-29"), ("102일 앞", "2025-04-30")):
            with self.subTest(label):
                filings = [{"ticker": "NVDA", "fiscal_year": 2025, "fiscal_period": "Q1",
                            "period_end": period_end, "filed_at": "2025-11-01"}]
                rows = metrics.build_rows(
                    [_snap("NVDA", "2026-08-26", snapshot="2026-08-23", target="2026-08-10")],
                    filings, {}, _MONDAY,
                )

                self.assertIsNone(rows[0]["prior_filed_at"])

    def test_unrelated_period_is_not_matched(self):
        filings = [{
            "ticker": "NVDA",
            "fiscal_year": 2025,
            "fiscal_period": "Q4",
            "period_end": "2026-01-31",
            "filed_at": "2026-02-25",
        }]
        rows = metrics.build_rows(
            [_snap("NVDA", "2026-08-26", snapshot="2026-08-23")], filings, {}, _MONDAY
        )

        self.assertIsNone(rows[0]["prior_filed_at"])


class CardTest(unittest.TestCase):
    def test_card_context_carries_labels_and_tokens(self):
        rows = metrics.build_rows(
            [_snap("NVDA", "2026-08-26", snapshot="2026-08-23")],
            [],
            {"NVDA": {"name_ko": "엔비디아", "name": "NVIDIA Corp", "sic_industry": "Technology"}},
            _MONDAY,
        )
        ctx, caption = card.build(rows, _MONDAY, date(2026, 8, 23))

        self.assertEqual(ctx["window_label"], "8/24 ~ 8/30")
        self.assertEqual(ctx["rows"][0]["name"], "엔비디아")
        self.assertEqual(ctx["rows"][0]["confidence_label"], "예정")
        self.assertEqual(ctx["rows"][0]["eps_label"], "$1.23")
        self.assertEqual(ctx["rows"][0]["revenue_avg"], "$46.5B")
        self.assertIn("NVDA", caption)
        # 템플릿에 hex를 인라인하지 않도록 palette가 토큰을 넘긴다.
        self.assertEqual(ctx["tokens"]["primary"], "#3182f6")

    def test_missing_consensus_degrades_to_none(self):
        snapshot = _snap("NVDA", "2026-08-26", snapshot="2026-08-23")
        snapshot["eps_avg"] = None
        snapshot["revenue_avg"] = None
        rows = metrics.build_rows([snapshot], [], {}, _MONDAY)
        ctx, _ = card.build(rows, _MONDAY, date(2026, 8, 23))

        self.assertIsNone(ctx["rows"][0]["eps_label"])
        self.assertIsNone(ctx["rows"][0]["revenue_avg"])


class _Store:
    """collect가 부르는 reader 계약만 갖춘 대역."""

    def __init__(self, snapshots: list[dict]) -> None:
        self._snapshots = snapshots
        self.asked_today: date | None = None

    def watchlist_members(self) -> list[dict]:
        return [{"ticker": "NVDA"}]

    def schedule_snapshots(self, tickers: list[str], *, today: date | None = None) -> list[dict]:
        self.asked_today = today
        return self._snapshots

    def prior_filings(self, tickers: list[str]) -> list[dict]:
        return []

    def load_names(self, tickers: list[str]) -> dict:
        return {}


class CollectTest(unittest.TestCase):
    def test_card_reference_date_is_when_the_schedule_was_last_confirmed(self):
        from investment_agent.notifications.earnings_calendar import candidates

        store = _Store([_snap("NVDA", "2026-08-26", snapshot="2026-08-01",
                              last_seen="2026-08-23T01:30:00+00:00")])
        rows, reference, week = candidates.collect(store, _MONDAY)

        self.assertEqual([row["ticker"] for row in rows], ["NVDA"])
        # 처음 본 날(8/1)이 아니라 마지막 재확인일이어야 카드의 "기준일"이 사실이다.
        self.assertEqual(reference, date(2026, 8, 23))
        self.assertEqual(week, "2026-W35")
        # 소비 기한(7일 신선도)과 컨센서스 조회 창이 같은 today를 봐야 cron이 밀려도 재현된다.
        self.assertEqual(store.asked_today, _MONDAY)

    def _collect_at(self, instant: datetime):
        from unittest import mock

        from investment_agent.notifications.earnings_calendar import candidates

        store = _Store([_snap("NVDA", "2026-09-22", snapshot="2026-09-01",
                              last_seen="2026-09-20T01:30:00+00:00")])
        with mock.patch("investment_agent.platform.clock.utc_now", return_value=instant):
            return candidates.collect(store), store

    def test_the_scheduled_sunday_night_utc_run_picks_the_week_that_is_starting(self):
        """워크플로는 일요일 23:10 UTC(=월요일 08:10 KST)에 돈다. UTC 날짜로 주를 고르면
        방금 끝난 주를 골라 이번 주 종목이 0건이 되는데, 예외도 로그도 없이 카드만 안 나간다."""
        (rows, _, week), store = self._collect_at(datetime(2026, 9, 20, 23, 10, tzinfo=timezone.utc))

        self.assertEqual(week, "2026-W39")
        self.assertEqual([row["ticker"] for row in rows], ["NVDA"])
        self.assertEqual(store.asked_today, date(2026, 9, 21))

    def test_a_run_still_on_sunday_in_korea_keeps_the_ending_week(self):
        """일요일 14:59 UTC는 아직 일요일 23:59 KST다 — 주 경계는 한국 날짜로만 넘어간다."""
        (rows, _, week), _ = self._collect_at(datetime(2026, 9, 20, 14, 59, tzinfo=timezone.utc))

        self.assertEqual(week, "2026-W38")
        self.assertEqual(rows, [])


class CustomWindowTest(unittest.TestCase):
    """대시보드가 쓰는 임의 구간 조회가 Discord 주간 규칙을 바꾸지 않아야 한다."""

    def test_week_rule_is_unchanged_and_delegates_to_the_window_helper(self):
        snapshots = [
            _snap("NVDA", "2026-08-26", snapshot="2026-08-23"),
            _snap("AAPL", "2026-10-30", snapshot="2026-08-23", target="2026-09-30"),
        ]
        start, end = metrics.week_window(_MONDAY)
        self.assertEqual(
            metrics.build_rows(snapshots, [], {}, _MONDAY),
            metrics.build_rows_in_window(snapshots, [], {}, _MONDAY, start=start, end=end),
        )

    def test_wider_window_includes_past_and_future_events(self):
        snapshots = [
            _snap("PAST", "2026-08-19", snapshot="2026-08-23"),
            _snap("NVDA", "2026-08-26", snapshot="2026-08-23"),
            _snap("FAR", "2026-09-20", snapshot="2026-08-23", target="2026-08-31"),
        ]
        rows = metrics.build_rows_in_window(
            snapshots,
            [],
            {},
            _MONDAY,
            start=date(2026, 8, 17),
            end=date(2026, 9, 30),
        )

        self.assertEqual([row["ticker"] for row in rows], ["PAST", "NVDA", "FAR"])
        self.assertEqual(rows[0]["days_until"], -5)

    def test_group_by_target_keeps_one_row_per_estimate_period(self):
        snapshots = [
            _snap("NVDA", "2026-08-26", snapshot="2026-08-20", target="2026-07-31"),
            _snap("NVDA", "2026-11-25", snapshot="2026-08-23", target="2026-10-31"),
        ]
        window = {"start": date(2026, 8, 1), "end": date(2026, 12, 31)}

        collapsed = metrics.build_rows_in_window(snapshots, [], {}, _MONDAY, **window)
        expanded = metrics.build_rows_in_window(
            snapshots, [], {}, _MONDAY, group_by_target=True, **window
        )

        # 티커별 최신 스냅샷 1건만 남기면 앞 분기가 사라진다.
        self.assertEqual([row["target_period_end"] for row in collapsed], [date(2026, 10, 31)])
        self.assertEqual(
            [row["target_period_end"] for row in expanded],
            [date(2026, 7, 31), date(2026, 10, 31)],
        )

    def test_reversed_window_is_rejected(self):
        with self.assertRaises(ValueError):
            metrics.build_rows_in_window(
                [], [], {}, _MONDAY, start=date(2026, 9, 1), end=date(2026, 8, 1)
            )


if __name__ == "__main__":
    unittest.main()
