"""공시 직전 컨센서스 선택·조립 회귀 테스트.

여기서 지키는 건 전부 "틀려도 카드는 그려지고 숫자만 거짓이 되는" 규칙이다.
"""
from __future__ import annotations

import unittest
from datetime import date

from investment_agent.notifications.earnings_report import card, charts, consensus


def _snap(
    ticker: str = "NVDA",
    *,
    snapshot_date: str,
    target: str,
    source: str = "yfinance",
    target_fiscal_year: int = 2026,
    target_fiscal_period: str = "Q3",
    source_horizon: str = "q+0",
    eps_avg: float = 2.08,
    revenue_avg: float = 91_800_000_000.0,
    **extra,
) -> dict:
    return {
        "ticker": ticker,
        "snapshot_date": snapshot_date,
        "target_fiscal_year": target_fiscal_year,
        "target_fiscal_period": target_fiscal_period,
        "target_period_end": target,
        "source": source,
        "snapshot_kind": "observed",
        "source_horizon": source_horizon,
        "eps_avg": eps_avg,
        "eps_low": 2.03,
        "eps_high": 2.20,
        "eps_analysts": 40,
        "revenue_avg": revenue_avg,
        "revenue_low": 89_000_000_000.0,
        "revenue_high": 94_000_000_000.0,
        "revenue_analysts": 38,
        "revisions_up_30d": 4,
        "revisions_down_30d": 0,
        "revisions_up_7d": 1,
        "revisions_down_7d": 0,
        **extra,
    }


class PickSnapshotTest(unittest.TestCase):
    def test_latest_snapshot_before_filing_wins(self):
        snaps = [
            _snap(snapshot_date="2026-07-16", target="2026-07-31", eps_avg=2.00),
            _snap(snapshot_date="2026-08-15", target="2026-07-31", eps_avg=2.08),
        ]
        picked = consensus.pick_snapshot(
            snaps, "NVDA", "2026-08-26", fiscal_year=2026, fiscal_period="Q3"
        )

        self.assertEqual(str(picked["snapshot_date"]), "2026-08-15")

    def test_snapshot_after_filing_is_rejected(self):
        """발표 뒤 값은 '기대'가 아니라 결과를 반영한 값이다."""
        snaps = [_snap(snapshot_date="2026-08-27", target="2026-07-31")]

        self.assertIsNone(
            consensus.pick_snapshot(
                snaps, "NVDA", "2026-08-26", fiscal_year=2026, fiscal_period="Q3"
            )
        )

    def test_fiscal_identity_selects_the_snapshot(self):
        """회계기간 식별자는 날짜 근사치 대신 저장된 절대 기간 키로 맞춘다."""
        snaps = [_snap("AAPL", snapshot_date="2026-07-20", target="2026-06-30",
                       target_fiscal_period="Q2")]
        picked = consensus.pick_snapshot(
            snaps, "AAPL", "2026-07-31", fiscal_year=2026, fiscal_period="Q2"
        )

        self.assertIsNotNone(picked)

    def test_annual_identity_remains_annual(self):
        snaps = [_snap("AAPL", snapshot_date="2026-02-15", target="2025-12-31",
                       target_fiscal_year=2025, target_fiscal_period="FY",
                       source_horizon="fy+0")]

        picked = consensus.pick_snapshot(
            snaps, "AAPL", "2026-02-20", fiscal_year=2025, fiscal_period="FY"
        )

        self.assertIsNotNone(picked)

    def test_neighbouring_quarter_is_not_picked(self):
        snaps = [_snap("AAPL", snapshot_date="2026-07-20", target="2026-09-30")]

        self.assertIsNone(
            consensus.pick_snapshot(
                snaps, "AAPL", "2026-07-31", fiscal_year=2026, fiscal_period="Q2"
            )
        )

    def test_missing_fiscal_identity_is_rejected(self):
        snaps = [_snap(snapshot_date="2026-08-15", target="2026-07-31")]

        self.assertIsNone(
            consensus.pick_snapshot(
                snaps, "NVDA", "2026-08-26", fiscal_year=None, fiscal_period=None
            )
        )

    def test_backfilled_seed_is_rejected(self):
        """eps_trend 소급분은 수집 시점의 target을 달고 있어 과거 분기에 못 붙인다."""
        snaps = [
            _snap(snapshot_date="2026-08-14", target="2026-07-31", source="yfinance:eps_trend",
                  snapshot_kind="reconstructed"),
        ]

        self.assertIsNone(
            consensus.pick_snapshot(
                snaps, "NVDA", "2026-08-26", fiscal_year=2026, fiscal_period="Q3"
            )
        )

    def test_seed_and_true_snapshot_together_pick_the_true_one(self):
        snaps = [
            _snap(snapshot_date="2026-08-20", target="2026-07-31", source="yfinance:eps_trend",
                  snapshot_kind="reconstructed", eps_avg=9.99),
            _snap(snapshot_date="2026-08-15", target="2026-07-31", eps_avg=2.08),
        ]
        picked = consensus.pick_snapshot(
            snaps, "NVDA", "2026-08-26", fiscal_year=2026, fiscal_period="Q3"
        )

        self.assertEqual(picked["eps_avg"], 2.08)

    def test_stale_snapshot_beyond_lead_cap_is_rejected(self):
        snaps = [_snap(snapshot_date="2026-01-05", target="2026-07-31")]

        self.assertIsNone(
            consensus.pick_snapshot(
                snaps, "NVDA", "2026-08-26", fiscal_year=2026, fiscal_period="Q3"
            )
        )

    def test_other_ticker_is_never_borrowed(self):
        snaps = [_snap("TSLA", snapshot_date="2026-08-15", target="2026-07-31")]

        self.assertIsNone(
            consensus.pick_snapshot(
                snaps, "NVDA", "2026-08-26", fiscal_year=2026, fiscal_period="Q3"
            )
        )


