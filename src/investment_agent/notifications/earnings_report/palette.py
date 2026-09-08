"""실적 카드 색 기준(SSOT) — DESIGN-system.md 토큰과 상태 색 규칙을 한 곳에서 정의.

원칙:
1. 방향(direction) 지표: 변화량 부호로 색. 높을수록 좋은 지표는 증가=초록, 낮을수록 좋은
   지표(부채비율·주식수 등)는 감소=초록. ±0.3% 이내는 보합(회색).
2. 밸류에이션 백분위: 역사적 위치 20/40/60/80 구간으로 색. 단 PER류는 높을수록 비쌈(빨강),
   수익률류(FCF·배당·이익수익률)는 높을수록 매력(초록)이라 방향을 뒤집는다.
3. 절대 수준 기준이 업종마다 다른 지표(ROE·ROA·ROIC·마진 등)는 색을 칠하지 않고 중립(흰색).
   객관적 기준이 없는 곳에 색으로 단정하지 않는다.

기본 화면은 다크 표면을 사용한다. 상승·하락 색은 텍스트와 작은 마커에만 쓰고
넓은 배경이나 막대 채움에는 사용하지 않는다.
"""
from __future__ import annotations

PRIMARY = "#3182f6"
PRIMARY_ACTIVE = "#003ecc"
INK = "#0a0b0d"
BODY = "#5b616e"
MUTED = "#7c828a"
MUTED_SOFT = "#a8acb3"
HAIRLINE = "#dee1e6"
HAIRLINE_SOFT = "#eef0f3"
CANVAS = "#ffffff"
SURFACE_SOFT = "#f7f7f7"
SURFACE_STRONG = "#eef0f3"
SURFACE_DARK = "#0a0b0d"
SURFACE_DARK_ELEVATED = "#16181c"
ON_DARK = "#ffffff"
ON_DARK_SOFT = "#a8acb3"

GREEN = "#05b169"     # 개선·저평가·건전
AMBER = "#f4b000"     # 주의
RED = "#cf202f"       # 악화·고평가·위험
NEUTRAL = ON_DARK     # 중립 수치(색 판단 보류)

_FLAT = 0.003  # ±0.3% 이내 변화는 보합 처리


def direction(delta: float | None, *, higher_better: bool = True) -> str:
    """변화량 → 색. higher_better=False면 부호 반전(예: 부채비율 상승=빨강)."""
    if delta is None:
        return MUTED
    d = delta if higher_better else -delta
    if d > _FLAT:
        return GREEN
    if d < -_FLAT:
        return RED
    return MUTED


# 밸류에이션 지표가 "높을수록 비싼가". 수익률 지표는 False(높을수록 매력).
EXPENSIVE_WHEN_HIGH = {
    "pe": True, "pb": True, "ps": True, "ev_ebitda": True, "ev_sales": True,
    "fcf_yield": False, "earnings_yield": False, "dividend_yield": False,
}


def percentile_color(pct: float | None, metric_key: str) -> str:
    """역사적 백분위(0~100) → 색. 비쌈 지표는 높을수록 빨강, 수익률 지표는 반전."""
    if pct is None:
        return NEUTRAL
    # 모든 지표를 "비쌈 정도(0~100, 높을수록 부담)"로 환산해 동일 규칙 적용.
    expensiveness = pct if EXPENSIVE_WHEN_HIGH.get(metric_key, True) else 100 - pct
    if expensiveness >= 80:
        return RED
    if expensiveness >= 60:
        return AMBER
    if expensiveness <= 20:
        return GREEN
    return MUTED  # 20~60 구간은 역사적 중립


def value_vs_avg_color(current: float | None, average: float | None, metric_key: str) -> str:
    """현재값이 기간 평균보다 싼지(초록)/비싼지(빨강). 수익률류는 방향 반전.

    역사적 밸류에이션 우측 1·3·5·7년 평균 칸 색에 쓴다. ±3% 이내는 보합(중립).
    """
    if current is None or average is None or average == 0:
        return NEUTRAL
    ratio = current / average
    # 모든 지표를 "비쌈 배수(>1=비쌈)"로 환산해 동일 규칙 적용.
    expensiveness = ratio if EXPENSIVE_WHEN_HIGH.get(metric_key, True) else (1 / ratio if ratio else 0)
    if expensiveness >= 1.10:
        return RED
    if expensiveness >= 1.03:
        return AMBER
    if expensiveness <= 0.90:
        return GREEN
    return MUTED


def gauge_zone(value: float | None, *, good: float, bad: float, lower_better: bool) -> str:
    """건전성 게이지 색 — good/bad 임계로 초록/노랑/빨강 (charts.gauges와 동일 규칙)."""
    if value is None:
        return MUTED
    if lower_better:
        return GREEN if value <= good else (AMBER if value <= bad else RED)
    return GREEN if value >= good else (AMBER if value >= bad else RED)
