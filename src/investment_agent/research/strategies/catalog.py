"""계산기와 알림이 공유하는 전략 메타데이터."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyMeta:
    db_name: str
    description: str
    notify_name: str
    notify_description: str


TICKER_LABELS: dict[str, str] = {
    "SPY": "미국 대형주",
    "EFA": "선진국주식",
    "EEM": "신흥국",
    "IWM": "미국 소형주",
    "SCZ": "선진국 소형주",
    "VNQ": "미국 리츠",
    "DBC": "원자재",
    "AGG": "미국 종합채권",
    "IEF": "미국 중기채",
    "TLT": "미국 장기채",
    "BIL": "단기채(현금)",
    "TIP": "물가채",
    "XLB": "소재",
    "XLC": "통신",
    "XLE": "에너지",
    "XLF": "금융",
    "XLI": "산업재",
    "XLK": "기술",
    "XLP": "필수소비재",
    "XLRE": "부동산",
    "XLU": "유틸리티",
    "XLV": "헬스케어",
    "XLY": "임의소비재",
}

MODE_LABELS: dict[str, str] = {
    "Risk-On-US": "🇺🇸 공격 · 미국 우위",
    "Risk-On-INTL": "🌏 공격 · 해외 우위",
    "Risk-Off": "🛡 방어 · 안전자산 도피",
    "Risk-Off (TLT)": "🛡 방어 · 장기채로 도피",
    "Defensive (Canary OFF)": "🐦 위험 감지 · 방어 모드",
    "Defensive (neg score)": "🛡 방어 · 점수 음수",
    "Attack (Canary ON)": "🐦 안전 신호 · 공격 모드",
    "Attack": "🐦 안전 신호 · 공격 모드",
}

STRATEGY_CATALOG: dict[str, StrategyMeta] = {
    "gem": StrategyMeta(
        db_name="GEM (Global Equities Momentum)",
        description="Antonacci 2014",
        notify_name="GEM",
        notify_description="미국 vs 해외 vs 현금 중 1년 승자 100%",
    ),
    "adm": StrategyMeta(
        db_name="ADM (Accelerating Dual Momentum)",
        description="Engineered Portfolio 2018",
        notify_name="ADM",
        notify_description="미국 대형 vs 해외 소형 모멘텀 승자 100%",
    ),
    "dmsr": StrategyMeta(
        db_name="DMSR (Dual Momentum Sector Rot.)",
        description="SPDR 11 sectors, 12M Top-4",
        notify_name="DMSR",
        notify_description="미국 11개 산업 Top-4 중 현금 초과분 25%씩",
    ),
    "gtaa5": StrategyMeta(
        db_name="GTAA-5",
        description="Faber 2007",
        notify_name="GTAA-5",
        notify_description="5개 자산군 중 10개월 평균선 위에 있으면 20%씩",
    ),
    "haa_bal": StrategyMeta(
        db_name="HAA-Balanced",
        description="Keller 2023 - Balanced",
        notify_name="HAA-Bal",
        notify_description="위험 신호로 8자산 Top-4 vs 방어 자동 전환",
    ),
    "haa_sim": StrategyMeta(
        db_name="HAA-Simple",
        description="Keller 2023 - Simple",
        notify_name="HAA-Sim",
        notify_description="위험 신호로 4자산 1등 vs 방어 자동 전환",
    ),
}


def ensure_registered_strategies(registered_ids: set[str]) -> None:
    """Fail fast when compute registration and metadata drift apart."""
    catalog_ids = set(STRATEGY_CATALOG)
    missing_meta = registered_ids - catalog_ids
    missing_compute = catalog_ids - registered_ids
    if missing_meta or missing_compute:
        parts = []
        if missing_meta:
            parts.append(f"metadata missing for {sorted(missing_meta)}")
        if missing_compute:
            parts.append(f"compute function missing for {sorted(missing_compute)}")
        raise RuntimeError("strategy catalog mismatch: " + "; ".join(parts))


__all__ = [
    "MODE_LABELS",
    "STRATEGY_CATALOG",
    "TICKER_LABELS",
    "StrategyMeta",
    "ensure_registered_strategies",
]
