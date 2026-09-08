"""공시 직전에 시장이 뭘 기대했는지를 고르고 카드 모양으로 접는 순수 변환.

reporting/notifications/earnings_report.py가 읽어 온 estimates 행만 받아 쓰고 Supabase를 직접 건드리지 않으므로,
픽스처만으로 단위 테스트할 수 있다.

## 회계기간과 시점

컨센서스는 `target_fiscal_year`·`target_fiscal_period`로 어느 실적인지 고정하고,
`snapshot_date < filed_at`으로 공시 전에 시장이 알 수 있었던 값만 고른다.

## 핵심 규칙 세 가지

1. **회계분기말 ≠ 달력 분기말.** 수집 단계가 yfinance의 상대 구간을 실제
   `fiscal_year`·`fiscal_period`로 표준화한다. 여기서는 날짜 근사치가 아니라 그 키로 맞춘다.
2. **재구성 시드는 실제 스냅샷이 아니다.** `snapshot_kind='reconstructed'`는 카드 선택에서
   제외한다.
3. **너무 오래된 스냅샷은 '발표 직전'이 아니다.** 분기 하나가 통째로 지난 값을 "시장의
   기대"라고 부르면 안 되므로 `_MAX_LEAD_DAYS` 상한을 둔다.

## EPS를 카드의 GAAP 값과 비교하지 않는 이유

카드의 희석 EPS는 `financial_versions` 순이익÷희석주식수, 즉 **GAAP**이다. 컨센서스 EPS는 보통
**조정(non-GAAP)**이라 기준이 다르다. 실측 괴리는 정상 분기에도 TSLA 기준 21~66%였고,
회계 Q4 행은 파생 과정 탓에 부호까지 뒤집혔다(AAPL·NVDA·KO가 흑자 분기에 음수 EPS).
그대로 빼면 없는 서프라이즈를 만들어낸다.

그래서 EPS 서프라이즈는 **`earnings_estimates`와 `earnings_results`의 (기준 예상, 실제) 쌍만** 쓴다.
둘 다 같은 출처가 같은 기준으로 준 값이라 자기들끼리는 정합한다. 매출은 이런 문제가
없어(매출은 매출이다) `earnings_results.revenue_actual`와 직접 비교한다.
"""
from __future__ import annotations

from datetime import date

from investment_agent.notifications.earnings_report.capital import f

# 회계기간 종료일과 발표 행의 기준일 사이에서 미래 분기를 가르는 허용 폭.
_PERIOD_END_TOLERANCE_DAYS = 25
# 공시일로부터 이만큼 이전까지의 스냅샷만 '발표 직전'으로 인정한다.
_MAX_LEAD_DAYS = 120
# surprise_pct는 분수로 저장된다(0.0269 = +2.69%).
#
# yfinance는 실제·예상의 기준이 어긋난 쌍을 섞어 준다. 관심종목 실측 분포를 보면
# 정상 서프라이즈는 한 자릿수~30%대에 모이고(AAPL 3~7%, KO 3~6%, NVDA 3~6%,
# TSLA -38~+17%), 그 밖은 예상치 분모가 0에 가깝거나 실제가 일회성 이익을 포함한
# 경우다(INTC +3162%·+2109%, GOOGL +91%·+214%, UBER +353%·-82%).
# 그래서 ±50%를 넘으면 '서프라이즈'라고 단정하지 않고 기준이 다르다고 표시한다.
# 진짜 큰 서프라이즈를 놓치는 쪽이, 없는 서프라이즈를 만드는 쪽보다 낫다.
_SURPRISE_SANITY = 0.5


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def pick_snapshot(
    snapshots: list[dict],
    ticker: str,
    filed_at: object,
    *,
    fiscal_year: object | None,
    fiscal_period: object | None,
    max_lead: int = _MAX_LEAD_DAYS,
) -> dict | None:
    """공시 분기를 겨냥한, 공시 직전의 마지막 진짜 스냅샷.

    조건이 하나라도 안 맞으면 None — 카드는 블록을 통째로 생략한다.
    """
    filed = _as_date(filed_at)
    if filed is None or fiscal_year is None or fiscal_period is None:
        return None

    eligible = []
    for row in snapshots:
        if str(row.get("ticker")) != ticker:
            continue
        if row.get("snapshot_kind") != "observed":
            continue
        snapped = _as_date(row.get("snapshot_date"))
        if snapped is None:
            continue
        if not snapped < filed:
            continue  # 발표 뒤에 찍힌 값은 '기대'가 아니라 결과를 반영한 값이다
        if (filed - snapped).days > max_lead:
            continue
        target_period = str(fiscal_period)
        if (
            str(row.get("target_fiscal_year")) != str(fiscal_year)
            or str(row.get("target_fiscal_period")) != target_period
        ):
            continue
        eligible.append((snapped, row))

    if not eligible:
        return None
    return max(eligible, key=lambda pair: pair[0])[1]


