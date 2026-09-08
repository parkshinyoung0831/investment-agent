"""발표 이력에서 재구성한 EPS 예상치 스냅샷을 만든다."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Any

from investment_agent.data.fundamentals.domain.services.match_reported_earnings import (
    match_reported_earnings,
)

HISTORICAL_EPS_SOURCE = "yfinance:earnings_dates"


@dataclass(frozen=True)
class HistoricalEpsEstimateBatch:
    """저장 가능 행과 건너뛴 사유를 함께 전달한다."""

    snapshots: list[dict[str, Any]]
    skipped: list[dict[str, str | None]]


def _finite_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def build_historical_eps_estimates(
    flash_rows: list[dict[str, Any]],
    reported_earnings: Mapping[str, Mapping[str, float | None]],
) -> HistoricalEpsEstimateBatch:
    """실적 속보 회계키에 Yahoo의 과거 EPS 예상치를 정확히 붙인다.

    Yahoo 이력은 발표 당시의 마지막 일별 컨센서스 스냅샷이 아니므로 반드시
    ``reconstructed``로 저장한다. 매출 예상치는 이 원천이 제공하지 않아 만들지 않는다.
    """
    snapshots_by_key: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    skipped: list[dict[str, str | None]] = []

    for flash in sorted(
        flash_rows,
        key=lambda row: (
            str(row.get("ticker") or ""),
            str(row.get("filed_at") or ""),
            str(row.get("accession_no") or ""),
        ),
    ):
        ticker = str(flash.get("ticker") or "").upper()
        filed_at = str(flash.get("filed_at") or "")
        matched = match_reported_earnings(reported_earnings, filed_at)
        if matched is None:
            skipped.append({"ticker": ticker or None, "reason": "report_date_unmatched"})
            continue
        report_date, values = matched
        eps_estimate = _finite_number(values.get("eps_estimate"))
        if eps_estimate is None:
            skipped.append({"ticker": ticker or None, "reason": "eps_estimate_missing"})
            continue
        try:
            fiscal_year = int(flash["fiscal_year"])
        except (KeyError, TypeError, ValueError):
            skipped.append({"ticker": ticker or None, "reason": "fiscal_year_missing"})
            continue
        fiscal_period = str(flash.get("fiscal_period") or "")
        period_end = str(flash.get("period_end") or "")
        if not ticker or fiscal_period not in {"Q1", "Q2", "Q3", "Q4", "FY"} or not period_end:
            skipped.append({"ticker": ticker or None, "reason": "fiscal_period_unresolved"})
            continue
        key = (ticker, fiscal_year, fiscal_period, report_date)
        snapshots_by_key.setdefault(key, {
            "ticker": ticker,
            "target_fiscal_year": fiscal_year,
            "target_fiscal_period": fiscal_period,
            "target_period_end": period_end,
            "snapshot_date": report_date,
            "snapshot_kind": "reconstructed",
            "source": HISTORICAL_EPS_SOURCE,
            "source_horizon": "q+0",
            "eps_avg": eps_estimate,
        })

    return HistoricalEpsEstimateBatch(
        snapshots=list(snapshots_by_key.values()),
        skipped=skipped,
    )


__all__ = [
    "HISTORICAL_EPS_SOURCE",
    "HistoricalEpsEstimateBatch",
    "build_historical_eps_estimates",
]
