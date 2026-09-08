"""지금 이 시각에 발표가 예정된 관심종목만 골라 낸다.

관심종목 50개를 매번 다 훑으면 SEC 호출이 낭비되고, 하루 한 번만 훑으면 장전
발표가 최대 15시간 늦게 잡힌다. 발표 예정 세션(BMO/AMC)을 알고 있으면 그 창
안에서 해당 종목만 좁게 훑을 수 있다.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from investment_agent.data.fundamentals.domain.services.classify_report_session import (
    ET,
    UNKNOWN,
    classify_session,
    is_placeholder_time,
    is_within_collect_window,
)

# 예정일이 하루쯤 어긋나는 일은 흔하다. 전후 하루를 같이 본다.
_DATE_SLACK_DAYS = 1
_EXACT_LEAD = timedelta(minutes=10)
_EXACT_LAG = timedelta(minutes=45)
_ESTIMATED_LEAD = timedelta(minutes=90)
_ESTIMATED_LAG = timedelta(minutes=120)
_MIDNIGHT = time(0, 0)
_DATE_ONLY_POLL_MINUTES = 5


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _as_datetime(value: object) -> datetime | None:
    """DB·테스트 입력의 ISO 시각을 timezone-aware datetime으로 정규화한다."""
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _is_date_only_anchor(moment: datetime | None, session: str) -> bool:
    """날짜만 받은 값을 저장용 ET 자정으로 앵커한 경우를 판별한다."""
    if moment is None:
        return True
    et = moment.astimezone(ET) if moment.tzinfo else moment.replace(tzinfo=ET)
    return session == UNKNOWN and et.timetz().replace(tzinfo=None) == _MIDNIGHT


def latest_schedule_by_ticker(rows: list[dict]) -> dict[str, dict]:
    """종목별로 가장 최근 관측 스냅샷만 남긴다.

    예정일은 자주 바뀌고 표는 관측일마다 행을 쌓으므로, 오래된 관측을 그대로
    쓰면 이미 바뀐 날짜로 수집을 건다.
    """
    latest: dict[str, dict] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "")
        if not ticker:
            continue
        snapshot = _as_date(row.get("snapshot_date"))
        current = latest.get(ticker)
        if current is None or (snapshot and snapshot > _as_date(current.get("snapshot_date"))):
            latest[ticker] = row
    return latest


def select_session_targets(
    rows: list[dict],
    now: datetime,
    *,
    include_unknown: bool = True,
) -> dict:
    """지금 수집 창이 열려 있는 종목과 그 세션을 돌려준다.

    `include_unknown`이 참이면 세션을 모르는 종목(예정 시각 미공개)도 넓은 창
    안에서 포함한다. 시간 메타데이터가 없다는 이유로 발표를 놓치는 쪽이,
    몇 번 더 훑는 쪽보다 나쁘다 — fast path 게이트와 같은 fail-open 원칙이다.
    """
    et_now = now.astimezone(ET) if now.tzinfo else now.replace(tzinfo=ET)
    today = et_now.date()
    window = {today - timedelta(days=_DATE_SLACK_DAYS), today, today + timedelta(days=_DATE_SLACK_DAYS)}

    targets: dict[str, str] = {}
    for ticker, row in latest_schedule_by_ticker(rows).items():
        expected_day = _as_date(row.get("expected_report_date"))
        if expected_day is None or expected_day not in window:
            continue
        session = str(row.get("expected_session") or UNKNOWN)
        if session == UNKNOWN and not include_unknown:
            continue
        if not is_within_collect_window(session, et_now):
            continue
        targets[ticker] = session

    by_session: dict[str, list[str]] = {}
    for ticker, session in sorted(targets.items()):
        by_session.setdefault(session, []).append(ticker)

    return {
        "as_of": et_now.isoformat(),
        "tickers": sorted(targets),
        "by_session": by_session,
    }


def select_timed_targets(rows: list[dict], now: datetime) -> dict:
    """발표 예정 시각의 신뢰도에 맞춰 지금 SEC를 조회할 종목만 고른다.

    정확 시각은 발표 직전부터 짧게, Yahoo 추정·자리표시는 넓게, 날짜만 아는
    일정은 기존 세션 안전망으로 처리한다. ``expected_report_at``을 무조건
    정확한 사실로 취급하면 ET 자정 앵커와 15:00 자리표시 때문에 오히려 공시를
    놓치므로 신뢰도별 창을 분리한다.
    """
    et_now = now.astimezone(ET) if now.tzinfo else now.replace(tzinfo=ET)
    today = et_now.date()
    date_window = {
        today - timedelta(days=_DATE_SLACK_DAYS),
        today,
        today + timedelta(days=_DATE_SLACK_DAYS),
    }
    targets: dict[str, str] = {}
    by_confidence: dict[str, list[str]] = {}

    for ticker, row in latest_schedule_by_ticker(rows).items():
        expected_day = _as_date(row.get("expected_report_date"))
        if expected_day is None or expected_day not in date_window:
            continue
        session = str(row.get("expected_session") or UNKNOWN)
        expected_at = _as_datetime(row.get("expected_report_at"))
        expected_et = (
            expected_at.astimezone(ET)
            if expected_at is not None and expected_at.tzinfo
            else expected_at.replace(tzinfo=ET) if expected_at is not None else None
        )

        if _is_date_only_anchor(expected_et, session):
            confidence = "date_only"
            # 정확 시각을 모르는 종목은 하루 창을 열어 두되, 매분 SEC를 호출하지
            # 않는다. 정밀 시각 대상의 1분 SLA와 날짜-only 안전망의 비용을 분리한다.
            eligible = (
                is_within_collect_window(UNKNOWN, et_now)
                and et_now.minute % _DATE_ONLY_POLL_MINUTES == 0
            )
        elif bool(row.get("is_estimated")) or is_placeholder_time(expected_et):
            confidence = "estimated"
            eligible = (
                expected_et is not None
                and expected_et - _ESTIMATED_LEAD <= et_now <= expected_et + _ESTIMATED_LAG
            )
        else:
            confidence = "exact"
            eligible = (
                expected_et is not None
                and expected_et - _EXACT_LEAD <= et_now <= expected_et + _EXACT_LAG
            )
        if not eligible:
            continue
        targets[ticker] = session
        by_confidence.setdefault(confidence, []).append(ticker)

    for tickers in by_confidence.values():
        tickers.sort()
    return {
        "as_of": et_now.isoformat(),
        "tickers": sorted(targets),
        "by_session": {
            session: sorted(ticker for ticker, value in targets.items() if value == session)
            for session in sorted(set(targets.values()))
        },
        "by_confidence": dict(sorted(by_confidence.items())),
    }


def session_now(now: datetime) -> str:
    """지금이 ET 기준 어느 세션 구간인지 — 로그와 워크플로 표시에 쓴다."""
    return classify_session(now)
