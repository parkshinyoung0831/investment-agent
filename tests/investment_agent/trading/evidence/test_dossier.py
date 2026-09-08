"""서류철 계약·조립·렌더의 근거와 분량 규칙을 고정한다."""
from __future__ import annotations

import unittest

from investment_agent.trading.contracts import ContractError, EvidenceBundle, EvidenceItem
from investment_agent.trading.evidence.builder import DossierBuilder
from investment_agent.trading.evidence.contracts import SECTION_IDS, DossierSection
from investment_agent.trading.evidence.renderer import render_markdown, render_prompt_payload
from investment_agent.trading.evidence.report import (
    coverage_rows,
    dossier_sections,
    valuation_contract_rows,
)

_AS_OF = "2026-08-20T22:00:00+00:00"
_AVAILABLE = "2026-08-20T21:30:00+00:00"


def _item(domain: str, payload: dict, *, suffix: str = "1") -> EvidenceItem:
    return EvidenceItem(
        evidence_id=f"EV-{domain}-{suffix}", domain=domain, source=f"{domain}.source",
        observed_at="2026-08-20", available_at=_AVAILABLE, timing_status="known",
        payload=payload,
    )


def _bundle(*items: EvidenceItem, missing=(), warnings=(), source_kind="live_shadow") -> EvidenceBundle:
    return EvidenceBundle(
        ticker="AAA", as_of_at=_AS_OF, source_kind=source_kind,
        evidence=tuple(items), missing_data=tuple(missing), warnings=tuple(warnings),
    )


def _valuation(**overrides) -> dict:
    payload = {
        "source_version": "pit-valuation-v1",
        "available_at": _AVAILABLE,
        "price": 50.0, "shares_outstanding": 1000.0, "market_cap": 50000.0,
        "pe_ttm": 1250.0, "pb": 100.0, "ps_ttm": 125.0, "fcf_yield": 0.0012,
        "is_meaningful_pe_ttm": True, "is_meaningful_pb": True,
        "is_meaningful_ps_ttm": True, "is_meaningful_fcf_yield": True,
        "missing_reasons": {},
        "input_evidence_ids": ["market.prices_daily:AAA:2026-08-20"],
    }
    payload.update(overrides)
    return payload


class SectionContractTest(unittest.TestCase):
    def test_known_section_requires_evidence_and_time(self):
        with self.assertRaises(ContractError):
            DossierSection(section_id="valuation", title="밸류에이션", payload={"pe_ttm": 10})

    def test_missing_section_cannot_carry_data(self):
        with self.assertRaises(ContractError):
            DossierSection(
                section_id="valuation", title="밸류에이션",
                payload={"pe_ttm": 10}, missing_reason="없음",
            )

    def test_unknown_section_id_is_rejected(self):
        with self.assertRaises(ContractError):
            DossierSection(section_id="made_up", title="가짜", missing_reason="없음")


