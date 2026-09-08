"""SEC submissions와 archive XML을 직접 사용하는 13F-HR/A 클라이언트."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any

from investment_agent.platform.logging import get_logger
from investment_agent.data.institutional.domain import shadow_diff
from investment_agent.data.institutional.domain.models import FilingRecord, RawPosition
from investment_agent.data.institutional.domain.parser import (
    local_name,
    normalize_positions,
    parse_information_table,
    parse_primary,
    xml_root,
)
from investment_agent.data.institutional.infrastructure.sources import edgartools_13f

log = get_logger(__name__)

_FORMS = {"13F-HR", "13F-HR/A"}

# shadow 대조 결과를 받는 콜백. ETL이 JSON run metrics와 로그로 흘려보낸다.
ShadowSink = Callable[[shadow_diff.ShadowDiff], None]
FilingErrorSink = Callable[[Any, Exception], None]


def _shadow_compare(
    accession_no: str,
    raw_positions: list[RawPosition],
    table_content: bytes | None,
    sink: ShadowSink,
) -> None:
    """edgartools로 같은 information table을 다시 파싱해 운영 결과와 대조한다.

    어떤 실패도 ETL 본류를 막지 않는다(관례 #8): edgartools 부재·파싱 오류는
    모두 잡아 ``ShadowDiff.error``로 기록한다.
    """
    try:
        if table_content is None:
            shadow_rows: list[RawPosition] = []
        else:
            shadow_rows = edgartools_13f.parse_information_table(
                table_content,
                source_format="xml",
            )
        diff = shadow_diff.compare(accession_no, raw_positions, shadow_rows)
    except edgartools_13f.EdgartoolsUnavailable as exc:
        diff = shadow_diff.errored(accession_no, raw_positions, str(exc))
    except Exception as exc:  # noqa: BLE001 - shadow 실패가 적재를 막지 않는다.
        diff = shadow_diff.errored(accession_no, raw_positions, repr(exc))
    try:
        sink(diff)
    except Exception as exc:  # noqa: BLE001 - 싱크 실패도 적재를 막지 않는다.
        log.warning("shadow sink failed accession_no=%s error=%r", accession_no, exc)


def _information_table_xml(
    manager_cik: str,
    filing: Any,
    *,
    sec_client: Any,
) -> bytes | None:
    """archive XML 중 루트가 informationTable인 첨부 파일을 찾는다."""
    primary_name = PurePosixPath(filing.primary_document).name.lower()
    base = sec_client.filing_archive_base(manager_cik, filing.accession_no)
    for item in sec_client.filing_archive_items(manager_cik, filing.accession_no):
        name = str(item.get("name") or "")
        if not name.lower().endswith(".xml") or name.lower() == primary_name:
            continue
        content = sec_client.get_bytes_optional(f"{base}/{name}")
        if content is None:
            continue
        try:
            root = xml_root(content)
        except ValueError:
            continue
        if local_name(root.tag) == "informationTable":
            return content
    return None


def _parse_filing(
    manager_cik: str,
    filing: Any,
    *,
    sec_client: Any,
    shadow_sink: ShadowSink | None = None,
) -> FilingRecord:
    if not filing.primary_document:
        raise ValueError(
            f"13F primary document is missing accession_no={filing.accession_no}"
        )
    primary_content = sec_client.get_bytes_optional(
        sec_client.filing_document_url(
            manager_cik,
            filing.accession_no,
            filing.primary_document,
        )
    )
    if primary_content is None:
        raise ValueError(
            f"13F primary document not found accession_no={filing.accession_no}"
        )
    primary = parse_primary(primary_content, form_type=filing.form_type)
    if primary.period_end.isoformat() != filing.report_date:
        raise ValueError(
            "13F report period mismatch "
            f"accession_no={filing.accession_no} "
            f"submissions={filing.report_date} primary={primary.period_end}"
        )

    table_content = _information_table_xml(manager_cik, filing, sec_client=sec_client)
    if table_content is None:
        if primary.reported_line_count:
            raise ValueError(
                "13F information table not found "
                f"accession_no={filing.accession_no} "
                f"reported={primary.reported_line_count}"
            )
        raw_positions = []
    else:
        raw_positions = parse_information_table(table_content)

    value_scale, positions = normalize_positions(
        raw_positions,
        schema_version=primary.schema_version,
        period_end=primary.period_end,
    )
    if shadow_sink is not None:
        _shadow_compare(
            filing.accession_no,
            raw_positions,
            table_content,
            shadow_sink,
        )
    return FilingRecord(
        accession_no=filing.accession_no,
        manager_cik=sec_client.padded_cik(manager_cik),
        period_end=primary.period_end,
        form_type=filing.form_type,
        report_type=primary.report_type,
        filing_date=date.fromisoformat(filing.filing_date),
        accepted_at=filing.accepted_at,
        amendment_type=primary.amendment_type,
        amendment_no=primary.amendment_no,
        reported_value_usd=primary.reported_value * value_scale,
        reported_line_count=primary.reported_line_count,
        confidential_omitted=primary.confidential_omitted,
        source_url=sec_client.filing_homepage_url(
            manager_cik,
            filing.accession_no,
        ),
        content_sha256=sha256(
            primary_content + b"\x00" + (table_content or b"")
        ).hexdigest(),
        positions=positions,
        parsed_line_count=len(raw_positions),
    )


def iter_filings(
    manager_cik: str,
    since: str,
    *,
    sec_client: Any,
    skip_accessions: set[str] | None = None,
    shadow_sink: ShadowSink | None = None,
    error_sink: FilingErrorSink | None = None,
) -> Iterator[FilingRecord]:
    """한 운용사의 신규 13F-HR/A를 순서대로 반환한다.

    개별 filing 파싱 실패는 error_sink로 격리하고 다음 accession_no을 계속 처리한다.
    submissions 조회 자체가 실패한 경우만 호출자에게 예외를 전파한다.
    """
    filings = sec_client.filings_filed_since(
        manager_cik,
        forms=_FORMS,
        cutoff=date.fromisoformat(since),
    )
    for filing in filings:
        if skip_accessions and filing.accession_no in skip_accessions:
            continue
        try:
            record = _parse_filing(
                manager_cik, filing, sec_client=sec_client, shadow_sink=shadow_sink
            )
        except Exception as exc:  # noqa: BLE001 - 손상 공시 하나가 이후 공시를 막지 않는다.
            log.error(
                "manager_cik=%s accession_no=%s parse failed: %r",
                manager_cik,
                filing.accession_no,
                exc,
            )
            if error_sink is not None:
                try:
                    error_sink(filing, exc)
                except Exception as sink_exc:  # noqa: BLE001 - 오류 기록 실패도 순회를 막지 않는다.
                    log.warning(
                        "filing error sink failed accession_no=%s error=%r",
                        filing.accession_no,
                        sink_exc,
                    )
            continue
        log.info(
            "manager_cik=%s accession_no=%s period=%s filed=%s "
            "amend=%s positions=%d",
            manager_cik,
            record.accession_no,
            record.period_end,
            record.filing_date,
            record.amendment_type,
            len(record.positions),
        )
        yield record