def pick_next_quarter(snapshots: list[dict], picked: dict | None) -> dict | None:
    """같은 스냅샷이 본 **다음 회계분기** 기대치.

    발표 직전 시점을 그대로 유지해야 하므로 새 스냅샷을 고르지 않고, 이미 고른
    스냅샷과 같은 날짜의 q+1 행만 쓴다. 발표 뒤 갱신된 값을 섞으면 '그때 시장이
    무엇을 기대했나'가 아니라 지금 기대가 된다.
    """
    if not picked:
        return None
    target_year = picked.get("target_fiscal_year")
    target_period = str(picked.get("target_fiscal_period") or "")
    next_year, next_period = _next_fiscal_period(target_year, target_period)
    if next_year is None or next_period is None:
        return None
    for row in snapshots:
        if (
            str(row.get("ticker")) == str(picked.get("ticker"))
            and str(row.get("snapshot_date")) == str(picked.get("snapshot_date"))
            and str(row.get("target_fiscal_year")) == str(next_year)
            and str(row.get("target_fiscal_period")) == next_period
            and row.get("snapshot_kind") == "observed"
        ):
            estimate = f(row.get("eps_avg"))
            if estimate is None:
                return None
            target = _as_date(row.get("target_period_end"))
            return {
                "estimate": estimate,
                "revenue": f(row.get("revenue_avg")),
                "analysts": row.get("eps_analysts"),
                "target_period_end": target,
                "label": f"{target.year % 100}·{target.month}월 예상" if target else "다음 분기 예상",
            }
    return None


def _next_fiscal_period(year: object, period: str) -> tuple[int | None, str | None]:
    try:
        parsed_year = int(year)
    except (TypeError, ValueError):
        return None, None
    order = ("Q1", "Q2", "Q3", "Q4")
    if period not in order:
        return None, None
    index = order.index(period)
    return (parsed_year + 1, "Q1") if index == 3 else (parsed_year, order[index + 1])


def pick_price_target(
    targets: list[dict],
    ticker: str,
    filed_at: object,
    *,
    max_lead: int = _MAX_LEAD_DAYS,
) -> dict | None:
    """공시 직전의 마지막 목표주가 스냅샷.

    카드는 가격·기술 지표를 공시 직전 거래일로 고정한다. 목표주가만 공시 뒤 값을
    쓰면 '발표를 보고 조정된 목표'가 섞여 같은 시점 비교가 깨진다.
    """
    filed = _as_date(filed_at)
    if filed is None:
        return None
    eligible = []
    for row in targets:
        if str(row.get("ticker")) != ticker:
            continue
        snapped = _as_date(row.get("snapshot_date"))
        if snapped is None or not snapped < filed or (filed - snapped).days > max_lead:
            continue
        eligible.append((snapped, row))
    if not eligible:
        return None

    row = max(eligible, key=lambda pair: pair[0])[1]
    mean = f(row.get("target_mean"))
    if mean is None:
        return None
    return {
        "snapshot_date": _as_date(row.get("snapshot_date")),
        "mean": mean,
        "median": f(row.get("target_median")),
        "high": f(row.get("target_high")),
        "low": f(row.get("target_low")),
    }


def _surprise(actual: float | None, estimate: float | None, stored: float | None) -> float | None:
    """서프라이즈 비율(분수). 저장값을 우선 쓰되 없으면 직접 계산한다."""
    if stored is not None:
        return stored
    if actual is None or estimate is None or estimate == 0:
        return None
    return (actual - estimate) / abs(estimate)


def surprise_rows(surprises: list[dict], period_end: object, *, limit: int = 8) -> list[dict]:
    """공시 분기까지의 서프라이즈 이력 — quarter_end 오름차순, 최근 limit개.

    마지막 항목이 이번 분기다(카드는 그걸 시계열의 끝점으로 강조한다).
    """
    cutoff = _as_date(period_end)
    out = []
    for row in surprises:
        quarter = _as_date(row.get("quarter_end"))
        if quarter is None:
            continue
        if cutoff is not None and (quarter - cutoff).days > _PERIOD_END_TOLERANCE_DAYS:
            continue  # 공시 시점엔 아직 모르는 미래 분기
        actual, estimate = f(row.get("eps_actual")), f(row.get("eps_estimate"))
        ratio = _surprise(actual, estimate, f(row.get("surprise_pct")))
        out.append({
            "quarter_end": quarter,
            "actual": actual,
            "estimate": estimate,
            "surprise": ratio,
            # 기준이 어긋난 값을 '서프라이즈 N%'로 단정하지 않는다.
            "reliable": ratio is not None and abs(ratio) <= _SURPRISE_SANITY,
        })
    out.sort(key=lambda item: item["quarter_end"])
    return out[-limit:]


