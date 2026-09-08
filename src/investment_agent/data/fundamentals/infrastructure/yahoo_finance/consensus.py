"""Yahoo Finance 컨센서스와 애널리스트 데이터 어댑터.

DB·오케스트레이션은 다루지 않는다. 항목별로 결측이 흔하므로 한 항목이 비어도
나머지는 그대로 돌려주고, 값 파싱 실패는 None으로 떨어뜨린다.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

from investment_agent.platform.clock import us_market_today
from investment_agent.platform.retry import network_retry
from investment_agent.data.fundamentals.domain.services.classify_report_session import resolve_session

HORIZON_BY_SOURCE_KEY = {
    "0q": "q+0",
    "+1q": "q+1",
    "0y": "fy+0",
    "+1y": "fy+1",
}
TREND_OFFSET_DAYS = {
    "7daysAgo": 7,
    "30daysAgo": 30,
    "60daysAgo": 60,
    "90daysAgo": 90,
}

def _num(value: Any) -> float | None:
    """숫자로 못 읽는 값(NaN·None·문자열)은 None으로 떨어뜨린다."""
    try:
        if value is None:
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(parsed) or not math.isfinite(parsed) else parsed


def _int(value: Any) -> int | None:
    parsed = _num(value)
    return None if parsed is None else int(parsed)


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(stamp) else stamp.date()


def _source_failure(failures: list[dict[str, str]], stage: str, exc: Exception) -> None:
    failures.append({"stage": stage, "error": repr(exc)})


@network_retry(attempts=3, max_wait=5)
def _read_attribute(ticker: yf.Ticker, name: str) -> Any:
    """실제 네트워크가 일어나는 yfinance 속성 접근을 재시도한다."""
    try:
        return getattr(ticker, name)
    except yf.exceptions.YFRateLimitError as exc:
        raise ConnectionError("Yahoo Finance rate limit") from exc


@network_retry(attempts=3, max_wait=5)
def _read_earnings_dates(ticker: yf.Ticker) -> pd.DataFrame | None:
    try:
        return ticker.get_earnings_dates(limit=24)
    except yf.exceptions.YFRateLimitError as exc:
        raise ConnectionError("Yahoo Finance rate limit") from exc


def _frame(
    ticker: yf.Ticker,
    name: str,
    failures: list[dict[str, str]],
) -> pd.DataFrame | None:
    """DataFrame 속성 하나를 안전하게 읽는다. 없거나 비면 None."""
    try:
        frame = _read_attribute(ticker, name)
    except Exception as exc:  # noqa: BLE001 - 부분 결과와 실패 상태를 함께 돌려준다
        _source_failure(failures, name, exc)
        return None
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    return frame


def _row(frame: pd.DataFrame | None, label: str) -> dict:
    if frame is None or label not in frame.index:
        return {}
    return frame.loc[label].to_dict()


def _ticker(symbol: str) -> yf.Ticker:
    return yf.Ticker(symbol)


def _add_quarter(anchor: date) -> date:
    """분기말에서 다음 분기말로. 월말 기준 회계연도는 월말을 유지한다.

    4-30 + 3개월은 7-30이 아니라 7-31이어야 한다. 애플처럼 52/53주 회계력을
    쓰는 회사는 월말이 아니므로 그대로 3개월을 더한다(하루 이틀 오차는
    근사임을 전제로 감수한다 — 정확한 기간말은 공시가 나와야 확정된다).
    """
    stamp = pd.Timestamp(anchor)
    shifted = stamp + pd.DateOffset(months=3)
    if stamp.is_month_end:
        shifted = shifted + pd.offsets.MonthEnd(0)
    return shifted.date()


def _next_quarter_end(history: pd.DataFrame | None) -> date | None:
    """직전 보고 분기말 다음 분기말을 추정한다(스냅샷을 걸어둘 구간 식별용)."""
    if history is None or history.empty:
        return None
    last = _as_date(max(history.index))
    return None if last is None else _add_quarter(last)


def _shift_period(anchor: date | None, horizon: str) -> date | None:
    """horizon별 대상 기간말. 분기 구간만 추정하고 연간 구간은 비워 둔다."""
    if anchor is None:
        return None
    if horizon == "q+0":
        return anchor
    if horizon == "q+1":
        return _add_quarter(anchor)
    return None


def _next_report(
    ticker: yf.Ticker,
    today: date,
    failures: list[dict[str, str]],
) -> tuple[date | None, datetime | None, bool | None, list[datetime]]:
    """다음 발표 예정일과 **예정 시각**, 확정 여부를 읽는다.

    `calendar`는 날짜만 준다. 장전/장후를 가르려면 시각이 필요하므로
    `get_earnings_dates()`의 tz-aware(America/New_York) 인덱스를 함께 읽는다.
    실측: JPM 06:00 ET, WMT 07:00 ET(장전) / NVDA 16:00 ET(장후).
    `isEarningsDateEstimate`는 그 날짜가 회사 확정 공지인지 야후 추정인지 알려준다.
    """
    expected_at: datetime | None = None
    past: list[datetime] = []
    try:
        # 과거 이력까지 넉넉히 읽는다. 야후는 시각 미공지 상태의 다음 발표에
        # 15:00 ET 자리표시를 넣으므로, 그 회사의 과거 습관이 보정 근거가 된다.
        frame = _read_earnings_dates(ticker)
        if frame is not None and not frame.empty:
            upcoming, history = [], []
            for stamp in frame.index:
                converted = _as_date(stamp)
                if converted is None:
                    continue
                (upcoming if converted >= today else history).append(stamp)
            if upcoming:
                expected_at = min(upcoming).to_pydatetime()
            past = [stamp.to_pydatetime() for stamp in sorted(history, reverse=True)]
    except yf.exceptions.YFEarningsDateMissing:
        pass
    except Exception as exc:  # noqa: BLE001 - calendar fallback과 실패 상태를 함께 보존한다
        _source_failure(failures, "earnings_dates", exc)

    expected_report = _as_date(expected_at) if expected_at else None
    if expected_report is None:
        try:
            calendar = _read_attribute(ticker, "calendar") or {}
            dates = calendar.get("Earnings Date") or []
            candidates = [d for d in (_as_date(d) for d in dates) if d and d >= today]
            expected_report = min(candidates) if candidates else None
        except Exception as exc:  # noqa: BLE001 - 다른 필드 수집은 계속한다
            _source_failure(failures, "calendar", exc)

    is_estimated: bool | None = None
    try:
        flag = (_read_attribute(ticker, "info") or {}).get(
            "isEarningsDateEstimate"
        )
        if flag is not None:
            is_estimated = bool(flag)
    except Exception as exc:  # noqa: BLE001 - 다른 필드 수집은 계속한다
        _source_failure(failures, "info", exc)

    return expected_report, expected_at, is_estimated, past


def fetch_consensus(symbol: str, *, today: date | None = None) -> dict:
    """한 종목의 컨센서스 일체를 읽어 표준 dict로 돌려준다.

    반환 키: snapshots(구간별 예상치·발표 일정), trend_seed(소급용),
    analyst_snapshot, source_failures.
    """
    today = today or us_market_today()
    ticker = _ticker(symbol)
    source_failures: list[dict[str, str]] = []

    earnings = _frame(ticker, "earnings_estimate", source_failures)
    revenue = _frame(ticker, "revenue_estimate", source_failures)
    trend = _frame(ticker, "eps_trend", source_failures)
    revisions = _frame(ticker, "eps_revisions", source_failures)
    history = _frame(ticker, "earnings_history", source_failures)

    anchor = _next_quarter_end(history)
    expected_report, expected_at, is_estimated, past_reports = _next_report(
        ticker, today, source_failures
    )
    expected_session = resolve_session(expected_at, past_reports)

    snapshots: list[dict] = []
    for source_key, horizon in HORIZON_BY_SOURCE_KEY.items():
        eps = _row(earnings, source_key)
        rev = _row(revenue, source_key)
        rev_counts = _row(revisions, source_key)
        if not (eps or rev or rev_counts):
            continue
        snapshots.append({
            "ticker": symbol,
            "snapshot_date": today.isoformat(),
            "horizon": horizon,
            "target_period_end": (
                d.isoformat() if (d := _shift_period(anchor, horizon)) else None
            ),
            "expected_report_date": (
                expected_report.isoformat() if expected_report and horizon == "q+0" else None
            ),
            "expected_report_at": (
                expected_at.isoformat() if expected_at and horizon == "q+0" else None
            ),
            "is_estimated": is_estimated if horizon == "q+0" else None,
            "expected_session": expected_session if horizon == "q+0" else None,
            "eps_avg": _num(eps.get("avg")),
            "eps_low": _num(eps.get("low")),
            "eps_high": _num(eps.get("high")),
            "eps_analysts": _int(eps.get("numberOfAnalysts")),
            "revenue_avg": _num(rev.get("avg")),
            "revenue_low": _num(rev.get("low")),
            "revenue_high": _num(rev.get("high")),
            "revenue_analysts": _int(rev.get("numberOfAnalysts")),
            "revisions_up_7d": _int(rev_counts.get("upLast7days")),
            "revisions_up_30d": _int(rev_counts.get("upLast30days")),
            "revisions_down_7d": _int(rev_counts.get("downLast7Days")),
            "revisions_down_30d": _int(rev_counts.get("downLast30days")),
        })

    # 발표 일정은 컨센서스 유무와 독립된 데이터다. 예상치 frame이 모두 비어도
    # q+0 envelope을 남겨 normalize 단계가 schedule만 저장할 수 있게 한다.
    if expected_report and not any(
        row["horizon"] == "q+0" for row in snapshots
    ):
        snapshots.append({
            "ticker": symbol,
            "snapshot_date": today.isoformat(),
            "horizon": "q+0",
            "target_period_end": anchor.isoformat() if anchor else None,
            "expected_report_date": expected_report.isoformat(),
            "expected_report_at": expected_at.isoformat() if expected_at else None,
            "is_estimated": is_estimated,
            "expected_session": expected_session,
            "eps_avg": None,
            "revenue_avg": None,
        })

    trend_seed = _trend_seed(symbol, trend, anchor, today)
    return {
        "snapshots": snapshots,
        "trend_seed": trend_seed,
        "analyst_snapshot": _analyst_snapshot(
            _price_target(symbol, ticker, today, source_failures),
            _recommendation(symbol, ticker, today, source_failures),
        ),
        "source_failures": source_failures,
    }


def _trend_seed(
    symbol: str, trend: pd.DataFrame | None, anchor: date | None, today: date,
) -> list[dict]:
    """eps_trend의 7/30/60/90일 전 값을 과거 스냅샷 행으로 편다.

    EPS 평균 하나뿐이라 low/high·매출은 비어 있다. 첫 수집에서 이력 시작점을
    90일 앞당기는 용도이며, 같은 날짜에 실제 스냅샷이 있으면 그쪽이 우선이다.
    """
    if trend is None:
        return []
    rows: list[dict] = []
    for source_key, horizon in HORIZON_BY_SOURCE_KEY.items():
        values = _row(trend, source_key)
        if not values:
            continue
        for column, offset in TREND_OFFSET_DAYS.items():
            value = _num(values.get(column))
            if value is None:
                continue
            rows.append({
                "ticker": symbol,
                "snapshot_date": (today - timedelta(days=offset)).isoformat(),
                "horizon": horizon,
                "target_period_end": (
                    d.isoformat() if (d := _shift_period(anchor, horizon)) else None
                ),
                "eps_avg": value,
                "source": "yfinance:eps_trend",
                "mapping_date": today.isoformat(),
            })
    return rows

def _price_target(
    symbol: str,
    ticker: yf.Ticker,
    today: date,
    failures: list[dict[str, str]],
) -> dict | None:
    try:
        raw = _read_attribute(ticker, "analyst_price_targets") or {}
    except Exception as exc:  # noqa: BLE001 - 부분 결과와 실패 상태를 함께 돌려준다
        _source_failure(failures, "analyst_price_targets", exc)
        return None
    if not raw:
        return None
    row = {
        "ticker": symbol,
        "snapshot_date": today.isoformat(),
        "target_mean": _num(raw.get("mean")),
        "target_median": _num(raw.get("median")),
        "target_high": _num(raw.get("high")),
        "target_low": _num(raw.get("low")),
    }
    keys = ("target_mean", "target_median", "target_high", "target_low")
    return row if any(row[key] is not None for key in keys) else None


def _recommendation(
    symbol: str,
    ticker: yf.Ticker,
    today: date,
    failures: list[dict[str, str]],
) -> dict | None:
    frame = _frame(ticker, "recommendations", failures)
    if frame is None or "period" not in frame.columns:
        return None
    current = frame[frame["period"] == "0m"]
    if current.empty:
        return None
    values = current.iloc[0].to_dict()
    return {
        "ticker": symbol,
        "snapshot_date": today.isoformat(),
        "strong_buy": _int(values.get("strongBuy")),
        "buy": _int(values.get("buy")),
        "hold": _int(values.get("hold")),
        "sell": _int(values.get("sell")),
        "strong_sell": _int(values.get("strongSell")),
    }


def _analyst_snapshot(
    price_target: dict | None,
    recommendation: dict | None,
) -> dict | None:
    """같은 종목·날짜인 목표주가와 의견 분포를 한 스냅샷으로 합친다."""
    if price_target is None and recommendation is None:
        return None
    source = price_target or recommendation or {}
    row = {
        "ticker": source.get("ticker"),
        "snapshot_date": source.get("snapshot_date"),
        "source": "yfinance",
        "target_mean": None,
        "target_median": None,
        "target_high": None,
        "target_low": None,
        "strong_buy": None,
        "buy": None,
        "hold": None,
        "sell": None,
        "strong_sell": None,
    }
    if price_target:
        row.update(price_target)
    if recommendation:
        row.update(recommendation)
    return row