class SurpriseRowsTest(unittest.TestCase):
    def _history(self) -> list[dict]:
        return [
            {"ticker": "NVDA", "quarter_end": "2025-10-31", "eps_estimate": 1.25,
             "eps_actual": 1.30, "surprise_pct": 0.0346},
            {"ticker": "NVDA", "quarter_end": "2026-01-31", "eps_estimate": 1.53,
             "eps_actual": 1.62, "surprise_pct": 0.0532},
            {"ticker": "NVDA", "quarter_end": "2026-04-30", "eps_estimate": 1.77,
             "eps_actual": 1.87, "surprise_pct": 0.0554},
        ]

    def test_future_quarters_are_excluded(self):
        """공시 시점에는 아직 모르는 분기를 카드에 실으면 안 된다."""
        rows = consensus.surprise_rows(self._history(), "2026-01-31")

        self.assertEqual([str(r["quarter_end"]) for r in rows], ["2025-10-31", "2026-01-31"])

    def test_stored_surprise_is_treated_as_a_fraction(self):
        rows = consensus.surprise_rows(self._history(), "2026-04-30")

        self.assertAlmostEqual(rows[-1]["surprise"], 0.0554)
        self.assertTrue(rows[-1]["reliable"])

    def test_surprise_is_derived_when_not_stored(self):
        history = [{"ticker": "X", "quarter_end": "2026-01-31", "eps_estimate": 2.0,
                    "eps_actual": 2.2, "surprise_pct": None}]
        rows = consensus.surprise_rows(history, "2026-01-31")

        self.assertAlmostEqual(rows[0]["surprise"], 0.1)

    def test_wildly_off_basis_is_flagged_unreliable(self):
        """관측된 실제 사례(GOOGL +214%/+92%, UBER -82%)를 서프라이즈로 단정하지 않는다."""
        for estimate, actual, stored in (
            (2.89, 9.11, 2.1423),      # GOOGL 2026-06-30
            (2.667, 5.11, 0.9159),     # GOOGL 2026-03-31 — 임계 0.5로 낮춰야 걸린다
            (0.712, 0.13, -0.8174),    # UBER 2026-03-31
            (0.007, 0.23, 31.62),      # INTC 2025-09-30 — 분모가 0에 가까운 경우
        ):
            with self.subTest(estimate=estimate, actual=actual):
                rows = consensus.surprise_rows(
                    [{"ticker": "X", "quarter_end": "2026-06-30", "eps_estimate": estimate,
                      "eps_actual": actual, "surprise_pct": stored}],
                    "2026-06-30",
                )
                self.assertFalse(rows[0]["reliable"])

    def test_ordinary_surprises_stay_reliable(self):
        """정상 범위(AAPL 3~7%, TSLA -38%)까지 잘라내면 블록이 쓸모없어진다."""
        for estimate, actual, stored in (
            (1.89, 2.02, 0.0674),      # AAPL 2026-06-30
            (0.5353, 0.33, -0.3835),   # TSLA 2026-06-30 — 진짜 큰 미스
        ):
            with self.subTest(estimate=estimate, actual=actual):
                rows = consensus.surprise_rows(
                    [{"ticker": "X", "quarter_end": "2026-06-30", "eps_estimate": estimate,
                      "eps_actual": actual, "surprise_pct": stored}],
                    "2026-06-30",
                )
                self.assertTrue(rows[0]["reliable"])


