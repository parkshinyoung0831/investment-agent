"""대시보드 실적·컨센서스·성장률·서프라이즈 계산."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from investment_agent.dashboard.calculations._common import (
    _records,
    finite_number,
)

def free_cash_flow(row: Mapping[str, Any]) -> float | None:
    """영업현금흐름과 자본지출이 모두 있을 때만 ``OCF - CapEx``를 반환한다."""
    if not isinstance(row, Mapping):
        return None
    operating_cash_flow = finite_number(row.get("net_cash_from_operating_activities"))
    capital_expenses = finite_number(row.get("capital_expenses"))
    if operating_cash_flow is None or capital_expenses is None:
        return None
    return operating_cash_flow - capital_expenses


def sec_gaap_diluted_eps(row: Mapping[str, Any]) -> float | None:
    """SEC GAAP 보통주 귀속 순이익과 희석평균주식수가 모두 있을 때 EPS를 계산한다."""
    if not isinstance(row, Mapping):
        return None
    numerator = finite_number(row.get("net_income_to_common_shareholders"))
    denominator = finite_number(row.get("shares_fully_diluted_average"))
    if numerator is None or denominator is None or denominator <= 0.0:
        return None
    return numerator / denominator


_CONSENSUS_QUARTERS = frozenset({"Q1", "Q2", "Q3", "Q4"})


def latest_estimate_overview(
    consensus_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """(종목, 대상 회계기간)별 가장 최근 관측 컨센서스 1건만 남긴다.

    ``earnings_estimates``는 같은 기간을 여러 날 관측한 이력이라 화면에 그대로 올리면
    한 종목이 여러 줄이 된다. 발표 예정일·애널리스트 목표주가는 이 표에 없으므로 붙이지
    않는다 — 없는 값을 만들지 않고 그대로 비워 둔다.
    """
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in _records(consensus_rows):
        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue
        key = (
            ticker,
            str(row.get("target_fiscal_year") or ""),
            str(row.get("target_fiscal_period") or ""),
        )
        current = latest.get(key)
        if current is None or str(row.get("snapshot_date") or "") > str(
            current.get("snapshot_date") or ""
        ):
            latest[key] = dict(row)
    return sorted(
        latest.values(),
        key=lambda row: (
            str(row.get("target_period_end") or ""),
            str(row.get("ticker") or ""),
        ),
    )


def pre_release_consensus(
    core_rows: Iterable[Mapping[str, Any]],
    consensus_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """공시된 분기마다 **공시일 이하** 마지막 관측 컨센서스를 붙인다.

    ``snapshot_date < filed_at``을 지키지 않으면 발표 뒤에 갱신된 값을 '시장의 기대'라고
    부르게 되므로, 공시일을 모르는 행은 컨센서스 없이 남긴다. EPS 서프라이즈는 같은 provider가 준 조정 EPS 쌍으로만
    계산한다 — SEC GAAP EPS와 기준이 달라 섞으면 없는 서프라이즈가 생긴다.
    """
    by_target: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in _records(consensus_rows):
        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue
        key = (
            ticker,
            str(row.get("target_fiscal_year") or ""),
            str(row.get("target_fiscal_period") or ""),
        )
        by_target.setdefault(key, []).append(dict(row))
    for rows in by_target.values():
        rows.sort(key=lambda row: str(row.get("snapshot_date") or ""))

    out: list[dict[str, Any]] = []
    for core in _records(core_rows):
        if str(core.get("fiscal_period") or "") not in _CONSENSUS_QUARTERS:
            continue
        ticker = str(core.get("ticker") or "").upper()
        filed_at = str(core.get("filed_at") or "")
        key = (
            ticker,
            str(core.get("fiscal_year") or ""),
            str(core.get("fiscal_period") or ""),
        )
        snapshot: dict[str, Any] = {}
        if filed_at:
            snapshot = next(
                (
                    row
                    for row in reversed(by_target.get(key, []))
                    if str(row.get("snapshot_date") or "") <= filed_at
                ),
                {},
            )
        out.append(
            {
                "ticker": ticker,
                "fiscal_year": core.get("fiscal_year"),
                "fiscal_period": core.get("fiscal_period"),
                "period_end": core.get("period_end"),
                "filed_at": core.get("filed_at"),
                "snapshot_date": snapshot.get("snapshot_date"),
                "source": snapshot.get("source"),
                "eps_avg": snapshot.get("eps_avg"),
                "eps_low": snapshot.get("eps_low"),
                "eps_high": snapshot.get("eps_high"),
                "eps_analysts": snapshot.get("eps_analysts"),
                "revenue_avg": snapshot.get("revenue_avg"),
                "revenue_low": snapshot.get("revenue_low"),
                "revenue_high": snapshot.get("revenue_high"),
                "revenue_analysts": snapshot.get("revenue_analysts"),
            }
        )
    return sorted(
        out,
        key=lambda row: (str(row.get("period_end") or ""), str(row.get("ticker") or "")),
        reverse=True,
    )


def quarter_growth(core_rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """분기 wide 행에서 전년 동기 대비 성장률과 마진 변화를 만든다.

    같은 회계분기의 한 해 전 행과 짝지어 계산한다. 달력 날짜 근사가 아니라
    ``(fiscal_year - 1, fiscal_period)`` 키로 맞춰야 비-12월 결산사가 어긋나지 않는다.
    전년 동기 행이 없으면 추정하지 않고 ``None``을 남긴다.
    """
    quarters = [
        dict(row)
        for row in _records(core_rows)
        if str(row.get("fiscal_period") or "") in _CONSENSUS_QUARTERS
    ]
    by_key = {
        (
            str(row.get("ticker") or "").upper(),
            str(row.get("fiscal_year") or ""),
            str(row.get("fiscal_period") or ""),
        ): row
        for row in quarters
    }

    def margin(row: Mapping[str, Any], column: str) -> float | None:
        numerator = finite_number(row.get(column))
        revenue = finite_number(row.get("revenue"))
        if numerator is None or revenue in (None, 0.0):
            return None
        return numerator / revenue

    def growth(current: Any, previous: Any) -> float | None:
        current_value = finite_number(current)
        previous_value = finite_number(previous)
        if current_value is None or previous_value in (None, 0.0):
            return None
        return current_value / previous_value - 1.0

    def delta(current: float | None, previous: float | None) -> float | None:
        return None if current is None or previous is None else current - previous

    out: list[dict[str, Any]] = []
    for row in quarters:
        ticker = str(row.get("ticker") or "").upper()
        try:
            prior_year = str(int(str(row.get("fiscal_year"))) - 1)
        except (TypeError, ValueError):
            prior_year = ""
        prior = by_key.get(
            (ticker, prior_year, str(row.get("fiscal_period") or "")), {}
        )
        out.append(
            {
                "ticker": ticker,
                "fiscal_year": row.get("fiscal_year"),
                "fiscal_period": row.get("fiscal_period"),
                "period_end": row.get("period_end"),
                "revenue_yoy": growth(row.get("revenue"), prior.get("revenue")),
                "net_income_yoy": growth(row.get("net_income"), prior.get("net_income")),
                "operating_margin_delta_yoy": delta(
                    margin(row, "operating_income_loss"),
                    margin(prior, "operating_income_loss") if prior else None,
                ),
                "gross_margin_delta_yoy": delta(
                    margin(row, "gross_profit"),
                    margin(prior, "gross_profit") if prior else None,
                ),
            }
        )
    return sorted(out, key=lambda row: str(row.get("period_end") or ""))


def historical_surprise_series(
    core_rows: Iterable[Mapping[str, Any]],
    consensus_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """과거 분기별 컨센서스 대비 실제 실적(EPS 및 매출)의 서프라이즈 이력을 계산한다.

    ``pre_release_consensus``를 기반으로 분기별 실제치와 사전 관측 기대치를 매칭하고,
    매출/EPS의 차이(diff), 서프라이즈 비율(surprise_pct), 비트/미스(beat/miss/inline)
    상태 및 연속 상회(consecutive beats) 기록을 시계열로 구성한다.
    """
    pre_consensus = pre_release_consensus(core_rows, consensus_rows)
    quarters = [
        dict(row)
        for row in _records(core_rows)
        if str(row.get("fiscal_period") or "") in _CONSENSUS_QUARTERS
    ]
    core_by_key = {
        (
            str(row.get("ticker") or "").upper(),
            str(row.get("fiscal_year") or ""),
            str(row.get("fiscal_period") or ""),
        ): row
        for row in quarters
    }

    records: list[dict[str, Any]] = []
    for item in pre_consensus:
        ticker = str(item.get("ticker") or "").upper()
        fy = str(item.get("fiscal_year") or "")
        fp = str(item.get("fiscal_period") or "")
        core = core_by_key.get((ticker, fy, fp), {})

        rev_actual = finite_number(core.get("revenue"))
        rev_est = finite_number(item.get("revenue_avg"))
        rev_diff = None
        rev_surprise_pct = None
        rev_status = "unknown"
        if rev_actual is not None and rev_est is not None and rev_est != 0.0:
            rev_diff = rev_actual - rev_est
            rev_surprise_pct = rev_diff / abs(rev_est)
            if rev_surprise_pct > 0.005:
                rev_status = "beat"
            elif rev_surprise_pct < -0.005:
                rev_status = "miss"
            else:
                rev_status = "inline"
        elif rev_actual is not None and rev_est is not None and rev_est == 0.0:
            rev_diff = rev_actual
            rev_status = "inline" if rev_actual == 0 else ("beat" if rev_actual > 0 else "miss")

        eps_actual = finite_number(core.get("eps_diluted_gaap"))
        if eps_actual is None:
            eps_actual = finite_number(core.get("eps_basic_gaap"))
        eps_est = finite_number(item.get("eps_avg"))
        eps_diff = None
        eps_surprise_pct = None
        eps_status = "unknown"
        if eps_actual is not None and eps_est is not None:
            eps_diff = eps_actual - eps_est
            if eps_est != 0.0:
                eps_surprise_pct = eps_diff / abs(eps_est)
            if eps_diff > 0.005:
                eps_status = "beat"
            elif eps_diff < -0.005:
                eps_status = "miss"
            else:
                eps_status = "inline"

        records.append(
            {
                "ticker": ticker,
                "fiscal_year": item.get("fiscal_year"),
                "fiscal_period": item.get("fiscal_period"),
                "period_end": item.get("period_end"),
                "filed_at": item.get("filed_at"),
                "snapshot_date": item.get("snapshot_date"),
                "revenue_actual": rev_actual,
                "revenue_estimate": rev_est,
                "revenue_diff": rev_diff,
                "revenue_surprise_pct": rev_surprise_pct,
                "revenue_status": rev_status,
                "eps_actual": eps_actual,
                "eps_estimate": eps_est,
                "eps_diff": eps_diff,
                "eps_surprise_pct": eps_surprise_pct,
                "eps_status": eps_status,
            }
        )

    # 연속 비트/미스 계산을 위해 오래된 순으로 정렬
    records.sort(key=lambda r: (str(r.get("ticker") or ""), str(r.get("period_end") or "")))

    by_ticker_records: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        by_ticker_records.setdefault(str(r["ticker"]), []).append(r)

    final_out: list[dict[str, Any]] = []
    for _t, t_records in by_ticker_records.items():
        rev_streak = 0
        eps_streak = 0
        for r in t_records:
            if r["revenue_status"] == "beat":
                rev_streak += 1
            elif r["revenue_status"] == "miss":
                rev_streak = 0
            if r["eps_status"] == "beat":
                eps_streak += 1
            elif r["eps_status"] == "miss":
                eps_streak = 0
            r["consecutive_revenue_beats"] = rev_streak
            r["consecutive_eps_beats"] = eps_streak
            final_out.append(r)

    # 대시보드 표시용 최신순(내림차순) 정렬
    final_out.sort(
        key=lambda r: (str(r.get("period_end") or ""), str(r.get("ticker") or "")),
        reverse=True,
    )
    return final_out
