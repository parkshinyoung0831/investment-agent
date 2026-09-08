"""LLM 텍스트 내 수치 주장의 사실성 검증 및 환각(Hallucination) 차단 게이트.

LLM의 분석 텍스트(reasoning)에 포함된 핵심 재무·기술·시장 수치들을 추출하여,
동일 시점의 불변 근거 묶음(EvidenceBundle)의 실제 값과 대조하고,
허위·왜곡된 수치가 포함된 신호를 결정론적으로 감지하고 패널티를 부과한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from investment_agent.platform.serialization import finite_float


@dataclass(frozen=True)
class FactClaim:
    """텍스트에서 추출한 수치 주장."""

    metric: str
    claimed_value: float
    raw_match: str


@dataclass(frozen=True)
class FactVerificationResult:
    """팩트체크 검증 결과."""

    is_valid: bool
    total_claims: int
    verified_claims: int
    hallucination_count: int
    hallucinated_claims: tuple[dict[str, Any], ...]
    max_relative_error: float
    confidence_penalty: float

    def adjusted_confidence(self, base_confidence: float) -> float:
        """환각 페널티를 반영하여 조정된 신뢰도 (0.0~1.0)."""
        clamped = max(0.0, min(1.0, float(base_confidence)))
        return max(0.0, min(1.0, clamped * (1.0 - self.confidence_penalty)))


# 정규식 패턴 모음: 메트릭 키 및 숫자 매칭 (한국어 조사 및 영문 유연 대응)
_METRIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("rsi", re.compile(r"(?:rsi(?:14)?|상대강도지수)(?:는|은|가|이)?\s*[:=]?\s*(\d+(?:\.\d+)?)", re.IGNORECASE)),
    ("pe_ratio", re.compile(r"(?:p/e|per|주가수익비율)(?:는|은|가|이)?\s*[:=]?\s*(\d+(?:\.\d+)?)", re.IGNORECASE)),
    ("pb_ratio", re.compile(r"(?:p/b|pbr|주가순자산비율)(?:는|은|가|이)?\s*[:=]?\s*(\d+(?:\.\d+)?)", re.IGNORECASE)),
    ("price", re.compile(r"(?:price|close|현재가|종가|주가)(?:는|은|가|이)?\s*[:=]?\s*\$?\s*(\d+(?:\.\d+)?)", re.IGNORECASE)),
    ("revenue_growth", re.compile(r"(?:revenue\s*growth|매출\s*성장률)(?:는|은|가|이)?\s*[:=]?\s*([+-]?\d+(?:\.\d+)?)\s*%?", re.IGNORECASE)),
    ("operating_margin", re.compile(r"(?:operating\s*margin|영업이익률)(?:는|은|가|이)?\s*[:=]?\s*([+-]?\d+(?:\.\d+)?)\s*%?", re.IGNORECASE)),
)


def extract_claims(text: str) -> list[FactClaim]:
    """분석 텍스트에서 수치 주장을 추출한다."""
    if not text:
        return []
    claims: list[FactClaim] = []
    for metric, pattern in _METRIC_PATTERNS:
        for match in pattern.finditer(text):
            val_str = match.group(1)
            val = finite_float(val_str)
            if val is not None:
                claims.append(FactClaim(metric=metric, claimed_value=val, raw_match=match.group(0)))
    return claims


def _extract_evidence_metrics(evidence: Mapping[str, Any]) -> dict[str, float]:
    """EvidenceBundle 또는 items 매핑에서 대조 가능한 실제 수치들을 수집한다."""
    metrics: dict[str, float] = {}

    items = evidence.get("items")
    if isinstance(items, (list, tuple)):
        for item in items:
            if not isinstance(item, Mapping):
                payload = getattr(item, "payload", {}) if hasattr(item, "payload") else {}
            else:
                payload = item.get("payload", {})
            if isinstance(payload, Mapping):
                _harvest_payload(payload, metrics)
    elif isinstance(evidence, Mapping):
        _harvest_payload(evidence, metrics)

    return metrics


def _harvest_payload(payload: Mapping[str, Any], out: dict[str, float]) -> None:
    """payload 내의 알려진 키들을 정규 메트릭으로 매핑."""
    close = finite_float(payload.get("close") or payload.get("price") or payload.get("last_close"))
    if close is not None:
        out["price"] = close

    rsi = finite_float(payload.get("rsi") or payload.get("rsi_14") or payload.get("rsi14"))
    if rsi is not None:
        out["rsi"] = rsi

    pe = finite_float(payload.get("pe_ratio") or payload.get("pe") or payload.get("trailing_pe"))
    if pe is not None:
        out["pe_ratio"] = pe

    pb = finite_float(payload.get("pb_ratio") or payload.get("pb"))
    if pb is not None:
        out["pb_ratio"] = pb

    rev_g = finite_float(payload.get("revenue_growth") or payload.get("revenue_growth_yoy"))
    if rev_g is not None:
        out["revenue_growth"] = rev_g

    op_m = finite_float(payload.get("operating_margin") or payload.get("op_margin"))
    if op_m is not None:
        out["operating_margin"] = op_m


class FactVerificationGate:
    """수치 검증 및 환각 제어 게이트."""

    def __init__(self, tolerance: float = 0.05, max_hallucination_rate: float = 0.25) -> None:
        self.tolerance = max(0.001, float(tolerance))
        self.max_hallucination_rate = max(0.0, min(1.0, float(max_hallucination_rate)))

    def verify(self, reasoning: str, evidence: Mapping[str, Any]) -> FactVerificationResult:
        """reasoning 텍스트를 파싱하여 evidence 데이터와 대조 검증한다."""
        claims = extract_claims(reasoning)
        if not claims:
            return FactVerificationResult(
                is_valid=True,
                total_claims=0,
                verified_claims=0,
                hallucination_count=0,
                hallucinated_claims=(),
                max_relative_error=0.0,
                confidence_penalty=0.0,
            )

        known_metrics = _extract_evidence_metrics(evidence)
        verified = 0
        hallucinations: list[dict[str, Any]] = []
        max_err = 0.0

        for claim in claims:
            if claim.metric not in known_metrics:
                continue

            actual = known_metrics[claim.metric]
            denom = abs(actual) if abs(actual) > 1e-6 else 1.0
            rel_err = abs(claim.claimed_value - actual) / denom
            max_err = max(max_err, rel_err)

            if rel_err <= self.tolerance:
                verified += 1
            else:
                hallucinations.append({
                    "metric": claim.metric,
                    "claimed": claim.claimed_value,
                    "actual": actual,
                    "relative_error": rel_err,
                    "raw": claim.raw_match,
                })

        tested = verified + len(hallucinations)
        if tested == 0:
            return FactVerificationResult(
                is_valid=True,
                total_claims=len(claims),
                verified_claims=0,
                hallucination_count=0,
                hallucinated_claims=(),
                max_relative_error=0.0,
                confidence_penalty=0.0,
            )

        hallucination_rate = len(hallucinations) / tested
        is_valid = hallucination_rate <= self.max_hallucination_rate

        if not hallucinations:
            penalty = 0.0
        else:
            penalty = min(1.0, hallucination_rate * 0.5 + min(0.5, max_err * 0.5))
            if not is_valid:
                penalty = max(0.5, penalty)

        return FactVerificationResult(
            is_valid=is_valid,
            total_claims=len(claims),
            verified_claims=verified,
            hallucination_count=len(hallucinations),
            hallucinated_claims=tuple(hallucinations),
            max_relative_error=max_err,
            confidence_penalty=penalty,
        )


__all__ = [
    "FactClaim",
    "FactVerificationGate",
    "FactVerificationResult",
    "extract_claims",
]
