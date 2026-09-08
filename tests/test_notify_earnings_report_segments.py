"""실적 알림에 붙는 세그먼트 요약의 기간·중복 방지 규칙을 검증한다."""
from __future__ import annotations

from datetime import date
import sys
import types
import unittest
from unittest.mock import Mock, patch


if "supabase" not in sys.modules:
    supabase = types.ModuleType("supabase")
    supabase.Client = object
    supabase.create_client = lambda *_args, **_kwargs: None
    sys.modules["supabase"] = supabase

from investment_agent.notifications.earnings_report import candidates
from investment_agent.notifications.earnings_report import run
from investment_agent.notifications.earnings_report import render
from investment_agent.reporting.notifications import earnings_report_segment_state as segment_state
from investment_agent.notifications.earnings_report import card, profiles


def _row(
    *,
    name: str,
    revenue: float,
    segment_hash: str,
    fiscal_year: int = 2026,
    fiscal_period: str = "Q2",
    segment_type: str = "business",
    period_kind: str = "quarter",
    dimension_count: int = 1,
    quality_status: str = "verified",
    axis: str = "BusinessSegments",
    profit_loss: float | None = None,
    profit_quality_status: str = "unsafe",
    profit_measure_kind: str | None = None,
    accession_no: str = "ACC",
) -> dict:
    return {
        "ticker": "TEST",
        "accession_no": accession_no,
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "period_kind": period_kind,
        "segment_hash": segment_hash,
        "segment_type": segment_type,
        "axis": axis,
        "raw_name": name,
        "display_name": name,
        "dimension_count": dimension_count,
        "revenue": revenue,
        "quality_status": quality_status,
        "coverage_ratio": 1.0,
        "profit_loss": profit_loss,
        "profit_quality_status": profit_quality_status,
        "profit_measure_kind": profit_measure_kind,
        "profit_measure_label": "영업이익" if profit_measure_kind else None,
        "profit_coverage_ratio": 1.0 if profit_quality_status == "verified" else None,
    }


