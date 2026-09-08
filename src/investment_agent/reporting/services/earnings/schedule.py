"""발표 예정 행을 화면·카드가 그릴 모양으로 접는 순수 변환.

Discord 카드와 Dashboard가 같은 등급 규칙을 주장해야 하므로 알림 패키지가 아니라
Reporting 계약이 소유한다. DB에 접근하지 않으므로 픽스처만으로 단위 테스트할 수 있다.

## 예정일을 어떻게 믿을 것인가

`expected_report_date`는 yfinance calendar에서 온 값이고, 두 가지 이유로 확정이 아니다.

1. **출처가 흔들린다.** 회사가 공식 공지를 내기 전에는 추정치가 실리고, 공지 뒤에도
   바뀐다. 그래서 같은 `target_period_end`의 스냅샷들을 전부 비교해 값이 바뀐 적이
   있으면 `shifted`로 표시하고, 이전 값을 함께 낸다 — 밀렸다는 사실 자체가 정보다.
2. **가리키는 사건이 다르다.** 이건 **실적 발표(보도자료)** 예정일이고, 우리 카드는
   **10-Q/10-K 제출** 시점에 나간다. 관심종목의 `period_end -> filed_at`은 중앙값
   30일인데 예정일은 기간말 +26~30일에 찍힌다 — 대체로 붙어 있지만 같은 날은 아니다.
   그래서 카드는 "이 날 카드가 온다"가 아니라 "이 주에 발표가 있다"만 주장한다.

셋째로 스냅샷 자체가 묵을 수 있다(`fundamentals_expectations`가 실패하면 갱신이 끊긴다).
기준일이 `_STALE_DAYS`보다 오래됐으면 `stale`로 표시한다.

판단할 근거를 카드가 숨기지 않도록, 작년 같은 분기의 **실제 제출일**을 함께 낸다.
"""
from __future__ import annotations

from datetime import date, timedelta

# 스냅샷이 이만큼 묵으면 예정일에 stale 표시를 단다.
_STALE_DAYS = 7

_WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")


def as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def week_window(today: date) -> tuple[date, date]:
    """today가 속한 주의 월요일~일요일. cron이 밀려도 같은 주를 가리킨다."""
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


def iso_week(day: date) -> str:
    """중복 발송 기준 키. 예: 2026-W34."""
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def _latest_by_ticker(snapshots: list[dict]) -> dict[str, dict]:
    """티커별 가장 최근 스냅샷 1건."""
    out: dict[str, dict] = {}
    for row in snapshots:
        current = out.get(str(row.get("ticker")))
        if current is None or str(row.get("snapshot_date")) > str(current.get("snapshot_date")):
            out[str(row.get("ticker"))] = row
    return out


def _latest_by_ticker_period(snapshots: list[dict]) -> dict[tuple[str, str], dict]:
    """(티커, 추정 기간)별 가장 최근 스냅샷 1건.

    주 단위 카드는 한 종목에 한 건만 실으면 되지만, 넓은 지평을 보는 화면에서는
    같은 종목의 다음 분기 예정일까지 함께 봐야 해서 기간별로 나눠 남긴다.
    """
    out: dict[tuple[str, str], dict] = {}
    for row in snapshots:
        key = (str(row.get("ticker")), str(row.get("target_period_end") or ""))
        current = out.get(key)
        if current is None or str(row.get("snapshot_date")) > str(current.get("snapshot_date")):
            out[key] = row
    return out


def _shift_history(snapshots: list[dict], ticker: str, target: str) -> list[tuple[str, date]]:
    """같은 추정 기간에 대해 관측된 (스냅샷일, 예정일) 목록 — 오름차순."""
    seen = [
        (str(row.get("snapshot_date")), as_date(row.get("expected_report_date")))
        for row in snapshots
        if str(row.get("ticker")) == ticker
        and str(row.get("target_period_end")) == target
        and as_date(row.get("expected_report_date")) is not None
    ]
    return sorted((snap, day) for snap, day in seen if day is not None)


def _prior_year_filing(filings: list[dict], ticker: str, target: date) -> dict | None:
    """작년 같은 분기의 실제 제출일 행. period_end가 1년 전에 가장 가까운 것."""
    best: tuple[int, dict] | None = None
    for row in filings:
        if str(row.get("ticker")) != ticker or not row.get("filed_at"):
            continue
        period_end = as_date(row.get("period_end"))
        if period_end is None:
            continue
        distance = abs((period_end - (target - timedelta(days=365))).days)
        if distance <= 20 and (best is None or distance < best[0]):
            best = (distance, row)
    return best[1] if best else None


