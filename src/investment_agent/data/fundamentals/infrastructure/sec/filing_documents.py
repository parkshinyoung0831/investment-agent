"""SEC 공시 목록과 XBRL instance 문서 어댑터."""
from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import PurePosixPath
from typing import Any

from investment_agent.data.universe.infrastructure.sources import sec

_DATA_BASE = sec.DATA_BASE
_ARCHIVE_BASE = sec.ARCHIVE_BASE
_DAILY_INDEX_BASE = f"{_ARCHIVE_BASE}/edgar/daily-index"
_SUBMISSIONS = f"{_DATA_BASE}/submissions/CIK{{cik}}.json"
_MASTER_INDEX_RE = re.compile(r"^master\.(\d{8})\.idx$")


def _get_json(url: str) -> dict[str, Any]:
    return sec.get_json(url)


def _get_text_optional(url: str) -> str | None:
    return sec.get_text_optional(url)


def _get_bytes_optional(url: str) -> bytes | None:
    return sec.get_bytes_optional(url)


def _padded_cik(cik: str | int) -> str:
    return sec.padded_cik(cik)


def _archive_cik(cik: str | int) -> int:
    return sec.archive_cik(cik)


def _iso_date(value: str | None) -> str:
    if not value:
        return ""
    value = str(value)
    if "-" in value:
        return value[:10]
    if len(value) >= 8:
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    return value


def submissions(cik: str | int) -> dict[str, Any]:
    """기업 CIK의 SEC submissions 문서를 반환한다."""
    return _get_json(_SUBMISSIONS.format(cik=_padded_cik(cik)))


def _filing_section(document: dict[str, Any]) -> dict[str, Any]:
    return document.get("filings", {}).get("recent", {}) or document


def _filings_from_document(
    document: dict[str, Any],
    *,
    forms: set[str],
) -> list[dict]:
    recent = _filing_section(document)
    # SEC submissions JSON의 서식 배열 키는 `form`이다. 다른 필드가 전부 camelCase라
    # `form_type`으로 잘못 읽기 쉬운데, 그러면 목록이 조용히 비어 세그먼트 공시가
    # 한 건도 발견되지 않는다(에러가 아니라 0건으로 끝난다).
    form_values = recent.get("form", []) or []
    accessions = recent.get("accessionNumber", []) or []
    report_dates = recent.get("reportDate", []) or []
    filing_dates = recent.get("filingDate", []) or []
    accepted_dates = recent.get("acceptanceDateTime", []) or []
    primary_documents = recent.get("primaryDocument", []) or []
    is_xbrl_values = recent.get("isXBRL", []) or []

    out: list[dict] = []
    for idx, filing_form in enumerate(form_values):
        if filing_form not in forms:
            continue
        accession_no = accessions[idx] if idx < len(accessions) else None
        report_date = report_dates[idx] if idx < len(report_dates) else None
        if not accession_no or not report_date:
            continue
        is_xbrl = is_xbrl_values[idx] if idx < len(is_xbrl_values) else True
        if str(is_xbrl).lower() in {"0", "false", "none"}:
            continue
        filing_date = filing_dates[idx] if idx < len(filing_dates) else None
        accepted_date = (
            accepted_dates[idx] if idx < len(accepted_dates) else filing_date
        )
        primary_document = (
            primary_documents[idx] if idx < len(primary_documents) else None
        )
        out.append(
            {
                "accession_no": str(accession_no),
                "form_type": str(filing_form),
                "report_date": _iso_date(str(report_date)),
                "filing_date": _iso_date(str(filing_date or accepted_date or "")),
                "accepted_date": _iso_date(str(accepted_date or filing_date or "")),
                "primary_document": str(primary_document or ""),
            }
        )
    return out


def filings_filed_since(
    cik: str | int,
    *,
    forms: Iterable[str],
    cutoff: date,
) -> list[dict]:
    """filing date 기준 cutoff 이후 recent 공시를 반환한다."""
    rows = _filings_from_document(submissions(cik), forms=set(forms))
    return [
        row
        for row in rows
        if row["filing_date"] and row["filing_date"] >= cutoff.isoformat()
    ]


def _quarter(day: date) -> int:
    return (day.month - 1) // 3 + 1


