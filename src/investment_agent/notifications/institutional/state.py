"""거장 13F 알림의 정체성과 원장이 아직 보내지 않은 상태를 계산한다."""
from __future__ import annotations

from investment_agent.notifications.engine import Notice, fact_time, unsettled
from investment_agent.notifications.topics import topic

from . import card, dataset

FILING_TOPIC = topic("guru.filing")
QUARTER_TOPIC = topic("guru.quarter")
ALL_MANAGERS = "all"


def filing_notice(filing: dict, data: object = None) -> Notice:
    """개별 제출의 정체성은 (운용사 CIK, accession_no)다."""
    return Notice(
        subject=str(filing["manager_cik"]),
        occurrence=str(filing["accession_no"]),
        fact_at=fact_time(filing.get("accepted_at") or filing["filing_date"]),
        basis={"period_end": str(filing.get("period_end") or "")},
        data=data,
    )


def quarter_notice(period: str, filings: list[dict], data: object = None) -> Notice:
    """분기 요약은 분기마다 한 장이다. 거장이 더 제출하면 새로 보내지 않고 그 장을 고친다."""
    return Notice(
        subject=ALL_MANAGERS,
        occurrence=period,
        fact_at=max(fact_time(f.get("accepted_at") or f["filing_date"]) for f in filings),
        basis={"filings": sorted(str(f["accession_no"]) for f in filings)},
        data=data,
    )


def pending_state(ledger) -> dict[str, object]:
    """렌더 전 사전 점검. 원장이 아직 보내지 않은 개별·종합 알림 수."""
    data = dataset.load_snapshot()
    period = card._latest_period(data)
    filings = card._latest_filings(data, period)
    pending_filings = unsettled(FILING_TOPIC, [filing_notice(f) for f in filings], ledger=ledger)
    summary_pending = bool(filings) and bool(unsettled(QUARTER_TOPIC, [quarter_notice(period, filings)], ledger=ledger))
    return {
        "period": period,
        "pending_filings": len(pending_filings),
        "summary_pending": summary_pending,
        "should_notify": bool(pending_filings) or summary_pending,
    }


__all__ = ["ALL_MANAGERS", "FILING_TOPIC", "QUARTER_TOPIC", "filing_notice", "pending_state", "quarter_notice"]
