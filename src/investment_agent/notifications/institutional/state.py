"""거장 알림 발송 상태와 미발송 항목을 계산한다."""
from __future__ import annotations

from . import card, dataset
from investment_agent.reporting.notifications.institutional import db


def filing_key(accession_no: str) -> str:
    return f"filing:{accession_no}"


def quarterly_key(period: str, filed_count: int) -> str:
    return f"quarterly:{period}:{filed_count}"


def pending_state() -> dict[str, object]:
    """최신 분기의 미발송 개별·종합 알림 상태를 반환."""
    data = dataset.load_snapshot()
    period = card._latest_period(data)
    filings = card._latest_filings(data, period)
    sent = db.sent_keys()
    pending_filings = [
        row for row in filings
        if filing_key(str(row["accession_no"])) not in sent
    ]
    summary_key = quarterly_key(period, len(filings))
    return {
        "period": period,
        "pending_filings": len(pending_filings),
        "summary_pending": summary_key not in sent,
        "should_notify": bool(pending_filings) or summary_key not in sent,
    }
