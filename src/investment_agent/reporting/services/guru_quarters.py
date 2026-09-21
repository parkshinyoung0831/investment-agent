"""13F 화면이 한 분기를 하나의 포트폴리오로 읽게 정정 공시를 결합한다.

같은 매니저·분기에 정정이 있으면 공시 목록의 "최신"과 "직전"이 같은 분기의 원본·정정이 되고,
정정만 낸 몇 줄이 그 분기 전체 장부로 읽힌다. 어느 신고가 유효한지의 규칙은 데이터 owner(`holdings.select_effective`)
하나를 쓰고, 여기서는 그 결과를 화면 계약(분기당 공시 1건 + 그 분기의 전체 포지션)으로 접는다.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from investment_agent.data.institutional.domain.holdings import (
    AMENDMENT_NEW_HOLDINGS,
    AMENDMENT_RESTATEMENT,
    select_effective,
)
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)


def _order(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("filing_date") or ""),
        str(row.get("accepted_at") or ""),
        str(row.get("accession_no") or ""),
    )


def effective_quarters(
    filings: Sequence[Mapping[str, Any]],
    positions: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """분기마다 유효한 신고를 골라 (공시 1건씩, 그 분기 전체 포지션)으로 접는다.

    공시 행은 그 분기의 마지막 유효 신고이고, 포지션의 `accession_no`는 그 행의 것으로 맞춘다 —
    화면 계산이 "한 공시의 장부"를 전제하기 때문이다. 기준 신고(원본·재작성본)가 없는 분기는
    덧붙임·안내문만 있는 분기는 결합하지 않고 마지막 신고를 그대로 둔다.
    """
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for filing in filings:
        groups.setdefault((str(filing.get("manager_cik")), str(filing.get("period_end"))), []).append(filing)

    event_by_accession: dict[str, str] = {}
    events: list[dict[str, Any]] = []
    for (manager, period), group in groups.items():
        effective = select_effective(
            group,
            order=_order,
            is_base=lambda row: row.get("form_type") == "13F-HR" or row.get("amendment_type") == AMENDMENT_RESTATEMENT,
            is_addition=lambda row: row.get("amendment_type") == AMENDMENT_NEW_HOLDINGS,
        )
        if not effective:
            # 기준 신고가 없는 분기(대개 13F-NT 안내문). 신고를 숨기지 않고 있는 그대로 보이되 결합은 하지 않는다.
            log.warning("13F quarter has no base filing: manager=%s period=%s", manager, period)
            effective = [max(group, key=_order)]
        event = max(effective, key=_order)
        events.append(dict(event))
        for row in effective:
            event_by_accession[str(row["accession_no"])] = str(event["accession_no"])

    combined = [
        {**position, "accession_no": event_by_accession[str(position.get("accession_no"))]}
        for position in positions
        if str(position.get("accession_no")) in event_by_accession
    ]
    return events, combined


__all__ = ["effective_quarters"]