class BuilderTest(unittest.TestCase):
    def _full(self) -> EvidenceBundle:
        return _bundle(
            _item("market", {"statistics": {
                "latest_close": 50.0, "observations": 21,
                "return_5d": 0.02, "return_20d": 0.05, "volatility_20d": 0.3,
            }}),
            _item("fundamentals", {
                "statistics": {"revenue": 100, "net_margin": 0.1},
                "filings": [{"period_end": "2026-06-30", "filed_at": "2026-07-25"}],
            }),
            _item("estimates", {
                "consensus_statistics": {"eps_avg": 1.2, "eps_analysts": 20},
                "reconstructed_rows_excluded": True,
            }),
            _item("macro", {"latest_observations": [
                {"series_id": "VIX", "obs_date": "2026-08-19", "value": 18.0},
            ]}),
            _item("gurus", {"positions": [
                {"manager_name": "M1", "value_usd": 1000, "action": "add"},
            ]}),
        )

    def test_every_section_is_present_even_when_missing(self):
        dossier = DossierBuilder().build(_bundle(missing=("market: 가격 없음",)))
        self.assertEqual(len(dossier.sections), len(SECTION_IDS))
        self.assertEqual(
            {section.section_id for section in dossier.sections}, set(SECTION_IDS),
        )

    def test_missing_reason_is_inherited_from_the_bundle(self):
        dossier = DossierBuilder().build(_bundle(missing=("market: 시점 기준 가격 없음",)))
        self.assertEqual(
            dossier.section("price_risk").missing_reason, "market: 시점 기준 가격 없음",
        )

    def test_known_sections_carry_evidence_ids(self):
        dossier = DossierBuilder().build(self._full(), valuation=_valuation())
        for section_id in ("price_risk", "valuation", "fundamentals", "estimates", "ownership"):
            section = dossier.section(section_id)
            self.assertTrue(section.is_known, section_id)
            self.assertTrue(section.evidence_ids, section_id)
            self.assertIsNotNone(section.available_at, section_id)

    def test_raw_price_bars_never_reach_the_dossier(self):
        """LLM에는 계산된 요약만 준다 — 원시 봉을 넣으면 토큰이 터진다."""
        bundle = _bundle(_item("market", {
            "statistics": {"latest_close": 50.0, "observations": 21},
            "latest_bars": [{"trade_date": "2026-08-20", "close": 50.0}] * 21,
        }))
        payload = DossierBuilder().build(bundle).section("price_risk").payload
        self.assertNotIn("latest_bars", payload)

    def test_valuation_available_after_as_of_is_refused(self):
        dossier = DossierBuilder().build(
            self._full(), valuation=_valuation(available_at="2026-08-21T02:00:00+00:00"),
        )
        section = dossier.section("valuation")
        self.assertFalse(section.is_known)
        self.assertIn("늦음", section.missing_reason)

    def test_valuation_without_evidence_is_refused(self):
        dossier = DossierBuilder().build(self._full(), valuation=_valuation(input_evidence_ids=[]))
        self.assertFalse(dossier.section("valuation").is_known)

    def test_external_live_is_never_a_data_section(self):
        """서류철은 뉴스 원문을 담지 않는다. Agent가 live에서만 직접 쓴다."""
        for kind in ("live_shadow", "historical_replay"):
            dossier = DossierBuilder().build(_bundle(source_kind=kind))
            self.assertFalse(dossier.section("external_live").is_known)

    def test_coverage_score_reflects_usable_sections(self):
        empty = DossierBuilder().build(_bundle())
        rich = DossierBuilder().build(self._full(), valuation=_valuation())
        self.assertEqual(empty.quality.coverage_score, 0.0)
        self.assertGreater(rich.quality.coverage_score, empty.quality.coverage_score)

    def test_same_inputs_produce_the_same_dossier_id(self):
        first = DossierBuilder().build(self._full(), valuation=_valuation())
        second = DossierBuilder().build(self._full(), valuation=_valuation())
        self.assertEqual(first.dossier_id, second.dossier_id)

    def test_bundle_warnings_are_carried_into_quality(self):
        bundle = _bundle(warnings=("technical 파생 뷰 주의",))
        dossier = DossierBuilder().build(bundle)
        self.assertIn("technical 파생 뷰 주의", dossier.quality.warnings)


class RendererTest(unittest.TestCase):
    def _dossier(self):
        bundle = _bundle(
            _item("market", {"statistics": {"latest_close": 50.0, "return_20d": 0.05}}),
        )
        return DossierBuilder().build(bundle, valuation=_valuation())

    def test_markdown_lists_evidence_for_every_known_section(self):
        text = render_markdown(self._dossier())
        self.assertIn("EV-market-1", text)
        self.assertIn("market.prices_daily:AAA:2026-08-20", text)
        self.assertIn("가용시각", text)

    def test_missing_sections_state_the_reason_not_a_zero(self):
        text = render_markdown(DossierBuilder().build(_bundle(missing=("market: 가격 없음",))))
        self.assertIn("사용 불가", text)
        self.assertIn("market: 가격 없음", text)

    def test_over_budget_render_says_it_was_truncated(self):
        text = render_markdown(self._dossier(), char_budget=400)
        self.assertLessEqual(len(text), 400 + 200)
        self.assertIn("잘렸습니다", text)
        self.assertIn("없다고 판단하지 마세요", text)

    def test_prompt_payload_pins_the_allowed_evidence_ids(self):
        payload = render_prompt_payload(self._dossier())
        self.assertIn("allowed_evidence_ids", payload)
        self.assertIn("EV-market-1", payload["allowed_evidence_ids"])
        self.assertIn("missing_sections", payload)

    def test_unusably_small_budget_fails_loudly(self):
        with self.assertRaises(ValueError):
            render_markdown(self._dossier(), char_budget=10)


class DossierReportTest(unittest.TestCase):
    def test_coverage_report_keeps_the_pit_limitations_visible(self) -> None:
        rows = {str(row["영역"]): row for row in coverage_rows()}

        self.assertEqual(rows["가격"]["7년 가능"], "482")
        self.assertIn("historical 불가", str(rows["가격"]["PIT 판정"]))
        self.assertEqual(rows["컨센서스"]["7년 가능"], "0")

    def test_report_includes_the_complete_dossier_shape(self) -> None:
        ids = {section.section_id for section in dossier_sections()}

        self.assertEqual(ids, {
            "price_risk", "valuation", "fundamentals", "estimates", "segments",
            "ownership", "macro_events", "external_live",
        })
        contracts = {str(row["항목"]): str(row["계약"]) for row in valuation_contract_rows()}
        self.assertIn("available_at", contracts["시간"])
        self.assertIn("SHA-256", contracts["재현성"])


if __name__ == "__main__":
    unittest.main()
