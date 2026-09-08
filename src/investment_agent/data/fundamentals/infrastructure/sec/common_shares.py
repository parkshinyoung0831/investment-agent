"""SEC 보통주 발행주식수 수집 어댑터."""
from __future__ import annotations

from datetime import date
from typing import Any

from investment_agent.data.universe.infrastructure.sources import sec
from investment_agent.platform.logging import get_logger
from investment_agent.data.fundamentals.domain.filing import SUPPORTED_FORMS
from investment_agent.data.fundamentals.domain.services.parse_shares import (
    drop_implausible_share_rows,
    parse_common_shares_from_companyfacts,
    parse_common_shares_from_xbrl_document,
    validate_shares_outstanding,
)

log = get_logger(__name__)


class ShareCollectionError(RuntimeError):
    """A CIK could not be collected completely enough for an atomic replace."""


def storable_share_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """저장 계약이 받는 서식만 남기고, 버린 서식 이름을 함께 돌려준다.

    CompanyFacts의 fact에는 `10-KT`(회계연도 변경 전환기 보고서) 같은 서식도 섞여
    온다. 제출 목록 조회는 서식을 정확히 일치시키지만 이 경로는 그 필터를 거치지
    않는다. 저장 계약이 받지 않는 서식을 그대로 보내면 DB가 `23514`로 거절하고,
    **그 CIK의 발행주식수가 통째로 갱신되지 않는다** — 실측으로 그렇게 실패한
    CIK가 있었다.

    전환기 보고서는 기간이 12개월이 아니라 회계기간 모델에 그대로 담기지 않는다.
    지금은 받지 않는 것이 맞고, 다만 조용히 죽지 않고 세어서 남긴다.
    """
    keep = [row for row in rows if str(row.get("form_type")) in SUPPORTED_FORMS]
    dropped = sorted({
        str(row.get("form_type")) for row in rows
        if str(row.get("form_type")) not in SUPPORTED_FORMS
    })
    return keep, dropped


def fetch_cik_common_shares(
    cik: str | int,
    *,
    cutoff: date,
    active_tickers: list[str] | None = None,
) -> list[dict[str, Any]]:
    """CIK의 모든 10-K/10-Q 공시로부터 보통주 발행주식수 이력을 수집한다."""
    padded = str(cik).strip().zfill(10)
    tickers = list(active_tickers or [])

    # 1. CompanyFacts 시도 (단일 클래스 빠름)
    cf_rows: list[dict[str, Any]] = []
    companyfacts_error: Exception | None = None
    try:
        cf_doc = sec.get_json(f"{sec.DATA_BASE}/api/xbrl/companyfacts/CIK{padded}.json")
        cf_rows = parse_common_shares_from_companyfacts(cf_doc, active_tickers=tickers)
    except Exception as exc:
        companyfacts_error = exc
        log.warning("CIK %s CompanyFacts unavailable: %s", padded, exc)

    # 2. Submissions에서 10-K/10-Q 조회
    filings = sec.filings_filed_since(padded, forms=SUPPORTED_FORMS, cutoff=cutoff)
    if not filings:
        if cf_rows:
            result = [r for r in cf_rows if r["filed_at"] >= cutoff.isoformat()]
            validate_shares_outstanding(result)
            return result
        if companyfacts_error is not None:
            raise ShareCollectionError(
                f"CIK {padded}: CompanyFacts and submissions both unavailable"
            ) from companyfacts_error
        return []

    # CompanyFacts는 XBRL **차원을 버린다.** 그래서 어떤 공시가 CompanyFacts에
    # 있다는 것은 그 공시의 발행주식수 사실에 클래스 차원이 없었다는 뜻이고,
    # 없다는 것은 차원이 있었다(= 클래스별로 나뉘어 있다)는 뜻이다.
    #
    # 그 대비를 그대로 쓰면 문서를 받아야 하는 공시가 저절로 좁혀진다. 전에는
    # 모든 공시의 primary document(1~3MB inline XBRL)를 받아 파싱했다 —
    # 500 CIK × 40건 = 2만 건, 약 33GB, 시간의 71%가 파싱이었다. 그중 92%는
    # CompanyFacts가 이미 같은 값을 갖고 있어 결과가 바뀌지 않는다(실측).
    cf_accessions = {r["accession_no"] for r in cf_rows}
    scan_targets = [f for f in filings if f.accession_no not in cf_accessions]
    if len(scan_targets) < len(filings):
        log.info(
            "CIK %s: 공시 %d건 중 %d건만 문서 스캔 (나머지는 CompanyFacts가 덮는다)",
            padded, len(filings), len(scan_targets),
        )

    direct_rows: list[dict[str, Any]] = []
    failures: list[str] = []

    for filing in scan_targets:
        try:
            url = sec.filing_document_url(padded, filing.accession_no, filing.primary_document)
            content = sec.get_bytes_optional(url)
            if not content:
                failures.append(f"{filing.accession_no}: missing primary document")
                continue
            direct_rows.extend(parse_common_shares_from_xbrl_document(
                content,
                cik=padded,
                accession_no=filing.accession_no,
                form_type=filing.form_type,
                filing_date=filing.filing_date,
                accepted_at=filing.accepted_at,
                active_tickers=tickers,
            ))
        except Exception as exc:
            failures.append(f"{filing.accession_no}: {type(exc).__name__}: {exc}")

    if failures:
        sample = "; ".join(failures[:5])
        raise ShareCollectionError(
            f"CIK {padded}: {len(failures)} filing(s) incomplete: {sample}"
        )

    # CompanyFacts 행은 **차원이 없던 공시의 값**이므로 클래스 유무와 무관하게
    # 그대로 쓸 수 있다. 전에는 이 CIK에 클래스가 하나라도 보이면 CompanyFacts를
    # 통째로 버리고 "문서로만 읽은 공시가 있다"며 CIK 전체를 실패시켰는데, 그러면
    # 클래스를 나중에 만든 기업의 과거 기간이 통째로 사라진다.
    base_rows = [row for row in cf_rows if row["filed_at"] >= cutoff.isoformat()]
    filing_by_accession = {filing.accession_no: filing for filing in filings}
    for row in base_rows:
        filing = filing_by_accession.get(str(row["accession_no"]))
        if filing is not None:
            row["accepted_at"] = filing.accepted_at

    out_by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in [*base_rows, *direct_rows]:
        key = (
            str(row["cik"]),
            str(row["share_class_key"]),
            str(row["as_of_date"]),
            str(row["accession_no"]),
        )
        out_by_key[key] = row

    storable, dropped_forms = storable_share_rows(list(out_by_key.values()))
    if dropped_forms:
        log.info("CIK %s: 저장 계약 밖 서식 제외 (%s)", padded, ", ".join(dropped_forms))

    # 자리표시자(`1`·`100`)와 자릿수 오류(×1,000·×1,000,000)는 SEC 원본에 섞여 온다.
    # 그 행만 버리고 나머지 기간은 남긴다 — 전에는 하나라도 있으면 그 CIK 전체를
    # 거절해서 17개사의 발행주식수가 통째로 비었다.
    kept, dropped = drop_implausible_share_rows(storable)
    if dropped:
        log.warning(
            "CIK %s: 원본 이상값 %d행 제외 (%s)", padded, len(dropped),
            ", ".join(sorted({str(int(r["shares_outstanding"])) for r in dropped})[:5]),
        )

    result = sorted(
        kept,
        key=lambda r: (r["as_of_date"], r["filed_at"], r["share_class_key"]),
    )
    validate_shares_outstanding(result)
    return result
