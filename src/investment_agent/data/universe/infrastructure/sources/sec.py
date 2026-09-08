"""SEC EDGAR 공통 HTTP·submissions·archive 헬퍼."""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import PurePosixPath
from typing import Any

import requests

from investment_agent.platform.retry import transient_retry

DATA_BASE = "https://data.sec.gov"
ARCHIVE_BASE = "https://www.sec.gov/Archives"
_REQUEST_GAP_SEC = float(os.environ.get("SEC_REQUEST_GAP_SEC", "0.12"))

_RATE_LOCK = threading.Lock()
_NEXT_REQUEST_AT = 0.0
_THREAD_LOCAL = threading.local()


@dataclass(frozen=True)
class SecFiling:
    """SEC submissions 문서의 공시 한 건."""

    accession_no: str
    form_type: str
    report_date: str
    filing_date: str
    accepted_at: str | None
    primary_document: str
    items: str | None = None


def user_agent() -> str:
    """SEC 정책에 맞는 연락처 포함 User-Agent를 반환한다."""
    value = os.environ.get("EDGAR_USER_AGENT", "").strip()
    if not value:
        raise RuntimeError(
            "EDGAR_USER_AGENT is required "
            "(for example: 'investment-agent contact@example.com')"
        )
    return value


def padded_cik(cik: str | int) -> str:
    """CIK를 SEC submissions용 10자리 문자열로 정규화한다."""
    return str(cik).strip().lstrip("0").zfill(10)


def archive_cik(cik: str | int) -> int:
    """CIK를 SEC archive 경로용 정수로 정규화한다."""
    return int(str(cik).strip().lstrip("0"))


def _headers(accept: str) -> dict[str, str]:
    return {
        "User-Agent": user_agent(),
        "Accept": accept,
        "Accept-Encoding": "gzip, deflate",
    }


def _session() -> requests.Session:
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        _THREAD_LOCAL.session = session
    return session


def _throttle() -> None:
    """동시 worker를 합쳐 SEC 요청 간 최소 간격을 보장한다."""
    global _NEXT_REQUEST_AT
    with _RATE_LOCK:
        now = time.monotonic()
        reserved_at = max(now, _NEXT_REQUEST_AT)
        _NEXT_REQUEST_AT = reserved_at + _REQUEST_GAP_SEC
    wait = reserved_at - now
    if wait > 0:
        time.sleep(wait)


@transient_retry(attempts=5)
def request(
    url: str,
    *,
    accept: str,
    timeout: int = 60,
    allow_not_found: bool = False,
) -> requests.Response:
    """SEC GET 요청을 공통 throttle·retry 정책으로 실행한다."""
    _throttle()
    response = _session().get(
        url,
        headers=_headers(accept),
        timeout=timeout,
    )
    if allow_not_found and response.status_code == 404:
        return response
    response.raise_for_status()
    return response


def get_json(url: str) -> Any:
    return request(url, accept="application/json").json()


def get_text_optional(url: str) -> str | None:
    response = request(
        url,
        accept="text/plain",
        allow_not_found=True,
    )
    return None if response.status_code == 404 else response.text


def get_bytes_optional(url: str) -> bytes | None:
    response = request(
        url,
        accept="application/xml,text/xml,text/html,*/*",
        allow_not_found=True,
    )
    return None if response.status_code == 404 else response.content


def submissions(cik: str | int) -> dict[str, Any]:
    """기업·기관 CIK의 SEC submissions 문서를 반환한다."""
    return get_json(f"{DATA_BASE}/submissions/CIK{padded_cik(cik)}.json")


def _iso_date(value: Any) -> str:
    text = str(value or "")
    if "-" in text:
        return text[:10]
    if len(text) >= 8:
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def submission_filings(
    document: dict[str, Any],
    *,
    forms: Iterable[str],
) -> list[SecFiling]:
    """submissions current/fragment 문서에서 지정 form 공시를 추출한다."""
    recent = document.get("filings", {}).get("recent", {}) or document
    wanted = set(forms)
    # SEC submissions JSON에서 서식 배열의 키만 `form`이다(나머지는 camelCase).
    # `form_type`으로 읽으면 목록이 조용히 비어 공시가 한 건도 발견되지 않는다.
    form_values = recent.get("form", []) or []
    rows: list[SecFiling] = []

    def value(name: str, index: int) -> Any:
        values = recent.get(name, []) or []
        return values[index] if index < len(values) else None

    for index, form_type in enumerate(form_values):
        if form_type not in wanted:
            continue
        accession_no = str(value("accessionNumber", index) or "").strip()
        filing_date = _iso_date(value("filingDate", index))
        report_date = _iso_date(value("reportDate", index))
        if not accession_no or not filing_date:
            continue
        rows.append(
            SecFiling(
                accession_no=accession_no,
                form_type=str(form_type),
                report_date=report_date,
                filing_date=filing_date,
                accepted_at=(
                    str(value("acceptanceDateTime", index) or "").strip()
                    or None
                ),
                primary_document=str(
                    value("primaryDocument", index) or ""
                ).strip(),
                items=(str(value("items", index) or "").strip() or None),
            )
        )
    return rows


def filings_filed_since(
    cik: str | int,
    *,
    forms: Iterable[str],
    cutoff: date,
) -> list[SecFiling]:
    """filing date 기준 cutoff 이후 공시를 현재·과거 submissions에서 찾는다."""
    meta = submissions(cik)
    wanted = set(forms)
    rows = submission_filings(meta, forms=wanted)

    for item in meta.get("filings", {}).get("files", []) or []:
        filing_to = _iso_date(item.get("filingTo"))
        name = str(item.get("name") or "")
        if not name or (filing_to and filing_to < cutoff.isoformat()):
            continue
        fragment = get_json(f"{DATA_BASE}/submissions/{name}")
        rows.extend(submission_filings(fragment, forms=wanted))

    unique = {
        row.accession_no: row
        for row in rows
        if row.filing_date >= cutoff.isoformat()
    }
    return sorted(
        unique.values(),
        key=lambda row: (
            row.filing_date,
            row.accepted_at or "",
            row.accession_no,
        ),
    )


def filing_archive_base(cik: str | int, accession_no: str) -> str:
    accession_nodash = accession_no.replace("-", "")
    return (
        f"{ARCHIVE_BASE}/edgar/data/{archive_cik(cik)}/"
        f"{accession_nodash}"
    )


def filing_document_url(
    cik: str | int,
    accession_no: str,
    document: str,
) -> str:
    """submissions의 중첩 표시 경로를 실제 archive 파일명으로 바꾼다."""
    filename = PurePosixPath(document).name
    return f"{filing_archive_base(cik, accession_no)}/{filename}"


def filing_homepage_url(cik: str | int, accession_no: str) -> str:
    return (
        f"{filing_archive_base(cik, accession_no)}/"
        f"{accession_no}-index.html"
    )


def filing_archive_items(cik: str | int, accession_no: str) -> list[dict]:
    """공시 archive의 파일 목록을 반환한다."""
    payload = get_json(f"{filing_archive_base(cik, accession_no)}/index.json")
    return payload.get("directory", {}).get("item", []) or []