class BuildTest(unittest.TestCase):
    _ROW = {
        "ticker": "NVDA", "period_end": "2026-07-26", "filed_at": "2026-08-26",
        "fiscal_year": 2026, "fiscal_period": "Q3",
        "revenue": 93_000_000_000.0,
    }

    def test_returns_none_when_nothing_is_available(self):
        """estimates 커버리지가 100%가 아니다 — 없으면 블록이 통째로 빠져야 한다."""
        self.assertIsNone(consensus.build(self._ROW, [], []))

    def test_eps_actual_comes_from_surprise_history_not_gaap(self):
        """GAAP 계산값과 조정 컨센서스를 빼면 없는 서프라이즈가 생긴다."""
        snaps = [_snap(snapshot_date="2026-08-15", target="2026-07-31")]
        history = [{"ticker": "NVDA", "quarter_end": "2026-07-26", "eps_estimate": 2.08,
                    "eps_actual": 2.25, "surprise_pct": 0.0817}]
        built = consensus.build(self._ROW, snaps, history)

        self.assertEqual(built["eps"]["actual"], 2.25)
        self.assertAlmostEqual(built["eps"]["surprise"], 0.0817)

    def test_revenue_surprise_uses_core_wide_revenue(self):
        snaps = [_snap(snapshot_date="2026-08-15", target="2026-07-31")]
        built = consensus.build(self._ROW, snaps, [])

        self.assertEqual(built["revenue"]["actual"], 93_000_000_000.0)
        self.assertAlmostEqual(built["revenue"]["surprise"], (93 - 91.8) / 91.8, places=4)

    def test_position_inside_low_high_range(self):
        snaps = [_snap(snapshot_date="2026-08-15", target="2026-07-31")]
        built = consensus.build(self._ROW, snaps, [])

        # low 89B, high 94B, actual 93B -> 0.8
        self.assertAlmostEqual(built["revenue"]["position"], 0.8, places=2)

    def test_history_only_still_builds(self):
        """컨센서스 스냅샷이 없어도 서프라이즈 이력만으로 블록을 낼 수 있다."""
        history = [
            {"ticker": "NVDA", "quarter_end": "2026-01-31", "eps_estimate": 1.5,
             "eps_actual": 1.6, "surprise_pct": 0.066},
            {"ticker": "NVDA", "quarter_end": "2026-04-30", "eps_estimate": 1.7,
             "eps_actual": 1.8, "surprise_pct": 0.058},
        ]
        built = consensus.build(self._ROW, [], history)

        self.assertIsNotNone(built)
        self.assertIsNone(built["eps"])
        self.assertEqual(len(built["history"]), 2)

    def test_revisions_are_carried_with_net(self):
        snaps = [_snap(snapshot_date="2026-08-15", target="2026-07-31",
                       revisions_up_30d=7, revisions_down_30d=14)]
        built = consensus.build(self._ROW, snaps, [])

        self.assertEqual(built["revisions"]["net"], -7)


