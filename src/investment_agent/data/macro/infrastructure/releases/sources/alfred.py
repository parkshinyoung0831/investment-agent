"""ALFRED vintage adapters for first prints and revisions."""
from __future__ import annotations

import math
import os
import re
from datetime import date, timedelta
from typing import Any

import requests

from investment_agent.platform.clock import us_market_today
from investment_agent.platform.logging import get_logger
from investment_agent.platform.retry import retry_on_5xx
from investment_agent.data.macro.infrastructure.releases.sources.actuals import _fred_slot

_BASE = "https://api.stlouisfed.org/fred/series/observations"
# output_type=3/4는 한 요청에서 vintage 날짜 2,000개를 넘길 수 없다. 일별
# 정책금리처럼 vintage가 많은 family는 안전한 chunk replay가 필요하다.
_MAX_VINTAGE_WINDOW_DAYS = 1800
# FRED는 실행 호스트의 날짜가 provider의 날짜보다 앞서 있어도
# ``realtime_end=9999-12-31``을 현재 최신 vintage sentinel로 허용한다.
# CI/로컬 clock drift에서 미래 날짜를 보내 400을 내지 않도록 마지막 chunk에만 쓴다.
_FRED_REALTIME_MAX = date(9999, 12, 31)

log = get_logger(__name__)


class AlfredDataError(ValueError):
    """ALFRED response가 vintage 계약을 만족하지 않을 때 발생한다."""


def _failure_reason(exc: Exception) -> str:
    """Actions 로그에 안전하게 남길 수 있는 provider 실패 요약."""
    if isinstance(exc, AlfredDataError):
        return str(exc)
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        if response is None:
            return "HTTP error"
        message = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                message = str(payload.get("error_message") or payload.get("message") or "")
        except ValueError:
            pass
        if message:
            # URL이나 query string은 쓰지 않는다. provider의 구조화된 설명만 짧게 남긴다.
            return f"HTTP {response.status_code}: {message[:240]}"
        return f"HTTP {response.status_code}"
    return type(exc).__name__


@retry_on_5xx()
def _observations_window(
    fred_id: str,
    *,
    observation_start: date,
    output_type: int,
    realtime_start: date,
    realtime_end: date,
) -> list[dict[str, Any]]:
    _fred_slot()
    response = requests.get(
        _BASE,
        params={
            "series_id": fred_id,
            "api_key": os.environ["FRED_API_KEY"],
            "file_type": "json",
            "output_type": output_type,
            "realtime_start": realtime_start.isoformat(),
            "realtime_end": realtime_end.isoformat(),
            "observation_start": observation_start.isoformat(),
            "limit": 100000,
            "sort_order": "asc",
        },
        timeout=60,
    )
    response.raise_for_status()
    rows = response.json().get("observations")
    if not isinstance(rows, list):
        raise AlfredDataError("ALFRED observations missing")
    return rows


def _observations(fred_id: str, *, observation_start: date, output_type: int) -> list[dict[str, Any]]:
    """ALFRED vintage limit을 넘기지 않고 observation window를 읽는다."""
    realtime_start = max(observation_start, date(1776, 7, 4))
    realtime_end = us_market_today()
    if realtime_start > realtime_end:
        return []
    output: list[dict[str, Any]] = []
    cursor = realtime_start
    while cursor <= realtime_end:
        chunk_end = min(cursor + timedelta(days=_MAX_VINTAGE_WINDOW_DAYS - 1), realtime_end)
        # 마지막 요청은 provider의 현재 날짜를 추측하지 않는다. FRED의
        # 9999-12-31 sentinel은 현재까지의 vintage를 반환하므로 호스트와
        # provider 사이의 시계 차이에도 PIT replay가 fail-closed로 유지된다.
        is_last_chunk = chunk_end == realtime_end
        request_end = _FRED_REALTIME_MAX if is_last_chunk else chunk_end
        output.extend(_observations_window(
            fred_id,
            observation_start=observation_start,
            output_type=output_type,
            realtime_start=cursor,
            realtime_end=request_end,
        ))
        if is_last_chunk:
            break
        cursor = chunk_end + timedelta(days=1)
    return output


def fetch_first_prints(
    fred_id: str,
    *,
    observation_start: date,
    scale: float | None = None,
) -> list[dict[str, Any]]:
    """output_type=4의 참조기간별 최초 발표값과 알려진 최초 availability date."""
    return _parse(
        _observations(fred_id, observation_start=observation_start, output_type=4),
        scale=scale,
        source="alfred_first_print",
    )


def fetch_revisions(
    fred_id: str,
    *,
    observation_start: date,
    scale: float | None = None,
) -> list[dict[str, Any]]:
    """output_type=3의 new/revised observation을 append-only revision 후보로 변환한다."""
    return _parse_revisions(
        _observations(fred_id, observation_start=observation_start, output_type=3),
        fred_id=fred_id,
        scale=scale,
    )


