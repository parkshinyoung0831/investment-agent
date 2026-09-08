"""SEC 13F 원문을 v1 institutional 원장에 다시 적재하는 경로."""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from investment_agent.data.institutional.repository import InstitutionalRepository
from investment_agent.platform.db.postgres import Database
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

_CIK_RE = re.compile(r"^[0-9]{10}$")
_ACCESSION_RE = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
_IDENTIFIER_RE = re.compile(r"^[A-Z0-9]{9}$")

FilingSource = Callable[[str, date], Iterable[Any]]


@dataclass(frozen=True)
class InstitutionalRefreshResult:
    managers: int
    filings: int
    positions: int
    failures: tuple[dict[str, str], ...]


def _filing_row(record: Any, manager_cik: str) -> dict[str, Any]:
    if not _CIK_RE.match(manager_cik) or str(record.manager_cik) != manager_cik:
        raise ValueError("13F record manager CIK does not match active manager")
    accession_no = str(record.accession_no)
    if not _ACCESSION_RE.match(accession_no):
        raise ValueError(f"invalid 13F accession_no: {accession_no!r}")
    if str(record.form_type) not in {"13F-HR", "13F-HR/A"}:
        raise ValueError(f"{accession_no}: unsupported form")
    if not record.report_type or not record.accepted_at or not record.source_url:
        raise ValueError(f"{accession_no}: missing required filing provenance")
    content_sha256 = str(record.content_sha256)
    if not re.fullmatch(r"[0-9a-f]{64}", content_sha256):
        raise ValueError(f"{accession_no}: invalid source content hash")
    amendment_type = record.amendment_type
    amendment_no = record.amendment_no
    if str(record.form_type).endswith("/A"):
        if amendment_type not in {"RESTATEMENT", "NEW HOLDINGS"} or not amendment_no:
            raise ValueError(f"{accession_no}: amendment metadata is incomplete")
    elif amendment_type is not None or amendment_no is not None:
        raise ValueError(f"{accession_no}: original filing has amendment metadata")
    if record.period_end > record.filing_date:
        raise ValueError(f"{accession_no}: period_end is after filing_date")
    return {
        "accession_no": accession_no,
        "manager_cik": manager_cik,
        "period_end": record.period_end.isoformat(),
        "form_type": record.form_type,
        "report_type": record.report_type,
        "filing_date": record.filing_date.isoformat(),
        "accepted_at": record.accepted_at,
        "amendment_type": amendment_type,
        "amendment_no": amendment_no,
        "reported_value_usd": record.reported_value_usd,
        "reported_line_count": record.reported_line_count,
        "confidential_omitted": record.confidential_omitted,
        "source_url": record.source_url,
        "content_sha256": content_sha256,
    }


def _position_rows(record: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for position in record.positions:
        identifier = str(position.cusip).strip().upper()
        if not _IDENTIFIER_RE.match(identifier):
            raise ValueError(f"{record.accession_no}: invalid 13F identifier {identifier!r}")
        if position.identifier_type not in {"CUSIP", "CINS"}:
            raise ValueError(f"{record.accession_no}: unsupported identifier type")
        if position.quantity_type not in {"SH", "PRN"} or position.position_kind not in {"SHARES", "PUT", "CALL"}:
            raise ValueError(f"{record.accession_no}: unsupported position type")
        rows.append({
            "accession_no": record.accession_no,
            "source_row_no": position.source_row_no,
            "issuer_name": position.issuer_name,
            "identifier": identifier,
            "identifier_type": position.identifier_type,
            "title_of_class": position.title_of_class,
            "value_usd": position.value_usd,
            "quantity": position.quantity,
            "quantity_type": position.quantity_type,
            "position_kind": position.position_kind,
            "investment_discretion": position.investment_discretion,
            "other_manager": position.other_manager,
            "voting_sole": position.voting_sole,
            "voting_shared": position.voting_shared,
            "voting_none": position.voting_none,
        })
    if int(record.reported_line_count) != int(record.parsed_line_count):
        raise ValueError(f"{record.accession_no}: SEC line count differs from parsed rows")
    if len(rows) != int(record.parsed_line_count):
        raise ValueError(f"{record.accession_no}: source row numbers were not preserved")
    reported = float(record.reported_value_usd)
    parsed = sum(float(row["value_usd"]) for row in rows)
    if abs(parsed - reported) > max(1.0, reported / 100_000):
        raise ValueError(f"{record.accession_no}: SEC reported value differs from positions")
    return rows


def refresh_institutional(
    db: Database, *, since: date, filing_source: FilingSource
) -> InstitutionalRefreshResult:
    """활성 manager별 13F를 독립 처리한다. 한 filing 실패는 재시도 대상으로 남는다."""
    repo = InstitutionalRepository(db)
    managers = repo.active_managers()
    filings = positions = 0
    failures: list[dict[str, str]] = []
    for manager in managers:
        manager_cik = str(manager["manager_cik"])
        try:
            records = filing_source(manager_cik, since)
        except Exception as exc:  # noqa: BLE001 - 다른 manager 수집은 보존한다
            log.exception("13F discovery failed manager_cik=%s", manager_cik)
            failures.append({"manager_cik": manager_cik, "error": repr(exc)})
            continue
        for record in records:
            accession_no = str(getattr(record, "accession_no", "unknown"))
            try:
                filing = _filing_row(record, manager_cik)
                position_rows = _position_rows(record)
                repo.upsert_filings([filing])
                repo.upsert_positions(position_rows)
                filings += 1
                positions += len(position_rows)
            except Exception as exc:  # noqa: BLE001 - 원천/검증 실패는 같은 manager의 다음 filing과 격리
                log.exception("13F load failed manager_cik=%s accession_no=%s", manager_cik, accession_no)
                failures.append({
                    "manager_cik": manager_cik,
                    "accession_no": accession_no,
                    "error": repr(exc),
                })
    result = InstitutionalRefreshResult(len(managers), filings, positions, tuple(failures))
    log.info("institutional_refresh %s", result)
    return result


__all__ = ["InstitutionalRefreshResult", "refresh_institutional"]