def _position(value: float | None, low: float | None, high: float | None) -> float | None:
    """low~high 구간에서 value의 위치(0~1). 범위 밖이면 끝에 붙인다."""
    if value is None or low is None or high is None or high <= low:
        return None
    return min(1.0, max(0.0, (value - low) / (high - low)))


def build(
    row: dict,
    snapshots: list[dict],
    surprises: list[dict],
    targets: list[dict] | None = None,
) -> dict | None:
    """공시 행 → '시장 기대' 블록 데이터. 쓸 게 하나도 없으면 None.

    컨센서스 스냅샷이 없어도 서프라이즈 이력만 있으면 블록은 낸다(반대도 같다).
    둘 다 없으면 None이고, 카드는 그 행을 통째로 생략한다.
    """
    ticker = str(row.get("ticker") or "")
    snapshot = pick_snapshot(
        snapshots, ticker, row.get("filed_at"),
        fiscal_year=row.get("fiscal_year"), fiscal_period=row.get("fiscal_period"),
    )
    period_end = row.get("period_end")
    history = surprise_rows(surprises, period_end)
    price_target = pick_price_target(targets or [], ticker, row.get("filed_at"))

    eps: dict | None = None
    revenue: dict | None = None
    revisions: dict | None = None

    if snapshot:
        eps_avg = f(snapshot.get("eps_avg"))
        # 이번 분기의 실제 EPS는 GAAP 계산값이 아니라 같은 출처의 조정 기준 값이다.
        latest = history[-1] if history else None
        actual = latest["actual"] if latest else None
        if eps_avg is not None:
            eps = {
                "estimate": eps_avg,
                "low": f(snapshot.get("eps_low")),
                "high": f(snapshot.get("eps_high")),
                "analysts": snapshot.get("eps_analysts"),
                "actual": actual,
                "surprise": latest["surprise"] if latest else None,
                "reliable": bool(latest and latest["reliable"]),
                "position": _position(
                    actual, f(snapshot.get("eps_low")), f(snapshot.get("eps_high"))
                ),
            }

        revenue_avg = f(snapshot.get("revenue_avg"))
        revenue_actual = f(row.get("revenue"))
        if revenue_avg is not None:
            revenue = {
                "estimate": revenue_avg,
                "low": f(snapshot.get("revenue_low")),
                "high": f(snapshot.get("revenue_high")),
                "analysts": snapshot.get("revenue_analysts"),
                "actual": revenue_actual,
                "surprise": (
                    (revenue_actual - revenue_avg) / abs(revenue_avg)
                    if revenue_actual is not None and revenue_avg else None
                ),
                "position": _position(
                    revenue_actual, f(snapshot.get("revenue_low")), f(snapshot.get("revenue_high"))
                ),
            }

        up = snapshot.get("revisions_up_30d")
        down = snapshot.get("revisions_down_30d")
        if up is not None or down is not None:
            up_count, down_count = int(up or 0), int(down or 0)
            revisions = {
                "up": up_count,
                "down": down_count,
                "up_7d": snapshot.get("revisions_up_7d"),
                "down_7d": snapshot.get("revisions_down_7d"),
                "net": up_count - down_count,
            }

    # 목표주가만 있어도 '주가' 블록에 녹일 게 있으므로 블록 생성 조건에 넣는다.
    if not (eps or revenue or history or price_target):
        return None
    return {
        "next_quarter": pick_next_quarter(snapshots, snapshot),
        "price_target": price_target,
        "snapshot_date": _as_date(snapshot.get("snapshot_date")) if snapshot else None,
        "lead_days": (
            (_as_date(row.get("filed_at")) - _as_date(snapshot.get("snapshot_date"))).days
            if snapshot and _as_date(row.get("filed_at")) and _as_date(snapshot.get("snapshot_date"))
            else None
        ),
        "eps": eps,
        "revenue": revenue,
        "revisions": revisions,
        "history": history,
    }
