"""대시보드와 문서가 공유하는 Evidence Dossier 준비 상태 보고서."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DossierSectionSpec:
    """서류철 한 섹션의 표시·소비 계약이다."""

    section_id: str
    title: str
    llm_summary: str
    ml_features: str
    data_status: str


def dossier_sections() -> tuple[DossierSectionSpec, ...]:
    """목표 서류철의 섹션과 현재 소비 가능 상태를 고정한다."""
    return (
        DossierSectionSpec("price_risk", "가격·위험", "1M/3M/1Y/3Y/7Y 수익률·변동성·낙폭", "수익률·변동성·모멘텀", "가격 원천은 있으나 PIT vintage 원장 전"),
        DossierSectionSpec("valuation", "밸류에이션", "PER·PBR·PSR·FCF yield와 역사 비교", "비율 수준·백분위·peer spread", "PIT 계산 계약·단위 테스트 완료, 저장 관측값 없음"),
        DossierSectionSpec("fundamentals", "재무", "성장·마진·현금흐름·부채 추세", "성장·마진·레버리지·quality", "wide 원천은 있으나 분기별 vintage 재구성 전"),
        DossierSectionSpec("estimates", "컨센서스", "수준·revision·surprise 이력", "revision momentum·dispersion·surprise", "PIT observed snapshot은 있으나 7년 이력 없음"),
        DossierSectionSpec("segments", "세그먼트", "사업·지역별 규모·성장·집중도", "성장·집중도", "품질 gate를 통과한 행만 사용 가능"),
        DossierSectionSpec("ownership", "13F 보유", "보유·매수/매도 변화", "lagged ownership change", "공시 지연을 반영한 PIT 조회 가능"),
        DossierSectionSpec("macro_events", "거시·이벤트", "regime·최근/예정 이벤트", "PIT macro level·event flag", "historical replay는 fail-closed로 제외"),
        DossierSectionSpec("external_live", "외부 라이브", "뉴스·소셜 요약과 출처", "사용 안 함", "live LLM 보조만 허용"),
    )


def valuation_contract_rows() -> list[dict[str, str]]:
    """PIT 밸류에이션 계약의 사용자 검토용 요약이다."""
    return [
        {"항목": "공통", "계약": "모든 알려진 입력은 observed_at·available_at·evidence_ids를 필수로 가집니다."},
        {"항목": "시간", "계약": "입력 available_at이 as_of_at보다 늦으면 계약 생성 전에 거부합니다."},
        {"항목": "PER", "계약": "market_cap / 양수 earnings_ttm; 적자·0은 null과 not meaningful 사유입니다."},
        {"항목": "PBR", "계약": "market_cap / 양수 book_value; 0·음수는 null과 사유입니다."},
        {"항목": "PSR", "계약": "market_cap / 양수 revenue_ttm; 0·음수는 null과 사유입니다."},
        {"항목": "FCF yield", "계약": "양수 free_cash_flow_ttm / market_cap; 비양수 FCF는 null과 사유입니다."},
        {"항목": "재현성", "계약": "정규화된 입력·source_version·근거 ID를 SHA-256 input_hash에 결박합니다."},
    ]