class ViewTest(unittest.TestCase):
    def test_none_stays_none(self):
        self.assertIsNone(card._expectation_view(None))

    def test_rising_estimates_change_the_reading(self):
        view = card._expectation_view({
            "snapshot_date": date(2026, 8, 15), "lead_days": 11,
            "eps": None, "revenue": None,
            "revisions": {"up": 9, "down": 2, "up_7d": 1, "down_7d": 0, "net": 7},
            "history": [],
        })

        self.assertIn("오르는 중", view["revisions"]["text"])
        self.assertIn("실망", view["revisions"]["text"])
        # 상향이 '좋다'는 뜻이 아니므로 색으로 단정하지 않는다.
        self.assertNotIn("color", view["revisions"])

    def test_seven_day_over_thirty_day_is_flagged_not_silently_fixed(self):
        """7일은 30일에 포함되므로 넘을 수 없다 — 넘으면 출처가 따로 갱신한 것이다.

        실측: UBER 상향 7일 7 대 30일 6, TSLA 하향 16 대 14, GOOGL 하향 18 대 15.
        값을 깎아 맞추면 출처에 없는 숫자가 되고, 줄을 지우면 어긋난 사실이 숨는다.
        """
        for up, down, up7, down7 in ((6, 5, 7, 4), (5, 14, 2, 16)):
            with self.subTest(up7=up7, down7=down7):
                view = card._expectation_view({
                    "snapshot_date": date(2026, 8, 15), "lead_days": 11,
                    "eps": None, "revenue": None, "history": [],
                    "revisions": {"up": up, "down": down, "up_7d": up7,
                                  "down_7d": down7, "net": up - down},
                })
                rev = view["revisions"]
                self.assertTrue(rev["inconsistent_7d"])
                # 원본 값은 그대로 남는다(깎지 않는다).
                self.assertEqual(rev["up_7d"], up7)
                self.assertEqual(rev["down_7d"], down7)

    def test_consistent_seven_day_is_not_flagged(self):
        view = card._expectation_view({
            "snapshot_date": date(2026, 8, 15), "lead_days": 11,
            "eps": None, "revenue": None, "history": [],
            "revisions": {"up": 4, "down": 0, "up_7d": 2, "down_7d": 0, "net": 4},
        })

        self.assertFalse(view["revisions"]["inconsistent_7d"])

    def test_missing_seven_day_is_not_flagged(self):
        view = card._expectation_view({
            "snapshot_date": date(2026, 8, 15), "lead_days": 11,
            "eps": None, "revenue": None, "history": [],
            "revisions": {"up": 4, "down": 0, "up_7d": None, "down_7d": None, "net": 4},
        })

        self.assertFalse(view["revisions"]["inconsistent_7d"])

    def test_unreliable_surprise_is_not_coloured_or_shown(self):
        view = card._expectation_view({
            "snapshot_date": date(2026, 8, 15), "lead_days": 11,
            "eps": {"estimate": 2.89, "low": 2.6, "high": 3.1, "analysts": 40,
                    "actual": 9.11, "surprise": 2.14, "reliable": False, "position": None},
            "revenue": None, "revisions": None, "history": [],
        })

        self.assertIsNone(view["eps"]["surprise"])
        self.assertEqual(view["eps"]["color"], "#7c828a")   # palette.MUTED
        self.assertTrue(view["eps"]["unreliable"])

    def test_basis_is_always_stated(self):
        """카드에 GAAP EPS도 함께 있으므로 무엇을 비교했는지 밝혀야 한다."""
        view = card._expectation_view({
            "snapshot_date": date(2026, 8, 15), "lead_days": 11,
            "eps": {"estimate": 2.08, "low": 2.03, "high": 2.2, "analysts": 40,
                    "actual": 2.25, "surprise": 0.0817, "reliable": True, "position": 0.5},
            "revenue": None, "revisions": None, "history": [],
        })

        self.assertEqual(view["eps"]["basis"], "조정 기준")
        self.assertEqual(view["eps"]["surprise"], "+8.2%")


class ComboOverlayTest(unittest.TestCase):
    def _history(self) -> list[dict]:
        return [
            {"ticker": "N", "fiscal_year": 2026, "fiscal_period": "Q1", "period_end": f"2026-0{i}-30",
             "revenue": 90_000_000_000.0 + i, "operating_income_loss": 5e10, "net_income": 4e10}
            for i in range(1, 5)
        ]

    def test_no_consensus_leaves_no_estimate_mark(self):
        chart = charts.combo(self._history(), [])

        self.assertIsNone(chart["financials"]["estimate"])

    def test_estimate_mark_is_placed_and_flags_beat(self):
        chart = charts.combo(self._history(), [], {
            "estimate": 80_000_000_000.0, "low": 78e9, "high": 82e9,
        })
        mark = chart["financials"]["estimate"]

        self.assertIsNotNone(mark)
        self.assertTrue(mark["beat"])          # 실제 90B > 기대 80B
        self.assertIsNotNone(mark["y_low"])

    def test_estimate_outside_bar_range_still_fits_the_axis(self):
        """수염이 축 밖으로 잘리면 '기대보다 훨씬 위'가 안 보인다."""
        chart = charts.combo(self._history(), [], {
            "estimate": 200e9, "low": 190e9, "high": 210e9,
        })
        mark = chart["financials"]["estimate"]

        self.assertGreaterEqual(mark["y_high"], 0)
        self.assertLessEqual(mark["y_low"], chart["financials"]["h"])


