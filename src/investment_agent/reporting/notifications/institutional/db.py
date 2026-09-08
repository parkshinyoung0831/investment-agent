"""institutional 원천과 notifications outbox를 읽고 쓰는 13F 알림 저장소."""
from __future__ import annotations

from investment_agent.platform.db.postgres import sb, select_all_paged
from investment_agent.data.universe.persistence import select_security_profiles
from investment_agent.notifications.outbox import Outbox
from investment_agent.data.institutional.domain import managers as manager_config

SCHEMA_INSTITUTIONAL = "institutional"
SCHEMA_UNIVERSE = "universe"
T_FILINGS = "filings"
T_POSITIONS = "positions"
T_SECURITIES = "securities"
T_IDENTIFIERS = "security_identifiers"
PRODUCER = "institutional"

_ORDER_BY = {
    (SCHEMA_INSTITUTIONAL, T_FILINGS): "filing_date,accession_no",
    (SCHEMA_INSTITUTIONAL, T_POSITIONS): "accession_no,source_row_no",
    (SCHEMA_UNIVERSE, T_SECURITIES): "security_id",
    (SCHEMA_UNIVERSE, T_IDENTIFIERS): "security_id,identifier",
}


def _all(schema: str, table: str, columns: str = "*") -> list[dict]:
    try:
        order_by = _ORDER_BY[(schema, table)]
    except KeyError as exc:
        raise ValueError(f"no stable order configured for {schema}.{table}") from exc
    return select_all_paged(
        lambda: sb.schema(schema).table(table).select(columns).order(order_by),
        order_by=order_by,
    )


def _identifier_map() -> list[dict]:
    securities = _all(SCHEMA_UNIVERSE, T_SECURITIES, "security_id,ticker")
    ticker_by_id = {
        int(row["security_id"]): str(row["ticker"])
        for row in securities
        if row.get("security_id") is not None and row.get("ticker")
    }
    identifiers = _all(
        SCHEMA_UNIVERSE, T_IDENTIFIERS,
        "identifier,identifier_type,security_id",
    )
    return [
        {
            "cusip": str(row["identifier"]),
            "ticker": ticker_by_id.get(int(row["security_id"]))
            if row.get("security_id") is not None else None,
        }
        for row in identifiers
        if row.get("identifier") and row.get("identifier_type") in {"CUSIP", "CINS"}
    ]


def load_analysis_source() -> dict[str, list[dict]]:
    """v1 원천 표를 카드 분석 함수가 소비하는 형태로 조립한다."""
    filings = _all(
        SCHEMA_INSTITUTIONAL, T_FILINGS,
        "accession_no,manager_cik,period_end,form_type,report_type,filing_date,"
        "accepted_at,amendment_type,amendment_no,source_url,confidential_omitted",
    )
    positions = [
        {**row, "cusip": row.get("identifier")}
        for row in _all(
            SCHEMA_INSTITUTIONAL, T_POSITIONS,
            "accession_no,source_row_no,issuer_name,identifier,identifier_type,"
            "value_usd,quantity,quantity_type,position_kind",
        )
    ]
    return {
        "managers": manager_config.all_managers(),
        "filings": filings,
        "positions": positions,
        "cusip_map": _identifier_map(),
        "tickers": select_security_profiles(),
    }


def sent_keys() -> set[str]:
    """이미 outbox에 선점·완료된 institutional 알림 키를 반환한다."""
    return Outbox().sent_keys(PRODUCER)
