"""v1 macro 원천 결과를 revision-safe observation 원장에 적재한다."""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from investment_agent.data.macro.repository import MacroRepository
from investment_agent.data.macro.domain.releases.release_catalog import measure_definitions
from investment_agent.data.macro.domain.revisions import Observation
from investment_agent.platform.clock import as_date, ensure_aware
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

SourceFetcher = Callable[[str, list[dict[str, Any]], date, date], tuple[Mapping[str, Any], list[dict[str, str]]]]
SeriesValidator = Callable[[Mapping[str, Any]], Sequence[Mapping[str, Any]]]


@dataclass(frozen=True)
class MacroRefreshResult:
    series: int
    observations: int
    failures: tuple[dict[str, str], ...]


def refresh_macro(
    db: Any,
    *,
    catalog: Sequence[dict[str, Any]],
    start: date,
    end: date,
    collected_at: datetime,
    fetch: SourceFetcher,
    validate: SeriesValidator | None = None,
    persist: bool = True,
) -> MacroRefreshResult:
    """source별 결과를 독립 수집해 원천 수집 시각으로만 버전을 남긴다."""
    if start > end:
        raise ValueError("macro start must not be after end")
    repo = MacroRepository(db)
    if persist:
        repo.upsert_series(catalog)
        # 부분 수집도 지원한다. 전체 release catalog의 measure를 모두 넣으려 하면
        # 이번 실행에 등록하지 않은 series_key를 참조하게 된다.
        catalog_series = {str(row["series_id"]) for row in catalog}
        repo.upsert_measures(
            row for row in measure_definitions()
            if str(row["series_id"]) in catalog_series
        )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in catalog:
        source = str(row.get("source") or "")
        series_id = str(row.get("series_id") or "")
        if not source or not series_id:
            raise ValueError("macro catalog requires source and series_id")
        grouped.setdefault(source, []).append(dict(row))

    failures: list[dict[str, str]] = []
    written = 0
    fetched: dict[str, Any] = {}
    successful_sources: set[str] = set()
    for source, series in sorted(grouped.items()):
        try:
            values, source_failures = fetch(source, series, start, end)
        except Exception as exc:  # noqa: BLE001 - 다른 source 수집을 계속한다
            log.exception("macro source failed source=%s", source)
            failures.extend({"source": source, "series_id": str(row["series_id"]), "error": repr(exc)} for row in series)
            continue
        failures.extend(dict(item) for item in source_failures)
        fetched.update(values)
        successful_sources.add(source)
    if validate is not None:
        for check in validate(fetched):
            if str(check.get("status")) != "fail":
                continue
            series_id = str(check.get("series_id") or "")
            if series_id:
                fetched.pop(series_id, None)
            failures.append({
                "source": "quality",
                "series_id": series_id,
                "error": str(check.get("reason") or "macro quality validation failed"),
            })

    # source별 수집 결과를 모두 모은 뒤 쓰므로 교차 원천 검증이 한 번에 같은 입력을 본다.
    for source, series in sorted(grouped.items()):
        observations: list[Observation] = []
        for config in series:
            series_id = str(config["series_id"])
            if source not in successful_sources:
                continue
            raw_series = fetched.get(series_id)
            if raw_series is None:
                failures.append({"source": source, "series_id": series_id, "error": "source returned no series"})
                continue
            try:
                for timestamp, value in raw_series.items():
                    period = as_date(timestamp)
                    number = float(value)
                    if period is None or not math.isfinite(number) or not start <= period <= end:
                        continue
                    observations.append(Observation(
                        series_id=series_id, ref_period=period, value=number,
                        effective_at=ensure_aware(collected_at),
                        collected_at=ensure_aware(collected_at), time_precision="collector_seen",
                    ))
            except Exception as exc:  # noqa: BLE001 - 한 series 변환 실패는 source 전체를 막지 않는다
                failures.append({"source": source, "series_id": series_id, "error": repr(exc)})
        if persist:
            written += repo.record_observations(observations, source_code=source)
    result = MacroRefreshResult(len(catalog), written, tuple(failures))
    log.info("macro_refresh %s", result)
    return result


__all__ = ["MacroRefreshResult", "refresh_macro"]