def _parse(rows: list[dict[str, Any]], *, scale: float | None, source: str) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    multiplier = 1.0 if scale is None else float(scale)
    for item in rows:
        raw = item.get("value")
        if raw in (None, "", "."):
            continue
        try:
            value = float(raw) * multiplier
        except (TypeError, ValueError) as exc:
            raise AlfredDataError("ALFRED returned a non-numeric value") from exc
        if not math.isfinite(value):
            raise AlfredDataError("ALFRED returned a non-finite value")
        period, released_on = item.get("date"), item.get("realtime_start")
        if not period or not released_on:
            raise AlfredDataError("ALFRED row has no date or realtime_start")
        parsed.append({
            "ref_period": str(period),
            "released_on": str(released_on),
            "value": value,
            "source": source,
            "vintage_end": item.get("realtime_end"),
        })
    return parsed


def _parse_revisions(
    rows: list[dict[str, Any]], *, fred_id: str, scale: float | None,
) -> list[dict[str, Any]]:
    """ALFRED output_type=3의 wide vintage 열을 정규화한다.

    output_type=3은 ``date`` 하나와 ``SERIESID_YYYYMMDD`` 형태의 vintage 열을
    반환한다. output_type=4처럼 ``realtime_start``가 있는 행으로 가정하면 모든
    revision이 탈락하므로, 열 suffix를 availability date로 보존한다.
    """
    multiplier = 1.0 if scale is None else float(scale)
    prefix = f"{fred_id}_"
    pattern = re.compile(rf"^{re.escape(prefix)}(\d{{8}})$")
    parsed: list[dict[str, Any]] = []
    for item in rows:
        period = str(item.get("date") or "")
        if not period:
            raise AlfredDataError("ALFRED revision row has no observation date")
        for key, raw in item.items():
            matched = pattern.match(str(key))
            if matched is None or raw in (None, "", "."):
                continue
            try:
                value = float(raw) * multiplier
            except (TypeError, ValueError) as exc:
                raise AlfredDataError("ALFRED revision returned a non-numeric value") from exc
            if not math.isfinite(value):
                raise AlfredDataError("ALFRED revision returned a non-finite value")
            token = matched.group(1)
            try:
                released_on = date.fromisoformat(
                    f"{token[:4]}-{token[4:6]}-{token[6:]}"
                ).isoformat()
            except ValueError as exc:
                raise AlfredDataError("ALFRED revision has an invalid vintage date") from exc
            parsed.append({
                "ref_period": period,
                "released_on": released_on,
                "value": value,
                "source": "alfred_revision",
                "vintage_end": None,
            })
    return parsed


def fetch_batch(
    targets: list[dict[str, Any]],
    *,
    observation_start: date,
    revisions: bool = False,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """family 단위 실패 격리로 ALFRED data를 수집한다."""
    collected: dict[str, list[dict[str, Any]]] = {}
    failures: list[dict[str, Any]] = []
    fetch = fetch_revisions if revisions else fetch_first_prints
    for target in targets:
        series_id = str(target["series_id"])
        try:
            rows = fetch(
                str(target["fred_id"]),
                observation_start=observation_start,
                scale=target.get("scale"),
            )
            if not rows:
                # revision audit의 짧은 구간에는 변경된 vintage가 없을 수 있다.
                # 그것은 실제 원천/API 오류가 아니라 정상적인 no-op이다.
                if revisions:
                    continue
                raise AlfredDataError("ALFRED returned no matching vintages")
            collected[series_id] = rows
        except Exception as exc:  # noqa: BLE001 - source isolation.
            reason = _failure_reason(exc)
            log.warning("ALFRED %s failed (%s): %s", series_id, type(exc).__name__, reason)
            failures.append({
                "series_id": series_id,
                "step": "alfred_revision" if revisions else "alfred_first_print",
                "error": reason,
                "type": type(exc).__name__,
            })
    return collected, failures


def source_rows(setting: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ALFRED vintage row를 append-only raw-observation contract로 변환한다.

    이 변환을 backfill와 revision audit가 공유해 source/effective_at/provenance가
    달라지는 것을 막는다. `realtime_start`는 날짜 정밀도이므로 precision도 명시한다.
    """
    actual = (setting.get("source_contract") or {}).get("actual") or {}
    output: list[dict[str, Any]] = []
    for row in rows:
        output.append({
            "series_id": setting["series_id"],
            "ref_period": str(row["ref_period"]),
            "value": row["value"],
            "unit": actual["unit"],
            "provider": str(row.get("source") or "alfred"),
            "provider_code": actual.get("code"),
            "effective_at": f"{row['released_on']}T00:00:00+00:00",
            "availability_precision": "date_only",
            "provenance": {
                "provider": "ALFRED",
                "realtime_start": row["released_on"],
                "realtime_end": row.get("vintage_end"),
                "vintage_kind": row.get("source"),
            },
        })
    return output