class NextQuarterTest(unittest.TestCase):
    def test_forward_estimate_comes_from_the_same_snapshot(self):
        """발표 뒤 갱신된 값을 섞으면 '그때의 기대'가 아니라 지금 기대가 된다."""
        picked = _snap(snapshot_date="2026-08-15", target="2026-07-31")
        snaps = [
            picked,
            {**_snap(snapshot_date="2026-08-15", target="2026-10-31", eps_avg=2.40,
                    target_fiscal_period="Q4", source_horizon="q+1")},
            {**_snap(snapshot_date="2026-09-30", target="2026-10-31", eps_avg=9.99,
                    target_fiscal_period="Q4", source_horizon="q+1")},
        ]
        forward = consensus.pick_next_quarter(snaps, picked)

        self.assertEqual(forward["estimate"], 2.40)
        self.assertIn("10월", forward["label"])

    def test_no_forward_row_is_fine(self):
        picked = _snap(snapshot_date="2026-08-15", target="2026-07-31")

        self.assertIsNone(consensus.pick_next_quarter([picked], picked))

    def test_build_carries_the_forward_estimate(self):
        picked = _snap(snapshot_date="2026-08-15", target="2026-07-31")
        snaps = [picked, {**_snap(snapshot_date="2026-08-15", target="2026-10-31",
                                  target_fiscal_period="Q4", source_horizon="q+1",
                                  eps_avg=2.40)}]
        built = consensus.build(
            {"ticker": "NVDA", "period_end": "2026-07-26", "filed_at": "2026-08-26",
             "fiscal_year": 2026, "fiscal_period": "Q3",
             "revenue": 93e9},
            snaps, [],
        )

        self.assertEqual(built["next_quarter"]["estimate"], 2.40)


class EpsBlendTest(unittest.TestCase):
    def _history(self) -> list[dict]:
        return [
            {"ticker": "N", "fiscal_year": 2026, "fiscal_period": f"Q{i}",
             "period_end": f"2026-0{i * 3}-30", "net_income": 1_000_000_000.0 * i,
             "shares_fully_diluted_average": 1_000_000_000.0, "revenue": 5e9}
            for i in range(1, 4)
        ]

    def test_chart_works_without_consensus(self):
        chart = charts.eps_trend(self._history())

        self.assertEqual(chart["actual_dots"], [])
        self.assertIsNone(chart["forward"])

    def test_adjusted_dots_are_matched_to_quarters(self):
        chart = charts.eps_trend(self._history(), {
            "history": [
                {"quarter_end": date(2026, 6, 30), "actual": 2.5, "estimate": 2.3},
                {"quarter_end": date(2026, 9, 30), "actual": 3.4, "estimate": 3.1},
            ],
            "next_quarter": None,
        })

        self.assertEqual(len(chart["actual_dots"]), 2)
        self.assertEqual(len(chart["estimate_dots"]), 2)

    def test_adjusted_values_expand_the_axis(self):
        """GAAP 선 범위 밖의 조정값이 잘리면 간극이 안 보인다."""
        chart = charts.eps_trend(self._history(), {
            "history": [{"quarter_end": date(2026, 9, 30), "actual": 50.0, "estimate": 48.0}],
            "next_quarter": None,
        })

        # 축 위끝이 50 이상으로 늘어나 점이 판 안에 들어와야 한다.
        self.assertGreaterEqual(chart["actual_dots"][0]["y"], 0)
        self.assertLessEqual(chart["actual_dots"][0]["y"], chart["h"])

    def test_number_line_uses_this_quarter_not_the_previous_one(self):
        """이력이 이번 분기까지 못 왔으면 직전 분기 쌍을 올리지 않는다."""
        stale = charts.eps_trend(self._history(), {
            # history 마지막 분기는 2026-09-30인데 쌍은 6월치뿐이다.
            "history": [{"quarter_end": date(2026, 6, 30), "actual": 2.5,
                         "estimate": 2.3, "surprise": 0.087, "reliable": True}],
            "next_quarter": None,
        })
        fresh = charts.eps_trend(self._history(), {
            "history": [{"quarter_end": date(2026, 9, 30), "actual": 3.4,
                         "estimate": 3.1, "surprise": 0.097, "reliable": True}],
            "next_quarter": None,
        })

        self.assertIsNone(stale["actual_label"])
        self.assertEqual(fresh["actual_label"], "3.40")

    def test_forward_point_sits_after_the_last_actual(self):
        chart = charts.eps_trend(self._history(), {
            "history": [],
            "next_quarter": {"estimate": 4.2, "label": "26·12월 예상"},
        })

        self.assertIsNotNone(chart["forward"])
        self.assertGreater(chart["forward"]["x"], chart["last_x"])
        self.assertEqual(chart["forward"]["label"], "4.20")

    def test_forward_revenue_bar_is_added_to_combo(self):
        history = [
            {"ticker": "N", "fiscal_year": 2026, "fiscal_period": "Q1",
             "period_end": f"2026-0{i}-30", "revenue": 90e9, "operating_income_loss": 5e10,
             "net_income": 4e10}
            for i in range(1, 5)
        ]
        chart = charts.combo(history, [], None, {"revenue": 95e9, "label": "26·12월 예상"})
        forward = chart["financials"]["forward"]

        self.assertIsNotNone(forward)
        self.assertGreater(forward["lx"], chart["financials"]["bars"][-1]["lx"])


