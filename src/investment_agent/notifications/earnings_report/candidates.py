"""어떤 공시를 카드로 보낼지 고르고, 카드가 필요한 자료를 한 덩어리로 묶는다.

필터는 세 겹이다: 관심종목 적용일(watch_from) 이후 · 운영 lookback(기본 7일) 이내 ·
notifications.outbox에 없는 (ticker, accession_no).

reporting/notifications/earnings_report.py의 조회 결과만 받아 쓰고 Supabase를 직접 건드리지 않는다.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

from investment_agent.platform.logging import get_logger
from investment_agent.reporting.notifications import earnings_report as db

log = get_logger(__name__)

# 첫 실행이 10년치 과거 공시를 한꺼번에 쏟아내지 않도록 하는 최근성 가드(일).
_DEFAULT_LOOKBACK_DAYS = 7
_WAIT_FOR_SEGMENT_STATES = ("processing", "failed")
# 세그먼트를 기다리는 기한(일). 기한이 없으면 "늦게 보낸다"가 아니라 "영영 안
# 보낸다"가 된다 — 세그먼트는 SEC의 분기 데이터셋에서 오고 그것은 한 분기 늦게
# 공개되므로, 갓 접수된 공시는 몇 달 동안 status=processing에 머문다.
_DEFAULT_SEGMENT_WAIT_DAYS = 3


def _lookback_days() -> int:
    try:
        return int(os.environ.get("FUNDAMENTALS_NOTIFY_LOOKBACK_DAYS", _DEFAULT_LOOKBACK_DAYS))
    except ValueError:
        return _DEFAULT_LOOKBACK_DAYS


def _segment_wait_days() -> int:
    try:
        return int(os.environ.get("FUNDAMENTALS_SEGMENT_WAIT_DAYS", _DEFAULT_SEGMENT_WAIT_DAYS))
    except ValueError:
        return _DEFAULT_SEGMENT_WAIT_DAYS


def _cutoff() -> str:
    return (date.today() - timedelta(days=_lookback_days())).isoformat()


def row_accession_no(row: dict) -> str:
    """wide 행의 대표 accession_no. 원본 근거는 Storage에 보관하므로 DB JSON을 읽지 않는다.

    `financial_versions.accession_no`는 NOT NULL이라 빈 값이 올 수 없다.
    """
    return str(row["accession_no"]).strip()


def group_by_filing(
    rows: list[dict],
    processed: set[tuple[str, str]],
    members: list[dict],
    global_cutoff: str,
) -> dict[tuple[str, str], list[dict]]:
    """관심종목 등록일과 운영 lookback을 만족하는 미발송 accession_no을 묶는다."""
    member_cutoffs = {
        str(member["ticker"]): max(global_cutoff, str(member.get("watch_from") or global_cutoff))
        for member in members
    }
    filings: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "")
        filed = str(row.get("filed_at") or "")
        accession_no = row_accession_no(row)
        cutoff = member_cutoffs.get(ticker)
        if not cutoff or not filed or filed < cutoff:
            continue
        if (ticker, accession_no) in processed:
            continue
        filings.setdefault((ticker, accession_no), []).append(row)
    return filings


def pick_headline(rows: list[dict]) -> dict:
    """같은 공시(같은 accession_no)의 여러 행 중 대표 1행: 기간말 최신, 동률이면 FY 우선."""
    return max(rows, key=lambda r: (str(r.get("period_end") or ""), r["fiscal_period"] == "FY"))


def _quarter_history(rows: list[dict], ticker: str, period_end: str) -> list[dict]:
    """티커의 분기 이력(period_end 오름차순)에서 헤드라인 기간까지 최근 N분기."""
    hist = [
        r for r in rows
        if r["ticker"] == ticker
        and r["fiscal_period"] in db.QUARTERS
        and str(r.get("period_end") or "") <= period_end
    ]
    hist.sort(key=lambda r: str(r.get("period_end") or ""))
    return hist[-db.TREND_QUARTERS:]


def _selected_members(tickers: set[str] | None = None) -> list[dict]:
    """활성 관심종목 중 지정된 종목만 남긴다."""
    members = db.watchlist_members()
    if tickers is None:
        return members
    return [member for member in members if str(member.get("ticker") or "") in tickers]


def is_report_ready(
    segment_state: dict | None,
    *,
    filed_at: str = "",
    today: date | None = None,
) -> bool:
    """정밀 카드를 지금 보낼지 판정한다.

    세그먼트가 아직이면 잠깐 기다린다 — 축이 붙은 카드가 더 낫고, 한 번 보내면
    같은 공시로 다시 보낼 기회가 없기 때문이다. **다만 기다림에는 기한이 있다.**
    세그먼트는 SEC의 분기 데이터셋에서 오고 그것은 한 분기 늦게 공개되므로, 기한이
    없으면 갓 접수된 공시일수록 오래 묶여 결국 아무것도 못 받는다.

    기한이 지나면 세그먼트 없이 내보낸다. 세그먼트는 본 카드가 아니라 같은
    메시지에 얹는 별도 embed라, 없으면 그 자리만 비고 재무 카드는 온전하다.
    """
    status = str((segment_state or {}).get("status") or "processing")
    if status not in _WAIT_FOR_SEGMENT_STATES:
        return True
    if not filed_at:
        return False
    deadline = (today or date.today()) - timedelta(days=_segment_wait_days())
    return str(filed_at)[:10] <= deadline.isoformat()


def pending_state(tickers: set[str] | None = None) -> dict[str, int | bool]:
    """렌더 의존성 설치 전에 사용할 가벼운 알림 대기 상태를 반환한다."""
    members = _selected_members(tickers)
    tickers = [str(member["ticker"]) for member in members]
    if not tickers:
        return {"watchlist_count": 0, "pending_filings": 0, "should_notify": False}

    rows = db.load_pending_keys(tickers)
    filings = group_by_filing(rows, db.processed_keys(), members, _cutoff())
    return {
        "watchlist_count": len(members),
        "pending_filings": len(filings),
        "should_notify": bool(filings),
    }


def load_pending(tickers: set[str] | None = None) -> list[dict]:
    """관심종목의 미발송 신규 공시 목록.

    각 항목: {
      "row":            헤드라인 financial_versions 행(_has_anomaly·accession_no 부착),
      "prev":           전년 동기 행 or None (YoY·비교 막대용),
      "history":        최근 분기 이력(매출·EPS·현금흐름 추세 차트용),
      "sector_*":       업종 특화 지표의 같은 네 가지,
      "health":         재무건전성 게이지 최신값 or None,
      "valuation":      밸류에이션 스트립 최신값 or None,
      "names":          표시용 회사명·업종,
      "segment_state":  {status, axes} — segment_state.build() 결과,
    }
    """
    members = _selected_members(tickers)
    tickers = [str(member["ticker"]) for member in members]
    if not tickers:
        log.info("fundamentals: Supabase 활성 관심종목 없음 — 조회 생략")
        return []
    rows = db.load_headline_rows(tickers)
    if not rows:
        return []

    # 공시(ticker, accession_no) 단위로 묶고, 등록일 이후 미발송·최근 건만 남긴다.
    filings = group_by_filing(rows, db.processed_keys(), members, _cutoff())
    if not filings:
        return []

    # 차트 보강 데이터는 발송 대상이 있을 때만 조회.
    by_key = {(r["ticker"], r["fiscal_year"], r["fiscal_period"]): r for r in rows}
    anomalies = db.anomaly_keys(tickers)
    health = db.load_health(tickers)
    valuation = db.load_valuation(tickers)
    names = db.load_names(tickers)
    sector_rows = db.load_sector_rows(tickers)
    sector_by_key = {
        (r["ticker"], r["fiscal_year"], r["fiscal_period"]): r for r in sector_rows
    }

    # 축(사업·제품·지역) 카드의 근거. 대상 공시가 정해진 뒤에만 조회한다.
    headlines = [pick_headline(cand) for cand in filings.values()]
    for row in headlines:
        row["accession_no"] = row_accession_no(row)
    segment_targets = {
        (str(r["ticker"]), str(r["accession_no"]), int(r["fiscal_year"]), str(r["fiscal_period"]))
        for r in headlines
    }
    segment_states = db.load_segment_highlights(segment_targets)

    out: list[dict] = []
    for row in headlines:
        ticker = row["ticker"]
        period_end = str(row.get("period_end") or "")
        row["_has_anomaly"] = (ticker, row["fiscal_year"], row["fiscal_period"]) in anomalies
        segment_key = (
            ticker, str(row["accession_no"]), int(row["fiscal_year"]), str(row["fiscal_period"]),
        )
        segment_state = segment_states.get(segment_key, {"status": "empty", "axes": []})
        filed_at = str(row.get("filed_at") or "")
        if not is_report_ready(segment_state, filed_at=filed_at):
            # 세그먼트는 별도 workflow_run에서 늦게 끝날 수 있다. 여기서 선점하면 축 없는
            # 카드가 확정돼 재발송 기회를 잃으므로, 다음 알림 주기에 다시 판단한다.
            log.info(
                "fundamentals: 세그먼트 적재 대기 ticker=%s accession_no=%s status=%s "
                "filed_at=%s wait_days=%d",
                ticker, row["accession_no"], segment_state.get("status"),
                filed_at or "-", _segment_wait_days(),
            )
            continue
        if segment_state.get("status") in _WAIT_FOR_SEGMENT_STATES:
            log.info(
                "fundamentals: 세그먼트 대기 기한 초과 — 재무 카드만 보낸다 "
                "ticker=%s accession_no=%s filed_at=%s",
                ticker, row["accession_no"], filed_at or "-",
            )
        out.append({
            "row": row,
            "prev": by_key.get((ticker, row["fiscal_year"] - 1, row["fiscal_period"])),
            "history": _quarter_history(rows, ticker, period_end),
            "sector_row": sector_by_key.get((ticker, row["fiscal_year"], row["fiscal_period"])),
            "sector_prev": sector_by_key.get((ticker, row["fiscal_year"] - 1, row["fiscal_period"])),
            "sector_history": _quarter_history(sector_rows, ticker, period_end),
            "health": health.get(ticker),
            "valuation": valuation.get(ticker),
            "names": names.get(ticker),
            "segment_state": segment_state,
        })

    out.sort(key=lambda x: (str(x["row"].get("filed_at")), x["row"]["ticker"]))
    return out
