"""OpenFIGI의 CUSIP/CINS 식별자 매핑 어댑터."""
from __future__ import annotations

import os
import time
from collections.abc import Iterable
from dataclasses import dataclass, replace
from threading import Lock

import requests

from investment_agent.platform.logging import get_logger
from investment_agent.platform.retry import transient_retry
from investment_agent.data.institutional.domain.parser import identifier_type

log = get_logger(__name__)

_ENDPOINT = "https://api.openfigi.com/v3/mapping"
_ID_TYPE = {"CUSIP": "ID_CUSIP", "CINS": "ID_CINS"}
_REQUEST_LOCK = Lock()
_last_request_at = 0.0


@dataclass(frozen=True)
class MappingResult:
    """한 13F 식별자의 설명 가능한 매핑 결과."""

    identifier: str
    identifier_type: str
    ticker: str | None
    figi: str | None
    mapping_status: str
    source: str


def _api_key() -> str | None:
    return os.environ.get("OPENFIGI_API_KEY") or None


def _batch_size() -> int:
    return 100 if _api_key() else 10


def _request_interval() -> float:
    # 키가 없는 공개 API 한도(25 req/min)에 경계에서 닿지 않도록 여유를 둔다.
    return 6.0 / 25.0 if _api_key() else 60.0 / 24.0


def _throttle() -> None:
    """이 프로세스의 모든 OpenFIGI 요청 사이에 일관된 간격을 둔다.

    모든 요청 직전에 공유 시계를 확인해 primary·fallback·재시도까지 하나의
    속도 제한을 따른다.
    """
    global _last_request_at
    with _REQUEST_LOCK:
        remaining = _request_interval() - (time.monotonic() - _last_request_at)
        if remaining > 0:
            time.sleep(remaining)
        _last_request_at = time.monotonic()


def _normalize_identifier(value: str) -> str:
    normalized = str(value).strip().upper().replace(" ", "")
    if len(normalized) != 9 or not normalized.isalnum():
        raise ValueError(f"invalid 13F identifier: {value!r}")
    return normalized


def _normalize_ticker(value: object) -> str | None:
    ticker = (
        str(value or "").strip().upper().replace(".", "-").replace("/", "-")
    )
    return ticker or None


@transient_retry(attempts=3)
def _map_batch(jobs: list[tuple[str, str]]) -> list[dict]:
    """OpenFIGI job 순서와 응답 순서를 1:1로 유지한다."""
    _throttle()
    headers = {"Content-Type": "application/json"}
    api_key = _api_key()
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key
    response = requests.post(
        _ENDPOINT,
        json=[
            {
                "idType": _ID_TYPE[id_kind],
                "idValue": identifier,
                "exchCode": "US",
            }
            for identifier, id_kind in jobs
        ],
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _result_for(
    identifier: str,
    id_kind: str,
    response: dict,
    *,
    source: str,
) -> MappingResult:
    hits = response.get("data") or []
    candidates: dict[tuple[str, str | None], dict] = {}
    for hit in hits:
        ticker = _normalize_ticker(hit.get("ticker"))
        if ticker:
            candidates[(ticker, str(hit.get("figi") or "") or None)] = hit
    if not candidates:
        return MappingResult(
            identifier=identifier,
            identifier_type=id_kind,
            ticker=None,
            figi=None,
            mapping_status="not_found",
            source=source,
        )
    tickers = {ticker for ticker, _figi in candidates}
    if len(tickers) != 1:
        return MappingResult(
            identifier=identifier,
            identifier_type=id_kind,
            ticker=None,
            figi=None,
            mapping_status="ambiguous",
            source=source,
        )
    ticker = next(iter(tickers))
    hit = next(item for (candidate, _), item in candidates.items() if candidate == ticker)
    return MappingResult(
        identifier=identifier,
        identifier_type=id_kind,
        ticker=ticker,
        figi=str(hit.get("figi") or "") or None,
        mapping_status="mapped",
        source=source,
    )


def _request_jobs(
    jobs: list[tuple[str, str]], *, source: str
) -> tuple[dict[str, MappingResult], int]:
    """타입별 OpenFIGI job을 rate limit에 맞춰 실행한다."""
    results: dict[str, MappingResult] = {}
    requests_made = 0
    size = _batch_size()
    for index in range(0, len(jobs), size):
        batch = jobs[index : index + size]
        payload = _map_batch(batch)
        requests_made += 1
        for (identifier, id_kind), response in zip(batch, payload, strict=False):
            results[identifier] = _result_for(
                identifier, id_kind, response or {}, source=source
            )
    return results, requests_made


def map_identifiers(identifiers: Iterable[str]) -> tuple[dict[str, MappingResult], int]:
    """CUSIP/CINS의 올바른 primary lookup과 안전한 반대 타입 fallback을 수행한다.

    CINS 판별은 표준의 국가 문자 규칙을 사용하지만, 응답이 없을 때는 반대 OpenFIGI
    타입도 조회한다. 즉 식별자 형식의 경계 사례가 영구 NULL 캐시로 굳지 않는다.
    """
    unique = list(dict.fromkeys(_normalize_identifier(value) for value in identifiers))
    primary_jobs = [(value, identifier_type(value)) for value in unique]
    primary, requests_made = _request_jobs(primary_jobs, source="openfigi_primary")

    unresolved = [
        value for value in unique
        if primary[value].mapping_status in {"not_found", "ambiguous"}
    ]
    if unresolved:
        fallback_jobs = [
            (value, "CUSIP" if primary[value].identifier_type == "CINS" else "CINS")
            for value in unresolved
        ]
        fallback, fallback_requests = _request_jobs(
            fallback_jobs, source="openfigi_fallback"
        )
        requests_made += fallback_requests
        for value in unresolved:
            candidate = fallback[value]
            if candidate.mapping_status == "mapped":
                primary[value] = replace(
                    candidate,
                    identifier_type=primary[value].identifier_type,
                )
            else:
                # Preserve the primary result, but make it explicit that both
                # identifier namespaces were exhausted.  A bare NULL would
                # otherwise hide whether the fallback was ever attempted.
                primary[value] = replace(
                    primary[value],
                    source="openfigi_primary+openfigi_fallback",
                )

    log.info(
        "openfigi mapped identifiers=%d requests=%d batch_size=%d",
        len(unique), requests_made, _batch_size(),
    )
    return primary, requests_made


__all__ = ["MappingResult", "map_identifiers"]
