"""8-K 실적 속보를 회사의 실제 회계분기에 붙인다.

달력 월로 분기를 매기면 안 된다. 1월 결산 유통사(WMT·TJX·TGT·ROST·HD·LOW)는
2026-08-20에 낸 8-K가 **FY2027 Q2**(2026-07-31 종료)인데, 달력 월(08월)로 매기면
FY2026 Q3가 된다. 실측 23건 중 20건이 그렇게 어긋나 있었고, 그 결과 10-Q와
대조하면 260일 차이나는 엉뚱한 분기끼리 붙었다.

회사의 실제 회계력은 `financial_versions`의 (fiscal_year, fiscal_period, period_end)에
있다. 아직 10-Q가 안 나온 최신 분기는 그 회계력에서 앞으로 밀어 만든다.
"""
from __future__ import annotations

from datetime import date, timedelta

QUARTERS = ("Q1", "Q2", "Q3", "Q4")

# 분기 종료 뒤 8-K가 나오기까지의 정상 범위. 이 밖이면 어느 분기인지 못 믿는다.
MIN_LAG_DAYS = 0
MAX_LAG_DAYS = 75
# 미래로 밀어 만들 때 한 분기의 길이.
_QUARTER_DAYS = 91
# 마지막 실제 분기에서 몇 분기까지 밀어 만들 것인가. 8-K는 10-Q보다 한두 분기
# 앞설 뿐이다. 회계력이 1년 넘게 낡았다면 밀어 만든 값을 믿을 수 없으므로
# 판정을 포기한다 — 12분기를 밀어 자신 있게 틀린 분기를 붙이는 쪽이 더 나쁘다.
MAX_PROJECTED_QUARTERS = 4


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _next_period(year: int, period: str) -> tuple[int, str]:
    index = QUARTERS.index(period)
    if index == len(QUARTERS) - 1:
        return year + 1, QUARTERS[0]
    return year, QUARTERS[index + 1]


def fiscal_calendar(rows: list[dict]) -> list[dict]:
    """financial_versions 행을 period_end 순 회계력으로 정리한다."""
    calendar: dict[tuple[int, str], dict] = {}
    for row in rows:
        period = str(row.get("fiscal_period") or "")
        period_end = _as_date(row.get("period_end"))
        try:
            year = int(row.get("fiscal_year"))
        except (TypeError, ValueError):
            continue
        if period not in QUARTERS or period_end is None:
            continue
        calendar[(year, period)] = {
            "fiscal_year": year,
            "fiscal_period": period,
            "period_end": period_end,
        }
    return sorted(calendar.values(), key=lambda item: item["period_end"])


def project_forward(
    calendar: list[dict], until: date, *, max_quarters: int = MAX_PROJECTED_QUARTERS
) -> list[dict]:
    """마지막 알려진 분기 뒤를 회계력 간격으로 밀어 만든다.

    8-K는 10-Q보다 먼저 나오므로, 속보가 가리키는 분기는 아직
    `financial_versions`에 없는 것이 정상이다.
    """
    if not calendar:
        return []
    projected = list(calendar)
    last = projected[-1]
    # 최근 4개 간격의 중앙값으로 분기 길이를 잡는다. 52/53주 회계력도 흡수한다.
    gaps = [
        (projected[i]["period_end"] - projected[i - 1]["period_end"]).days
        for i in range(max(1, len(projected) - 4), len(projected))
    ]
    step = sorted(gaps)[len(gaps) // 2] if gaps else _QUARTER_DAYS
    if not 60 <= step <= 120:
        step = _QUARTER_DAYS

    year, period, period_end = last["fiscal_year"], last["fiscal_period"], last["period_end"]
    projected_count = 0
    while period_end < until and projected_count < max_quarters:
        projected_count += 1
        year, period = _next_period(year, period)
        period_end = period_end + timedelta(days=step)
        projected.append({
            "fiscal_year": year,
            "fiscal_period": period,
            "period_end": period_end,
            "is_projected": True,
        })
    return projected


def resolve_flash_period(
    calendar_rows: list[dict],
    filing_date: object,
) -> tuple[int, str, str] | None:
    """8-K 공시일에 대응하는 (회계연도, 회계분기, 기간종료일)을 돌려준다.

    실적 8-K는 그 분기가 끝난 직후에 나온다. 따라서 공시일 **이전**에 끝난
    분기 중 가장 가까운 것이 그 속보의 대상이다. 정상 범위를 벗어나면
    추정하지 않고 None을 돌려준다 — 틀린 분기에 붙이면 10-Q와 대조가 깨지고
    카드가 엉뚱한 기간을 보여 준다.
    """
    filed = _as_date(filing_date)
    if filed is None:
        return None
    calendar = project_forward(fiscal_calendar(calendar_rows), filed)
    if not calendar:
        return None

    ended = [row for row in calendar if row["period_end"] <= filed]
    if not ended:
        return None
    candidate = ended[-1]
    # 밀어 만든 분기가 상한에 걸려 공시일에 못 미치면 회계력이 너무 낡은 것이다.
    lag = (filed - candidate["period_end"]).days
    if not MIN_LAG_DAYS <= lag <= MAX_LAG_DAYS:
        return None
    return (
        candidate["fiscal_year"],
        candidate["fiscal_period"],
        candidate["period_end"].isoformat(),
    )