class PriceTargetTest(unittest.TestCase):
    def _target(self, snapshot_date: str, **over) -> dict:
        return {
            "ticker": "NVDA", "snapshot_date": snapshot_date,
            "target_mean": 302.83, "target_median": 300.0,
            "target_high": 500.0, "target_low": 180.0, **over,
        }

    def test_latest_target_before_filing_wins(self):
        picked = consensus.pick_price_target(
            [self._target("2026-07-15", target_mean=280.0), self._target("2026-08-15")],
            "NVDA", "2026-08-26",
        )

        self.assertEqual(picked["mean"], 302.83)

    def test_target_after_filing_is_rejected(self):
        """발표를 보고 조정된 목표가 섞이면 같은 시점 비교가 깨진다."""
        picked = consensus.pick_price_target(
            [self._target("2026-08-27")], "NVDA", "2026-08-26"
        )

        self.assertIsNone(picked)

    def test_target_does_not_require_a_redundant_snapshot_price(self):
        picked = consensus.pick_price_target([self._target("2026-08-15")], "NVDA", "2026-08-26")

        self.assertEqual(picked["mean"], 302.83)
        self.assertNotIn("price_current", picked)
        self.assertNotIn("upside", picked)

    def test_build_returns_a_block_for_targets_alone(self):
        """컨센서스가 없어도 목표주가만으로 '주가'에 녹일 게 있다."""
        built = consensus.build(
            {"ticker": "NVDA", "period_end": "2026-07-26", "filed_at": "2026-08-26",
             "revenue": 93e9},
            [], [], [self._target("2026-08-15")],
        )

        self.assertIsNotNone(built)
        self.assertEqual(built["price_target"]["mean"], 302.83)

    def test_missing_targets_leave_the_block_absent(self):
        self.assertIsNone(consensus.build(
            {"ticker": "JPM", "period_end": "2026-06-30", "filed_at": "2026-08-06"},
            [], [], [],
        ))


class PriceTrackTest(unittest.TestCase):
    _TECH = {"low_52w": 165.17, "high_52w": 235.74, "close": 208.27, "sma_200": 180.0}

    def test_track_without_target_has_no_target_block(self):
        track = charts.week52_range(self._TECH)

        self.assertIsNone(track["target"])

    def test_axis_expands_to_cover_targets_beyond_the_52w_high(self):
        """목표가 52주 축 밖이면 끝에 눌려 '어디로 본다'가 안 읽힌다."""
        track = charts.week52_range(self._TECH, {
            "low": 180.0, "high": 500.0, "mean": 302.83, "upside": 0.345,
        })

        # 52주 띠가 축 전체를 채우지 않고, 목표 평균이 그 오른쪽에 놓인다.
        self.assertLess(track["band_width"], 100.0)
        self.assertGreater(track["target"]["mean_pos"], track["close_pos"])
        self.assertEqual(track["axis_hi_label"], "$500.00")

    def test_positions_stay_within_the_track(self):
        track = charts.week52_range(self._TECH, {
            "low": 74.0, "high": 500.0, "mean": 302.83, "upside": 0.345,
        })

        for key in ("band_left", "close_pos", "sma200_pos"):
            with self.subTest(key=key):
                self.assertGreaterEqual(track[key], 0.0)
                self.assertLessEqual(track[key], 100.0)

    def test_target_below_price_is_flagged(self):
        track = charts.week52_range(self._TECH, {
            "low": 100.0, "high": 200.0, "mean": 150.0, "upside": -0.28,
        })

        self.assertFalse(track["target"]["above"])


if __name__ == "__main__":
    unittest.main()