def _money(value: object) -> str | None:
    """매출 컨센서스를 조/억 단위로 짧게."""
    try:
        amount = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    for unit, scale in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(amount) >= scale:
            return f"${amount / scale:,.1f}{unit}"
    return f"${amount:,.0f}"


def build_rows(
    snapshots: list[dict],
    filings: list[dict],
    names: dict[str, dict],
    today: date,
    *,
    stale_days: int = _STALE_DAYS,
) -> list[dict]:
    """이번 주에 발표가 예정된 관심종목 행 — 예정일 오름차순.

    Discord `#실적-캘린더` 카드의 기준이다. 창을 바꿔 보는 화면은
    :func:`build_rows_in_window`을 쓰고, 이 함수의 규칙은 건드리지 않는다.
    """
    start, end = week_window(today)
    return build_rows_in_window(
        snapshots,
        filings,
        names,
        today,
        start=start,
        end=end,
        stale_days=stale_days,
    )


def build_rows_in_window(
    snapshots: list[dict],
    filings: list[dict],
    names: dict[str, dict],
    today: date,
    *,
    start: date,
    end: date,
    group_by_target: bool = False,
    stale_days: int = _STALE_DAYS,
) -> list[dict]:
    """임의 구간의 발표 예정 행 — 예정일 오름차순.

    `group_by_target=True`면 (티커, 추정 기간)별로 최신 스냅샷을 남겨 같은 종목의
    다음 분기까지 함께 낸다. shifted/stale 등급과 전년 제출일 규칙은 주간 카드와 같다.
    """
    if end < start:
        raise ValueError("end must not be earlier than start")
    picked = (
        list(_latest_by_ticker_period(snapshots).items())
        if group_by_target
        else [((ticker, ""), row) for ticker, row in _latest_by_ticker(snapshots).items()]
    )
    rows: list[dict] = []
    for (ticker, _period), latest in picked:
        expected = as_date(latest.get("expected_report_date"))
        if expected is None or not (start <= expected <= end):
            continue

        snapshot_date = as_date(latest.get("snapshot_date"))
        stale = snapshot_date is None or (today - snapshot_date).days > stale_days

        target = str(latest.get("target_period_end") or "")
        history = _shift_history(snapshots, ticker, target)
        distinct = sorted({day for _, day in history})
        previous = distinct[0] if len(distinct) > 1 and distinct[0] != expected else None

        target_date = as_date(target)
        prior = _prior_year_filing(filings, ticker, target_date) if target_date else None
        name = names.get(ticker) or {}

        target_fy = latest.get("target_fiscal_year")
        target_fp = latest.get("target_fiscal_period")
        form_expected = "10-K" if str(target_fp or "").upper() in ("Q4", "FY") else "10-Q"

        rows.append({
            "ticker": ticker,
            "name": name.get("name_ko") or name.get("name") or ticker,
            "sic_industry": name.get("sic_industry"),
            "expected": expected,
            "expected_label": f"{expected.month}/{expected.day}({_WEEKDAYS[expected.weekday()]})",
            "days_until": (expected - today).days,
            "target_period_end": target_date,
            "target_fiscal_year": target_fy,
            "target_fiscal_period": target_fp,
            "form_expected": form_expected,
            # 표시 등급: 값이 밀린 적 있으면 shifted, 스냅샷이 묵었으면 stale, 아니면 estimated.
            # 어느 쪽이든 '확정'은 없다 — 출처가 확정 여부를 알려주지 않는다.
            "confidence": "shifted" if previous else "stale" if stale else "estimated",
            "previous_expected": previous,
            "snapshot_date": snapshot_date,
            "observations": len(history),
            "eps_avg": latest.get("eps_avg"),
            "eps_analysts": latest.get("eps_analysts"),
            "revenue_avg": _money(latest.get("revenue_avg")),
            "prior_filed_at": as_date(prior.get("filed_at")) if prior else None,
            "prior_period": (
                f"{prior.get('fiscal_year')} {prior.get('fiscal_period')}" if prior else None
            ),
        })
    rows.sort(
        key=lambda row: (row["expected"], row["ticker"], str(row["target_period_end"] or ""))
    )
    return rows


__all__ = [
    "as_date",
    "build_rows",
    "build_rows_in_window",
    "iso_week",
    "week_window",
]
