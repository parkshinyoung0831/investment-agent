"""서류철이 쓰는 장기 구간 통계.

`EvidenceBundle`은 feature 계산용이라 260봉까지만 담는다. 서류철은 사람과 LLM이
"지금이 역사적으로 어디쯤인가"를 판단해야 하므로 더 넓은 창을 본다. 대신 원본을
그대로 넘기지 않고 **구간별 요약과 백분위만** 만든다 — 10년치 봉을 프롬프트에 넣으면
토큰이 터지고, ML에도 원시 봉은 쓸모가 없다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping, Sequence

_TRADING_DAYS = 252

# 사람이 실제로 말하는 구간이다. 거래일 환산이라 달력 기준과 며칠 어긋난다.
PRICE_WINDOWS: tuple[tuple[str, int], ...] = (
    ("1M", 21),
    ("3M", 63),
    ("1Y", _TRADING_DAYS),
    ("3Y", _TRADING_DAYS * 3),
    ("5Y", _TRADING_DAYS * 5),
    ("7Y", _TRADING_DAYS * 7),
)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


# 일별로 인정하는 최대 간격(달력일). 주말·공휴일 때문에 하루보다 크다.
MAX_DAILY_GAP_DAYS = 4

# 창 안에서 일별 간격이 차지해야 하는 최소 비율.
# 중앙값으로 판정하면 창의 49%가 주간이어도 통과한다 — 그 구간의 연율 변동성은
# 이미 오염돼 있다. 비율로 봐야 부분 오염을 잡는다.
MIN_DAILY_GAP_RATIO = 0.90


@dataclass(frozen=True)
class WindowStat:
    """한 구간의 수익률·변동성·낙폭. 표본이 모자라면 값 대신 사유를 남긴다."""

    label: str
    window_days: int
    observations: int
    total_return: float | None = None
    annualized_volatility: float | None = None
    max_drawdown: float | None = None
    median_gap_days: float | None = None
    daily_gap_ratio: float | None = None
    is_daily: bool = True
    missing_reason: str | None = None
    volatility_missing_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.missing_reason:
            return {
                "label": self.label,
                "observations": self.observations,
                "missing_reason": self.missing_reason,
            }
        payload: dict[str, Any] = {
            "label": self.label,
            "observations": self.observations,
            "total_return": self.total_return,
            "max_drawdown": self.max_drawdown,
            "median_gap_days": self.median_gap_days,
            "daily_gap_ratio": self.daily_gap_ratio,
        }
        if self.volatility_missing_reason:
            payload["annualized_volatility_missing_reason"] = self.volatility_missing_reason
        else:
            payload["annualized_volatility"] = self.annualized_volatility
        return payload


def _bars_oldest_first(rows: Iterable[Mapping[str, Any]]) -> list[tuple[date, float]]:
    bars: list[tuple[date, float]] = []
    for row in rows:
        close = _number(row.get("close"))
        raw = str(row.get("trade_date") or "")[:10]
        if close is None or close <= 0.0 or not raw:
            continue
        try:
            bars.append((date.fromisoformat(raw), close))
        except ValueError:
            continue
    bars.sort(key=lambda item: item[0])
    return bars


def _gap_profile(days: Sequence[date]) -> tuple[float | None, float | None]:
    """구간의 중앙 간격과 '일별로 볼 수 있는 간격'의 비율을 함께 돌려준다."""
    if len(days) < 2:
        return None, None
    gaps = sorted((days[i] - days[i - 1]).days for i in range(1, len(days)))
    middle = len(gaps) // 2
    median = (
        float(gaps[middle]) if len(gaps) % 2
        else (gaps[middle - 1] + gaps[middle]) / 2.0
    )
    ratio = sum(1 for gap in gaps if gap <= MAX_DAILY_GAP_DAYS) / len(gaps)
    return median, round(ratio, 6)


def _window_stat(bars: Sequence[tuple[date, float]], label: str, window: int) -> WindowStat:
    if len(bars) <= window:
        return WindowStat(
            label=label, window_days=window, observations=len(bars),
            missing_reason=f"need_{window + 1}_closes_have_{len(bars)}",
        )
    segment = list(bars[-(window + 1):])
    days = [day for day, _ in segment]
    closes = [close for _, close in segment]
    total = closes[-1] / closes[0] - 1.0
    gap, ratio = _gap_profile(days)
    is_daily = ratio is not None and ratio >= MIN_DAILY_GAP_RATIO

    volatility = None
    volatility_reason = None
    if not is_daily:
        # 주간 수익률에 sqrt(252)를 곱하면 변동성이 2배 이상 부풀려진다.
        volatility_reason = (
            f"only_{ratio:.0%}_of_gaps_are_daily" if ratio is not None
            else "series_spacing_unknown"
        )
    else:
        returns = [
            closes[i] / closes[i - 1] - 1.0
            for i in range(1, len(closes))
            if closes[i - 1] > 0.0
        ]
        if len(returns) >= 2:
            mean = math.fsum(returns) / len(returns)
            variance = math.fsum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
            volatility = math.sqrt(variance) * math.sqrt(_TRADING_DAYS)
        else:
            volatility_reason = "not_enough_returns"

    peak = closes[0]
    drawdown = 0.0
    for close in closes:
        peak = max(peak, close)
        drawdown = min(drawdown, close / peak - 1.0)
    return WindowStat(
        label=label, window_days=window, observations=len(segment),
        total_return=total, annualized_volatility=volatility, max_drawdown=drawdown,
        median_gap_days=gap, daily_gap_ratio=ratio, is_daily=is_daily,
        volatility_missing_reason=volatility_reason,
    )


def _percentile(bars: Sequence[tuple[date, float]], window: int) -> float | None:
    """현재가가 그 구간 분포에서 몇 번째인지 0~1로 돌려준다.

    "싸다/비싸다"를 절대 수준이 아니라 자기 역사 대비로 말하게 하는 값이다. 표본
    간격이 성겨도 분위는 의미가 있으므로 일별 여부를 따지지 않는다.
    """
    if len(bars) < 2:
        return None
    segment = bars[-window:] if len(bars) > window else list(bars)
    if len(segment) < 2:
        return None
    latest = segment[-1][1]
    below = sum(1 for _, close in segment if close <= latest)
    return round(below / len(segment), 6)


def price_risk_profile(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """구간별 수익·위험과 현재가의 역사적 위치를 만든다."""
    bars = _bars_oldest_first(rows)
    if not bars:
        return {}
    windows = [_window_stat(bars, label, window) for label, window in PRICE_WINDOWS]
    daily_only = [stat for stat in windows if stat.missing_reason is None and stat.is_daily]
    return {
        "latest_close": bars[-1][1],
        "observations": len(bars),
        "earliest_trade_date": bars[0][0].isoformat(),
        "latest_trade_date": bars[-1][0].isoformat(),
        # 연율 변동성을 믿을 수 있는 최장 구간. 이보다 긴 창은 리샘플 구간이 섞인다.
        "longest_daily_window": daily_only[-1].label if daily_only else None,
        "windows": [stat.to_dict() for stat in windows],
        "price_percentile_1y": _percentile(bars, _TRADING_DAYS),
        "price_percentile_7y": _percentile(bars, _TRADING_DAYS * 7),
    }


@dataclass(frozen=True)
class AnnualPoint:
    """한 회계연도의 합산 실적. TTM이 아니라 연도 비교용이다."""

    fiscal_year: int
    quarters: int
    revenue: float | None
    net_income: float | None
    operating_income: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fiscal_year": self.fiscal_year,
            "quarters": self.quarters,
            "revenue": self.revenue,
            "net_income": self.net_income,
            "operating_margin": (
                self.operating_income / self.revenue
                if self.operating_income is not None and self.revenue not in (None, 0.0)
                else None
            ),
            "net_margin": (
                self.net_income / self.revenue
                if self.net_income is not None and self.revenue not in (None, 0.0)
                else None
            ),
        }


def _annual_points(rows: Iterable[Mapping[str, Any]]) -> list[AnnualPoint]:
    by_year: dict[int, dict[str, Any]] = {}
    for row in rows:
        year = row.get("fiscal_year")
        if year is None:
            continue
        bucket = by_year.setdefault(int(year), {"quarters": set(), "rows": []})
        period = str(row.get("fiscal_period") or "")
        if period in bucket["quarters"]:
            continue
        bucket["quarters"].add(period)
        bucket["rows"].append(row)

    def _sum(entries: list[Mapping[str, Any]], field: str) -> float | None:
        total = 0.0
        seen = False
        for entry in entries:
            value = _number(entry.get(field))
            if value is None:
                return None
            total += value
            seen = True
        return total if seen else None

    points: list[AnnualPoint] = []
    for year in sorted(by_year):
        bucket = by_year[year]
        points.append(AnnualPoint(
            fiscal_year=year,
            quarters=len(bucket["quarters"]),
            revenue=_sum(bucket["rows"], "revenue"),
            net_income=_sum(bucket["rows"], "net_income"),
            operating_income=_sum(bucket["rows"], "operating_income_loss"),
        ))
    return points


def _cagr(first: float | None, last: float | None, years: int) -> float | None:
    """음수나 0에서 출발하면 성장률이 의미를 잃으므로 만들지 않는다."""
    if first is None or last is None or years < 1:
        return None
    if first <= 0.0 or last <= 0.0:
        return None
    return (last / first) ** (1.0 / years) - 1.0


def fundamental_trend(
    rows: Iterable[Mapping[str, Any]],
    *,
    max_years: int = 7,
) -> dict[str, Any]:
    """연도별 매출·이익·마진과 장기 성장률을 만든다.

    분기가 4개 미만인 연도는 부분 연도라 성장률 계산에서 제외한다 — 3분기만 있는
    해를 온전한 해와 비교하면 성장률이 실제보다 낮게 나온다.
    """
    points = _annual_points(rows)
    if not points:
        return {}
    trimmed = points[-max_years:]
    complete = [point for point in trimmed if point.quarters >= 4]
    result: dict[str, Any] = {
        "years": [point.to_dict() for point in trimmed],
        "complete_years": len(complete),
        "partial_years": [point.fiscal_year for point in trimmed if point.quarters < 4],
    }
    if len(complete) >= 2:
        span = complete[-1].fiscal_year - complete[0].fiscal_year
        result["revenue_cagr"] = _cagr(complete[0].revenue, complete[-1].revenue, span)
        result["net_income_cagr"] = _cagr(complete[0].net_income, complete[-1].net_income, span)
        result["cagr_span_years"] = span
        margins = [
            point.operating_income / point.revenue
            for point in complete
            if point.operating_income is not None and point.revenue not in (None, 0.0)
        ]
        if len(margins) >= 2:
            result["operating_margin_first"] = margins[0]
            result["operating_margin_last"] = margins[-1]
            result["operating_margin_change"] = margins[-1] - margins[0]
    else:
        result["missing_reason"] = f"need_2_complete_years_have_{len(complete)}"
    return result


__all__ = [
    "MAX_DAILY_GAP_DAYS",
    "MIN_DAILY_GAP_RATIO",
    "PRICE_WINDOWS",
    "AnnualPoint",
    "WindowStat",
    "fundamental_trend",
    "price_risk_profile",
]