class SegmentHighlightsTest(unittest.TestCase):
    @staticmethod
    def _result(rows: list[dict], *, accession_no: str = "ACC", fiscal_period: str = "Q2") -> dict:
        target = ("TEST", accession_no, 2026, fiscal_period)
        states = {("TEST", accession_no): {"status": "parsed"}}
        return segment_state.build(rows, {target}, states)[target]

    def test_same_fiscal_period_only_and_yoy_by_segment_hash(self):
        rows = [
            _row(name="Cloud", revenue=60, segment_hash="cloud"),
            _row(name="Devices", revenue=40, segment_hash="devices"),
            _row(name="US", revenue=80, segment_hash="us", segment_type="geographic"),
            _row(name="Cross-tab", revenue=999, segment_hash="cross", dimension_count=2),
            _row(name="Cloud", revenue=50, segment_hash="cloud", fiscal_year=2025),
            _row(name="Devices", revenue=50, segment_hash="devices", fiscal_year=2025),
            _row(name="Other quarter", revenue=999, segment_hash="other", fiscal_period="Q1"),
        ]

        result = self._result(rows)
        highlights = result["axes"][0]["rows"]

        self.assertEqual([row["name"] for row in highlights], ["Cloud", "Devices"])
        self.assertEqual(result["axes"][0]["type"], "business")
        self.assertAlmostEqual(highlights[0]["revenue_pct"], 0.6)
        self.assertAlmostEqual(highlights[0]["revenue_yoy"], 0.2)
        geographic = next(a for a in result["axes"] if a["type"] == "geographic")
        self.assertEqual([row["name"] for row in geographic["rows"]], ["US"])

    def test_annual_filing_does_not_use_quarter_segment(self):
        rows = [
            _row(name="Annual", revenue=100, segment_hash="annual", fiscal_period="FY", period_kind="annual"),
            _row(name="Quarter", revenue=200, segment_hash="quarter", fiscal_period="FY", period_kind="quarter"),
        ]

        target = ("TEST", "ACC", 2026, "FY")
        result = segment_state.build(
            rows, {target}, {("TEST", "ACC"): {"status": "parsed"}}
        )[target]

        self.assertEqual([row["name"] for row in result["axes"][0]["rows"]], ["Annual"])

    def test_partial_segment_hides_share_and_yoy(self):
        rows = [
            _row(name="Custom Cloud", revenue=60, segment_hash="cloud", quality_status="partial"),
            _row(name="Custom Cloud", revenue=50, segment_hash="cloud", fiscal_year=2025),
        ]

        item = self._result(rows)["axes"][0]["rows"][0]

        self.assertEqual(item["quality_status"], "partial")
        self.assertIsNone(item["revenue_pct"])
        self.assertIsNone(item["revenue_yoy"])

    def test_profit_yoy_requires_same_verified_measure(self):
        rows = [
            _row(
                name="Cloud", revenue=100, segment_hash="cloud", profit_loss=25,
                profit_quality_status="verified", profit_measure_kind="operating_income",
            ),
            _row(
                name="Cloud", revenue=80, segment_hash="cloud", fiscal_year=2025,
                profit_loss=20, profit_quality_status="verified",
                profit_measure_kind="operating_income",
            ),
        ]

        item = self._result(rows)["axes"][0]["rows"][0]

        self.assertEqual(item["profit_loss"], 25)
        self.assertAlmostEqual(item["profit_yoy"], 0.25)

    def test_unsafe_profit_is_hidden_even_when_revenue_is_verified(self):
        item = self._result([
            _row(
                name="Cloud", revenue=100, segment_hash="cloud", profit_loss=999,
                profit_quality_status="unsafe", profit_measure_kind="operating_income",
            )
        ])["axes"][0]["rows"][0]

        self.assertIsNone(item["profit_loss"])
        self.assertIsNone(item["profit_margin"])

    def test_exact_accession_does_not_borrow_other_filing(self):
        result = self._result([
            _row(name="Wrong filing", revenue=100, segment_hash="wrong", accession_no="OTHER")
        ])

        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["axes"], [])

    def test_filing_status_is_preserved_when_segments_are_not_ready(self):
        target = ("TEST", "ACC", 2026, "Q2")
        result = segment_state.build(
            [], {target}, {("TEST", "ACC"): {"status": "processing"}}
        )[target]

        self.assertEqual(result["status"], "processing")

    def test_report_waits_for_unfinished_or_failed_segment_sync(self):
        """세그먼트 공시가 끝나기 전에는 빈 축 카드로 선점하지 않는다."""
        self.assertFalse(candidates.is_report_ready({"status": "processing", "axes": []}))
        self.assertFalse(candidates.is_report_ready({"status": "failed", "axes": []}))
        self.assertTrue(candidates.is_report_ready({"status": "unsupported", "axes": []}))
        self.assertTrue(candidates.is_report_ready({"status": "verified", "axes": []}))

    def test_the_wait_for_segments_has_a_deadline(self):
        """기한이 없으면 "늦게 보낸다"가 아니라 "영영 안 보낸다"가 된다.

        세그먼트는 SEC의 분기 데이터셋에서 오고 그것은 한 분기 늦게 공개된다.
        실제로 관심종목 47건이 status=processing에 몇 달째 묶여 카드가 한 장도
        나가지 않았다. 기한이 지나면 재무 카드만이라도 내보낸다 — 세그먼트는 본
        카드가 아니라 같은 메시지에 얹는 별도 embed라 없으면 그 자리만 빈다.
        """
        today = date(2026, 9, 8)
        waiting = {"status": "processing", "axes": []}
        # 갓 접수된 공시는 축이 붙기를 기다린다.
        self.assertFalse(
            candidates.is_report_ready(waiting, filed_at="2026-09-07", today=today))
        # 기한을 넘기면 세그먼트 없이 내보낸다.
        self.assertTrue(
            candidates.is_report_ready(waiting, filed_at="2026-06-30", today=today))
        self.assertTrue(
            candidates.is_report_ready({"status": "failed", "axes": []},
                                       filed_at="2026-06-30", today=today))

    def test_a_filing_without_a_filed_date_keeps_waiting(self):
        """접수일을 모르면 기한을 잴 수 없다. 그때는 보내지 않는 쪽이 안전하다."""
        self.assertFalse(
            candidates.is_report_ready({"status": "processing", "axes": []}, filed_at=""))

    def test_pending_report_is_deferred_until_segment_sync_finishes(self):
        """후속 알림 잡도 processing/failed 공시를 선점하지 않는다."""
        row = {
            "ticker": "TEST", "fiscal_year": 2026, "fiscal_period": "Q2",
            "period_end": "2026-06-30", "filed_at": date.today().isoformat(),
            "accession_no": "ACC",
        }
        common = {
            "watchlist_members": Mock(return_value=[{"ticker": "TEST", "watch_from": "2000-01-01"}]),
            "load_headline_rows": Mock(return_value=[row]),
            "processed_keys": Mock(return_value=set()),
            "anomaly_keys": Mock(return_value=set()),
            "load_health": Mock(return_value={}),
            "load_valuation": Mock(return_value={}),
            "load_names": Mock(return_value={}),
            "load_sector_rows": Mock(return_value=[]),
        }
        for status in ("processing", "failed"):
            with self.subTest(status=status), patch.multiple(candidates.db, **common), patch.object(
                candidates.db,
                "load_segment_highlights",
                side_effect=lambda targets: {
                    target: {"status": status, "axes": []} for target in targets
                },
            ):
                self.assertEqual(candidates.load_pending(), [])


