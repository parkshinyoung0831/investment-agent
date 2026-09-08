"""매크로 원천 시계열의 단위·범위와 환율 교차검증을 담당한다."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

import numpy as np
import pandas as pd


def validate_series(indicator: dict, series: pd.Series) -> None:
    """지표별 수집 계약을 확인하고 명백한 단위·스파이크 오류를 차단한다.

    ``source_params.validation``은 원천값을 화면 단위로 정규화한 뒤 적용한다.
    범위는 포함 경계이며, 변화율은 연속 관측치 간 절대 변화율(%)이다.
    """
    if not isinstance(series, pd.Series):
        raise TypeError(
            f"source returned {type(series).__name__}, expected Series"
        )
    cleaned = series.dropna().sort_index()
    if cleaned.empty:
        return
    try:
        observation_dates = pd.DatetimeIndex(pd.to_datetime(cleaned.index)).normalize()
    except (TypeError, ValueError) as exc:
        raise ValueError("source returned an invalid observation date index") from exc
    if observation_dates.has_duplicates:
        raise ValueError("source returned duplicate observation dates")

    values = pd.to_numeric(cleaned, errors="coerce")
    if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError("source returned a non-finite value")

    params = indicator.get("source_params") or {}
    contract = params.get("validation") or {}
    minimum = contract.get("min_value")
    maximum = contract.get("max_value")
    if minimum is not None and (values < float(minimum)).any():
        actual = float(values.min())
        raise ValueError(f"value {actual:g} is below configured minimum {float(minimum):g}")
    if maximum is not None and (values > float(maximum)).any():
        actual = float(values.max())
        raise ValueError(f"value {actual:g} is above configured maximum {float(maximum):g}")

    max_change = contract.get("max_abs_change_pct")
    if max_change is not None and len(values) >= 2:
        changes = values.pct_change(fill_method=None).abs() * 100.0
        actual = float(changes.max(skipna=True))
        if np.isfinite(actual) and actual > float(max_change):
            raise ValueError(
                f"absolute change {actual:.2f}% exceeds configured maximum "
                f"{float(max_change):g}%"
            )


def _comparison(
    series_id: str,
    primary: pd.Series,
    reference: pd.Series,
    *,
    median_tolerance_pct: float,
    min_overlap: int,
) -> dict:
    aligned = pd.concat(
        [primary.rename("primary"), reference.rename("reference")],
        axis=1,
        sort=False,
    ).dropna()
    if len(aligned) < min_overlap:
        return {
            "series_id": series_id,
            "status": "skipped",
            "reason": "insufficient_overlap",
            "overlap": len(aligned),
        }

    errors = (
        (aligned["primary"] - aligned["reference"]).abs()
        / aligned["reference"].abs()
        * 100.0
    )
    median_error = float(errors.median())
    p95_error = float(errors.quantile(0.95))
    return {
        "series_id": series_id,
        "status": "pass" if median_error <= median_tolerance_pct else "fail",
        "overlap": len(aligned),
        "through": aligned.index.max().date().isoformat(),
        "median_abs_pct": round(median_error, 4),
        "p95_abs_pct": round(p95_error, 4),
        "tolerance_pct": median_tolerance_pct,
    }


def audit_fx_cross_sources(
    series_by_id: dict[str, pd.Series],
    fetch_fred: Callable[[str, date, date], pd.Series],
    *,
    start: date,
    end: date,
    median_tolerance_pct: float = 3.0,
    min_overlap: int = 5,
) -> list[dict]:
    """BOK 환율을 독립적인 연준/FRED 관측치와 교차검증한다.

    ECOS를 주 원천으로 유지한다. FRED의 DEXKOUS(원/달러)와
    DEXJPUS(엔/달러)로 만든 원/100엔은 발표가 더 늦으므로 최근 겹치는
    구간만 검증하며, FRED 장애나 겹침 부족은 주 원천 적재를 막지 않는다.
    """
    targets = {sid for sid in ("USDKRW", "JPYKRW") if sid in series_by_id}
    if not targets:
        return []

    audit_start = max(start, end - timedelta(days=120))
    try:
        fred_usdkrw = fetch_fred("DEXKOUS", audit_start, end).dropna().sort_index()
        fred_jpy_per_usd = fetch_fred("DEXJPUS", audit_start, end).dropna().sort_index()
    except Exception as exc:  # noqa: BLE001 - optional reference outages cannot block primary data
        return [
            {
                "series_id": sid,
                "status": "skipped",
                "reason": "reference_unavailable",
                "error_type": type(exc).__name__,
            }
            for sid in sorted(targets)
        ]

    checks: list[dict] = []
    if "USDKRW" in targets:
        checks.append(
            _comparison(
                "USDKRW",
                series_by_id["USDKRW"],
                fred_usdkrw,
                median_tolerance_pct=median_tolerance_pct,
                min_overlap=min_overlap,
            )
        )
    if "JPYKRW" in targets:
        fred_krw_per_100jpy = (fred_usdkrw / fred_jpy_per_usd * 100.0).dropna()
        checks.append(
            _comparison(
                "JPYKRW",
                series_by_id["JPYKRW"],
                fred_krw_per_100jpy,
                median_tolerance_pct=median_tolerance_pct,
                min_overlap=min_overlap,
            )
        )
    return checks