def _available_daily_index_urls(start: date, end: date) -> list[str]:
    quarters: set[tuple[int, int]] = set()
    day = start
    while day <= end:
        quarters.add((day.year, _quarter(day)))
        day += timedelta(days=1)

    urls: list[tuple[date, str]] = []
    for year, quarter in sorted(quarters):
        base = f"{_DAILY_INDEX_BASE}/{year}/QTR{quarter}"
        listing = _get_json(f"{base}/index.json")
        for item in listing.get("directory", {}).get("item", []) or []:
            name = str(item.get("name") or "")
            match = _MASTER_INDEX_RE.match(name)
            if not match:
                continue
            file_day = date.fromisoformat(
                f"{match.group(1)[:4]}-{match.group(1)[4:6]}-{match.group(1)[6:8]}"
            )
            if start <= file_day <= end:
                urls.append((file_day, f"{base}/{name}"))
    return [url for _, url in sorted(urls)]


def parse_daily_index_ciks(
    text: str,
    *,
    tracked_ciks: set[int],
    forms: Iterable[str],
) -> set[int]:
    """daily master index에서 추적 대상 form 제출 CIK만 추린다."""
    allowed = set(forms)
    out: set[int] = set()
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) != 5 or parts[2].strip() not in allowed:
            continue
        try:
            cik = int(parts[0])
        except ValueError:
            continue
        if cik in tracked_ciks:
            out.add(cik)
    return out


def recent_filing_ciks(
    *,
    tracked_ciks: set[int],
    forms: Iterable[str],
    end: date,
    lookback_days: int,
) -> tuple[set[int], int]:
    """겹침 daily index 구간에서 실제 공시가 있었던 CIK만 반환한다."""
    if lookback_days < 1:
        raise ValueError("lookback_days must be at least 1")

    start = end - timedelta(days=lookback_days - 1)
    changed: set[int] = set()
    files_read = 0
    for url in _available_daily_index_urls(start, end):
        text = _get_text_optional(url)
        if text is None:
            continue
        files_read += 1
        changed.update(
            parse_daily_index_ciks(
                text,
                tracked_ciks=tracked_ciks,
                forms=forms,
            )
        )
    if files_read == 0:
        raise RuntimeError(
            f"no SEC daily index files available from {start} through {end}"
        )
    return changed, files_read


def _is_instance_candidate(name: str) -> bool:
    lower = name.lower()
    if not lower.endswith((".xml", ".htm", ".html")):
        return False
    blocked = (
        "_cal.xml",
        "_def.xml",
        "_lab.xml",
        "_pre.xml",
        "-index.xml",
        "filingsummary.xml",
        "index.html",
    )
    return not any(lower.endswith(suffix) for suffix in blocked)


def _find_xbrl_document(cik_int: int, accession_nodash: str) -> str | None:
    url = f"{_ARCHIVE_BASE}/edgar/data/{cik_int}/{accession_nodash}/index.json"
    items = _get_json(url).get("directory", {}).get("item", [])
    candidates = [
        item["name"]
        for item in items
        if item.get("name") and _is_instance_candidate(item["name"])
    ]
    if not candidates:
        return None

    xml = [name for name in candidates if name.lower().endswith(".xml")]
    if xml:
        return min(xml, key=len)

    html = [
        name
        for name in candidates
        if name.lower().endswith((".htm", ".html"))
        and not name.lower().startswith("r")
    ]
    return min(html or candidates, key=len)


def fetch_xbrl_document(
    cik: str | int,
    accession_no: str,
    primary_document: str | None = None,
) -> bytes | None:
    """공시의 inline XBRL/instance 문서를 반환한다."""
    cik_int = _archive_cik(cik)
    accession_nodash = accession_no.replace("-", "")
    base = f"{_ARCHIVE_BASE}/edgar/data/{cik_int}/{accession_nodash}"

    if primary_document:
        filename = PurePosixPath(primary_document).name
        document = _get_bytes_optional(f"{base}/{filename}")
        if document is not None:
            return document

    filename = _find_xbrl_document(cik_int, accession_nodash)
    if not filename:
        return None
    return _get_bytes_optional(f"{base}/{filename}")