class EarningsCardTest(unittest.TestCase):
    @staticmethod
    def _item(*, sector: str = "Electronic Computers") -> dict:
        row = {
            "ticker": "TEST", "fiscal_year": 2026, "fiscal_period": "Q2",
            "accession_no": "ACC", "form_type": "10-Q", "period_end": "2026-06-30",
            "filed_at": "2026-07-30", "mapping_version": "test",
            "revenue": 120, "operating_income_loss": 30, "net_income": 24,
            "gross_profit": 60, "shares_fully_diluted_average": 12,
            "net_cash_from_operating_activities": 28, "capital_expenses": 8,
            "cash_and_cash_equivalents": 40, "total_debt_including_current": 10,
            "source_manifest": {
                key: {"accession_no": "ACC"} for key in (
                    "revenue", "operating_income_loss", "net_income",
                    "net_cash_from_operating_activities",
                )
            },
            "_has_anomaly": False,
        }
        prev = {
            **row, "fiscal_year": 2025, "accession_no": "PREV", "revenue": 100,
            "operating_income_loss": 20, "net_income": 18,
        }
        return {
            "row": row,
            "prev": prev,
            "names": {"name": "Test Corp", "name_ko": "테스트", "sic_industry": sector},
            "valuation": {
                "valuation_supported": True, "price": 10, "price_date": "2026-08-01",
                "market_cap": 1000, "pe_ttm": 20, "pb": 3,
                "ev_to_ebitda": 15, "fcf_yield": .03,
            },
            "segment_state": {"status": "unsupported", "axes": []},
        }

    def test_original_template_renders_without_optional_segments(self):
        ctx, caption = card.build(self._item())
        html = render.render("earnings.html.j2", ctx)

        self.assertIn("TEST", caption)
        self.assertIn("실적", html)
        self.assertIn("현금흐름", html)
        self.assertNotIn("세그먼트 성과", html)

    def test_one_block_per_question(self):
        """블록 하나 = 질문 하나. 제목이 '뭐와 뭐'면 두 주제가 섞였다는 뜻이다."""
        source = render.ENV.loader.get_source(render.ENV, "earnings.html.j2")[0]

        for title in (
            "밸류에이션", "주가", "주주환원", "수익성", "손익 구조", "실적 추이",
            "현금흐름", "현금흐름 추이", "EPS", "유동성 · 부채", "재무건전성",
        ):
            with self.subTest(title=title):
                self.assertIn(f'<div class="section-title">{title}</div>', source)
        for merged in ("수익성과 재무건전성", "현금흐름과 이익의 질", "주가와 주주환원"):
            with self.subTest(merged=merged):
                self.assertNotIn(merged, source)

    def test_revisions_block_is_wired_into_both_row_one_branches(self):
        """1행은 배당 유무로 두 갈래다 — 한쪽에만 붙이면 배당 없는 회사에서 조용히 빠진다.

        실측으로 UBER(배당 없음) 카드에서 '추정치 방향'이 통째로 사라졌다.
        """
        source = render.ENV.loader.get_source(render.ENV, "earnings.html.j2")[0]
        body = source.split("{% macro revisions_block() %}", 1)[1]

        # 매크로 정의부를 뺀 호출 지점이 두 갈래 모두에 있어야 한다.
        self.assertEqual(body.count("{{ revisions_block() }}"), 2)

    def test_each_trend_block_draws_its_own_chart(self):
        """블록 하나 = 질문 하나 = 그림 하나."""
        source = render.ENV.loader.get_source(render.ENV, "earnings.html.j2")[0]

        for card_title, chart in (
            ("실적 추이", "combo.financials"),
            ("EPS", "eps_trend"),
            ("현금흐름 추이", "cashflow_quarters"),
            ("유동성 · 부채", "combo.ratios"),
        ):
            body = source.split(f'<div class="section-title">{card_title}</div>', 1)[1]
            body = body.split("</section>", 1)[0]
            with self.subTest(card=card_title):
                self.assertIn(chart, body)

    def test_gauge_tracks_and_range_bar_are_gone(self):
        """트랙이 먹는 면적 대비 정보가 '값 1 + 등급 1'뿐이라 글자로 내린다."""
        source = render.ENV.loader.get_source(render.ENV, "earnings.html.j2")[0]

        for dead in ("gauge-track", "gauge-marker", "gauge-tick", "rangebar", "margin-delta"):
            with self.subTest(dead=dead):
                self.assertNotIn(dead, source)

    def test_sector_profiles_are_distinct(self):
        cases = {
            "Fire, Marine & Casualty Insurance": "insurance",
            "Real Estate Investment Trusts": "reit",
            "Electric Services": "utility",
            "Electronic Computers": "corporate",
        }
        for sector, expected in cases.items():
            with self.subTest(sector=sector):
                item = self._item(sector=sector)
                self.assertEqual(profiles.classify(item["names"]), expected)


class EarningsExtrasTest(unittest.TestCase):
    def test_price_and_share_history_are_passed_to_card_context(self):
        prices = {"TEST": [{"trade_date": "2026-01-02", "close": 10}]}
        shares = {"TEST": [("2026-01-02", 100)]}
        with patch.multiple(
            run.db,
            load_price_history=Mock(return_value=prices),
            load_shares_history=Mock(return_value=shares),
            load_valuation_snapshots=Mock(return_value={}),
            load_quality_history=Mock(return_value={}),
            load_earnings_quality=Mock(return_value={}),
            load_earnings_estimates=Mock(return_value=[]),
            load_surprise_history=Mock(return_value={}),
        ), patch.object(run.history, "compute", return_value=None):
            extras = run._extras_by_ticker(["TEST"])["TEST"]

        self.assertIs(extras["prices"], prices["TEST"])
        self.assertIs(extras["shares"], shares["TEST"])


if __name__ == "__main__":
    unittest.main()
