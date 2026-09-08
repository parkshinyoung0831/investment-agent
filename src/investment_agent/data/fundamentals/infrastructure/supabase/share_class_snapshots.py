"""Supabase repository for fundamentals.share_class_snapshots."""
from __future__ import annotations

from datetime import datetime

from typing import Any

from investment_agent.operations.runtime import utc_now_iso
from investment_agent.platform.logging import get_logger
from investment_agent.platform.db.postgres import sb, select_all_paged, select_paged_in_chunks
from investment_agent.data.universe.persistence import select_security_ids_by_ticker

SCHEMA_FUNDAMENTALS = "fundamentals"
T_SHARE_CLASS_SNAPSHOTS = "share_class_snapshots"
T_FILINGS = "filings"
log = get_logger(__name__)


def replace_shares_outstanding(
    cik: str,
    *,
    filed_from: str,
    rows: list[dict[str, Any]],
) -> dict[str, int]:
    """한 CIK·filing window를 교체하고 canonical filings와 연결한다."""
    padded = str(cik).strip().zfill(10)
    ingested_at = utc_now_iso()
    ticker_values = sorted({str(row.get("mapped_ticker") or "").upper() for row in rows if row.get("mapped_ticker")})
    security_ids = select_security_ids_by_ticker(ticker_values) if ticker_values else {}
    payload: list[dict[str, Any]] = []
    filings: dict[str, dict[str, Any]] = {}
    allowed = {
        "cik", "share_class_key", "share_class_axis", "share_class_member",
        "share_class_title", "as_of_date", "shares_outstanding", "accession_no",
        "source_concept", "ticker_mapping_status", "ingested_at",
    }
    for row in rows:
        accession = str(row.get("accession_no") or "")
        mapped_ticker = str(row.get("mapped_ticker") or "").upper()
        payload_row = {
            key: value for key, value in row.items() if key in allowed
        }
        payload_row.update({
            "cik": padded,
            "ingested_at": ingested_at,
            "mapped_security_id": security_ids.get(mapped_ticker),
        })
        payload.append(payload_row)
        if accession:
            filings[accession] = {
                "accession_no": accession,
                "cik": padded,
                "form_type": row.get("form_type") or "10-Q",
                "filing_date": row.get("filed_at") or row.get("accepted_at"),
                "report_date": row.get("as_of_date"),
                "source": "sec_edgar",
            }
    if filings:
        sb.schema(SCHEMA_FUNDAMENTALS).table(T_FILINGS).upsert(
            list(filings.values()), on_conflict="accession_no"
        ).execute()
    existing = select_all_paged(
        lambda: sb.schema(SCHEMA_FUNDAMENTALS).table(T_SHARE_CLASS_SNAPSHOTS)
        .select("cik,share_class_key,as_of_date,accession_no")
        .eq("cik", padded),
        order_by="cik,share_class_key,as_of_date,accession_no",
    )
    new_keys = {
        (padded, str(row["share_class_key"]), str(row["as_of_date"]), str(row["accession_no"]))
        for row in payload
    }
    window_filings = select_all_paged(
        lambda: sb.schema(SCHEMA_FUNDAMENTALS).table(T_FILINGS)
        .select("accession_no,filing_date").eq("cik", padded)
        .gte("filing_date", filed_from),
        order_by="filing_date,accession_no",
    )
    window_accessions = {
        str(row["accession_no"]) for row in window_filings
    } | set(filings)
    stale = [
        row for row in existing
        if str(row.get("accession_no")) in window_accessions
        and (padded, str(row["share_class_key"]), str(row["as_of_date"]), str(row["accession_no"])) not in new_keys
    ]
    deleted = 0
    for row in stale:
        response = (
            sb.schema(SCHEMA_FUNDAMENTALS).table(T_SHARE_CLASS_SNAPSHOTS)
            .delete(count="exact", returning="minimal")
            .eq("cik", padded).eq("share_class_key", row["share_class_key"])
            .eq("as_of_date", row["as_of_date"]).eq("accession_no", row["accession_no"])
            .execute()
        )
        deleted += int(response.count or 0)
    upserted = 0
    for start in range(0, len(payload), 500):
        chunk = payload[start:start + 500]
        sb.schema(SCHEMA_FUNDAMENTALS).table(T_SHARE_CLASS_SNAPSHOTS).upsert(
            chunk, on_conflict="cik,share_class_key,as_of_date,accession_no"
        ).execute()
        upserted += len(chunk)
    counts = {
        "upserted": upserted,
        "deleted": deleted,
    }
    log.info("share_class_snapshots replaced: cik=%s %s", cik, counts)
    return counts


def load_shares_outstanding_by_cik(cik: str | int) -> list[dict[str, Any]]:
    """한 CIK의 클래스별 발행주식수 시점 기록 전체를 반환한다."""
    padded = str(cik).strip().zfill(10)
    rows = select_all_paged(
        lambda: sb.schema(SCHEMA_FUNDAMENTALS).table(T_SHARE_CLASS_SNAPSHOTS)
        .select("*").eq("cik", padded).order("as_of_date"),
        order_by="as_of_date",
    )
    accessions = sorted({str(row["accession_no"]) for row in rows if row.get("accession_no")})
    filings = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_FUNDAMENTALS).table(T_FILINGS)
        .select("accession_no,filing_date,form_type").in_("accession_no", chunk),
        accessions,
        order_by="accession_no",
        paged_reader=select_all_paged,
    ) if accessions else []
    by_accession = {str(row["accession_no"]): row for row in filings}
    return [
        {
            **row,
            "filed_at": by_accession.get(str(row.get("accession_no")), {}).get("filing_date"),
            "form_type": by_accession.get(str(row.get("accession_no")), {}).get("form_type"),
        }
        for row in rows
    ]


def share_class_snapshots_filed_before(
    ticker: str, as_of_at: datetime, *, limit: int = 24
) -> list[dict]:
    """공시일이 cutoff 이전인 발행주식수 snapshot.

    `accepted_at`이 비어 있는 행도 돌려준다 — 그 경우 호출자가 일자 정밀도 정책
    (`valuation_inputs.filing_available_at`)을 적용한다.
    """
    security_id = select_security_ids_by_ticker([ticker]).get(str(ticker).upper())
    if security_id is None:
        return []
    rows = select_all_paged(
        lambda: sb.schema(SCHEMA_FUNDAMENTALS).table(T_SHARE_CLASS_SNAPSHOTS)
        .select("*").eq("mapped_security_id", security_id),
        order_by="as_of_date,accession_no",
    )
    accessions = sorted({str(row["accession_no"]) for row in rows if row.get("accession_no")})
    filings = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_FUNDAMENTALS).table(T_FILINGS)
        .select("accession_no,filing_date,form_type,available_at")
        .in_("accession_no", chunk),
        accessions,
        order_by="accession_no",
        paged_reader=select_all_paged,
    ) if accessions else []
    by_accession = {str(row["accession_no"]): row for row in filings}
    result = []
    for row in rows:
        filing = by_accession.get(str(row.get("accession_no")), {})
        filed_at = filing.get("filing_date")
        if not filed_at or str(filed_at) > as_of_at.date().isoformat():
            continue
        result.append({
            **row,
            "ticker": str(ticker).upper(),
            "filed_at": filed_at,
            "form_type": filing.get("form_type"),
            "available_at": filing.get("available_at"),
        })
    result.sort(key=lambda row: (str(row.get("filed_at") or ""), str(row.get("as_of_date") or "")), reverse=True)
    return result[:limit]
