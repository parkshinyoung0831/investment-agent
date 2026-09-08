"""발표 예정 카드의 주 선택·불확실성 표기 회귀 테스트."""
from __future__ import annotations

import unittest
from datetime import date

from investment_agent.notifications.earnings_calendar import card
from investment_agent.reporting.services.earnings import schedule as metrics

# 2026-08-24는 월요일. 그 주는 8/24 ~ 8/30이다.
_MONDAY = date(2026, 8, 24)


def _snap(ticker: str, expected: str, *, snapshot: str, target: str = "2026-07-31") -> dict:
    return {
        "ticker": ticker,
        "snapshot_date": snapshot,
        "target_period_end": target,
        "expected_report_date": expected,
        "eps_avg": 1.23,
        "eps_analysts": 42,
        "revenue_avg": 46_500_000_000,
    }


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

    def test_no_row_is_ever_labelled_confirmed(self):
        # 출처가 확정 여부를 알려주지 않으므로 '확정' 등급 자체가 없어야 한다.
        self.assertNotIn("confirmed", metrics.build_rows(
            [_snap("NVDA", "2026-08-26", snapshot="2026-08-23")], [], {}, _MONDAY
        )[0]["confidence"])


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
