"""EvidenceBundle과 PIT 밸류에이션 관측값을 InvestmentDossier로 조립한다.

원본을 다시 읽지 않는다. `ContextBuilder`가 이미 시점 검증을 마친 bundle을 받아
섹션별 **요약**으로 줄이는 것이 이 계층의 유일한 책임이다. 값이 없으면 추정하지
않고 사유만 남긴다.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from investment_agent.trading.contracts import EvidenceBundle, EvidenceItem, parse_datetime
from investment_agent.trading.evidence.contracts import (
    DOSSIER_VERSION,
    DossierSection,
    InvestmentDossier,
    build_quality,
)
from investment_agent.trading.evidence.history import fundamental_trend, price_risk_profile

# 섹션 제목은 화면·프롬프트가 함께 쓰는 표시 이름이다.
SECTION_TITLES = {
    "price_risk": "가격·위험",
    "valuation": "밸류에이션",
    "fundamentals": "재무",
    "estimates": "컨센서스",
    "segments": "세그먼트",
    "ownership": "13F 보유",
    "macro_events": "거시·이벤트",
    "external_live": "외부 라이브",
}

# LLM에 통째로 넘기지 않기 위한 섹션별 행 예산.
_MAX_MACRO_SERIES = 12
_MAX_ECON_EVENTS = 8
_MAX_SEGMENTS = 8
_MAX_GURUS = 10

def _find(bundle: EvidenceBundle, domain: str) -> EvidenceItem | None:
    for item in bundle.evidence:
        if item.domain == domain:
            return item
    return None


def _missing_reason(bundle: EvidenceBundle, domain: str) -> str:
    """ContextBuilder가 남긴 사람이 읽는 사유를 그대로 물려준다."""
    prefix = f"{domain}:"
    for text in bundle.missing_data:
        if str(text).startswith(prefix):
            return str(text)
    return f"{domain}: 근거 없음"


def _section(
    section_id: str,
    *,
    bundle: EvidenceBundle,
    domain: str,
    payload: Mapping[str, Any] | None,
    extra_evidence: Sequence[str] = (),
) -> DossierSection:
    item = _find(bundle, domain)
    if item is None or not payload:
        return DossierSection(
            section_id=section_id,
            title=SECTION_TITLES[section_id],
            missing_reason=_missing_reason(bundle, domain),
        )
    return DossierSection(
        section_id=section_id,
        title=SECTION_TITLES[section_id],
        payload=dict(payload),
        evidence_ids=(item.evidence_id, *extra_evidence),
        available_at=item.available_at,
    )


def _price_risk(
    bundle: EvidenceBundle,
    price_history: Sequence[Mapping[str, Any]] | None,
) -> DossierSection:
    item = _find(bundle, "market")
    payload: dict[str, Any] = {}
    if item is not None and isinstance(item.payload, Mapping):
        statistics = item.payload.get("statistics")
        if isinstance(statistics, Mapping) and statistics:
            # 원시 봉은 넣지 않는다 — LLM에는 계산된 요약만 준다.
            payload = {
                "latest_close": statistics.get("latest_close"),
                "observations": statistics.get("observations"),
                "returns": {
                    key: value for key, value in statistics.items()
                    if key.startswith("return_")
                },
                "volatility": statistics.get("volatility_20d_annualized"),
                "max_drawdown": statistics.get("max_drawdown_window"),
            }
    if price_history:
        # bundle은 feature용이라 260봉까지다. 장기 구간은 별도 조회로 채운다.
        profile = price_risk_profile(price_history)
        if profile:
            payload["long_horizon"] = profile
    return _section("price_risk", bundle=bundle, domain="market", payload=payload)


def _fundamentals(
    bundle: EvidenceBundle,
    filing_history: Sequence[Mapping[str, Any]] | None,
) -> DossierSection:
    item = _find(bundle, "fundamentals")
    payload: dict[str, Any] = {}
    if item is not None and isinstance(item.payload, Mapping):
        statistics = item.payload.get("statistics")
        filings = item.payload.get("filings")
        if isinstance(statistics, Mapping) and statistics:
            payload = {"statistics": dict(statistics)}
            if isinstance(filings, list) and filings:
                payload["filings_considered"] = len(filings)
                payload["latest_period_end"] = filings[0].get("period_end")
                payload["latest_filed_at"] = filings[0].get("filed_at")
    if filing_history and payload:
        # bundle은 12건까지라 3년이다. 연도별 추세는 별도 조회로 채운다.
        trend = fundamental_trend(filing_history)
        if trend:
            payload["long_horizon"] = trend
    return _section("fundamentals", bundle=bundle, domain="fundamentals", payload=payload)


def _estimates(bundle: EvidenceBundle) -> DossierSection:
    item = _find(bundle, "estimates")
    payload: dict[str, Any] = {}
    if item is not None and isinstance(item.payload, Mapping):
        statistics = item.payload.get("consensus_statistics")
        if isinstance(statistics, Mapping) and statistics:
            payload = {
                "consensus": dict(statistics),
                "reconstructed_rows_excluded": bool(
                    item.payload.get("reconstructed_rows_excluded")
                ),
            }
    return _section("estimates", bundle=bundle, domain="estimates", payload=payload)


def _segments(bundle: EvidenceBundle) -> DossierSection:
    item = _find(bundle, "segments")
    payload: dict[str, Any] = {}
    if item is not None and isinstance(item.payload, Mapping):
        metrics = item.payload.get("metrics")
        if isinstance(metrics, list) and metrics:
            payload = {
                "segment_count": len(metrics),
                "segments": [
                    {
                        key: row.get(key)
                        for key in ("segment_label", "revenue", "profit_loss", "quality_status")
                        if key in row
                    }
                    for row in metrics[:_MAX_SEGMENTS]
                    if isinstance(row, Mapping)
                ],
                "truncated": len(metrics) > _MAX_SEGMENTS,
            }
    return _section("segments", bundle=bundle, domain="segments", payload=payload)


def _ownership(bundle: EvidenceBundle) -> DossierSection:
    item = _find(bundle, "gurus")
    payload: dict[str, Any] = {}
    if item is not None and isinstance(item.payload, Mapping):
        positions = item.payload.get("positions")
        features = item.payload.get("features")
        if isinstance(positions, list) and positions:
            payload = {
                "holder_count": len(positions),
                "positions": [
                    {
                        key: row.get(key)
                        for key in ("manager_name", "value_usd", "quantity_change_pct", "action")
                        if key in row
                    }
                    for row in positions[:_MAX_GURUS]
                    if isinstance(row, Mapping)
                ],
                "truncated": len(positions) > _MAX_GURUS,
            }
            if isinstance(features, Mapping) and features:
                payload["features"] = dict(features)
    return _section("ownership", bundle=bundle, domain="gurus", payload=payload)


def _macro_events(bundle: EvidenceBundle) -> DossierSection:
    """거시와 경제일정을 한 섹션으로 합친다 — LLM에는 regime 하나로 읽히는 게 낫다."""
    macro = _find(bundle, "macro")
    econ = _find(bundle, "economic_calendar")
    if macro is None and econ is None:
        return DossierSection(
            section_id="macro_events",
            title=SECTION_TITLES["macro_events"],
            missing_reason=_missing_reason(bundle, "macro"),
        )
    payload: dict[str, Any] = {}
    evidence: list[str] = []
    available: list[str] = []
    if macro is not None and isinstance(macro.payload, Mapping):
        observations = macro.payload.get("latest_observations")
        if isinstance(observations, list) and observations:
            payload["macro"] = [
                {key: row.get(key) for key in ("series_id", "obs_date", "value") if key in row}
                for row in observations[:_MAX_MACRO_SERIES]
                if isinstance(row, Mapping)
            ]
            payload["macro_truncated"] = len(observations) > _MAX_MACRO_SERIES
            evidence.append(macro.evidence_id)
            available.append(macro.available_at)
    if econ is not None and isinstance(econ.payload, Mapping):
        rows = [
            row for key in ("events", "results", "forecasts")
            for row in (econ.payload.get(key) or [])
            if isinstance(row, Mapping)
        ]
        if rows:
            payload["events"] = [
                {
                    key: row.get(key)
                    for key in ("event_key", "scheduled_at", "actual", "forecast")
                    if key in row
                }
                for row in rows[:_MAX_ECON_EVENTS]
            ]
            payload["events_truncated"] = len(rows) > _MAX_ECON_EVENTS
            evidence.append(econ.evidence_id)
            available.append(econ.available_at)
    if not payload:
        return DossierSection(
            section_id="macro_events",
            title=SECTION_TITLES["macro_events"],
            missing_reason=_missing_reason(bundle, "macro"),
        )
    return DossierSection(
        section_id="macro_events",
        title=SECTION_TITLES["macro_events"],
        payload=payload,
        evidence_ids=tuple(evidence),
        available_at=max(available, key=parse_datetime),
    )


def _valuation(
    bundle: EvidenceBundle,
    observation: Mapping[str, Any] | None,
) -> DossierSection:
    """PIT 밸류에이션 원장의 관측값만 쓴다. 대시보드 view는 근거로 쓰지 않는다."""
    if not observation:
        return DossierSection(
            section_id="valuation",
            title=SECTION_TITLES["valuation"],
            missing_reason="valuation: 시점 기준 PIT 밸류에이션 관측값 없음",
        )
    available_at = observation.get("available_at")
    evidence = [str(value) for value in (observation.get("input_evidence_ids") or [])]
    if not available_at or not evidence:
        return DossierSection(
            section_id="valuation",
            title=SECTION_TITLES["valuation"],
            missing_reason="valuation: 관측값에 가용시각 또는 근거가 없어 사용 불가",
        )
    if parse_datetime(str(available_at)) > parse_datetime(bundle.as_of_at):
        return DossierSection(
            section_id="valuation",
            title=SECTION_TITLES["valuation"],
            missing_reason="valuation: 관측값 가용시각이 판단 시점보다 늦음",
        )
    payload = {
        key: observation.get(key)
        for key in (
            "price", "shares_outstanding", "market_cap",
            "pe_ttm", "pb", "ps_ttm", "fcf_yield",
            "is_meaningful_pe_ttm", "is_meaningful_pb",
            "is_meaningful_ps_ttm", "is_meaningful_fcf_yield",
        )
    }
    # 왜 못 만들었는지가 값만큼 중요하다.
    payload["missing_reasons"] = dict(observation.get("missing_reasons") or {})
    payload["source_version"] = observation.get("source_version")
    return DossierSection(
        section_id="valuation",
        title=SECTION_TITLES["valuation"],
        payload=payload,
        evidence_ids=tuple(evidence),
        available_at=str(available_at),
    )


def _external_live(bundle: EvidenceBundle) -> DossierSection:
    """뉴스·소셜은 live에서만 Agent가 직접 붙인다. 서류철은 정책만 기록한다."""
    return DossierSection(
        section_id="external_live",
        title=SECTION_TITLES["external_live"],
        missing_reason=(
            "external_live: 서류철은 외부 원문을 담지 않는다; live Shadow에서만 "
            "Agent가 provider 경계를 통과해 직접 사용한다"
            if bundle.source_kind == "live_shadow"
            else "external_live: historical replay에서 외부 뉴스·소셜은 항상 차단"
        ),
    )


class DossierBuilder:
    """bundle 하나와 선택적 밸류에이션 관측값으로 서류철을 만든다."""

    version = DOSSIER_VERSION

    def build(
        self,
        bundle: EvidenceBundle,
        *,
        valuation: Mapping[str, Any] | None = None,
        price_history: Sequence[Mapping[str, Any]] | None = None,
        filing_history: Sequence[Mapping[str, Any]] | None = None,
    ) -> InvestmentDossier:
        sections = (
            _price_risk(bundle, price_history),
            _valuation(bundle, valuation),
            _fundamentals(bundle, filing_history),
            _estimates(bundle),
            _segments(bundle),
            _ownership(bundle),
            _macro_events(bundle),
            _external_live(bundle),
        )
        quality = build_quality(sections, warnings=bundle.warnings)
        return InvestmentDossier(
            ticker=bundle.ticker,
            as_of_at=bundle.as_of_at,
            source_kind=bundle.source_kind,
            sections=sections,
            quality=quality,
            provenance={
                "bundle_evidence_count": len(bundle.evidence),
                "bundle_missing_count": len(bundle.missing_data),
                "valuation_source_version": (
                    (valuation or {}).get("source_version") if valuation else None
                ),
                "price_history_bars": len(price_history or ()),
                "filing_history_rows": len(filing_history or ()),
            },
            dossier_version=self.version,
        )


__all__ = ["SECTION_TITLES", "DossierBuilder"]
