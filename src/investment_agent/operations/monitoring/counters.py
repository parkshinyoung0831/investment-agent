"""각 알림이 '지금 보낼 게 있다고 보는지'를 그대로 읽어 온다.

**게이트가 정상적으로 0건을 낼 때가 제일 위험하다.** 2026-08-18에 관심종목 48개의
알림 시작일이 당일로 박혀 직전 분기 공시 33건이 통째로 걸러졌는데, 워크플로는 초록이고
채널도 '사건형이라 조용한 것'으로 보여 어디에도 걸리지 않았다. 카드가 `관심종목 50 ·
미발송 공시 0`이라고 말했다면 사람이 이상하다고 느꼈을 것이다.

**여기서 쿼리를 만들지 않는다.** 각 알림 패키지가 이미 렌더 의존성 없이 돌도록 만들어
둔 preflight(`pending_state`)를 그대로 호출한다. ops가 자기 쿼리를 갖는 순간 스키마가
바뀔 때 여기만 남아 거짓말을 하게 된다.

Supabase 자격증명이 없거나 조회가 실패하면 **그 줄만 비운다** — 카운터 때문에 일일
점검 전체가 사라지면 점검이 없는 것보다 나쁘다.
"""
from __future__ import annotations

from typing import Any, Callable

from investment_agent.platform.logging import get_logger
from investment_agent.platform.storage_paths import runtime_database_path

log = get_logger(__name__)


def _runtime_ledger_available() -> bool:
    """현재 실행기가 발송 원장을 읽을 수 있는지 확인한다.

    GitHub-hosted 하트비트에는 실행 컴퓨터의 SQLite가 없다. 이때 ``mode=ro``로
    억지로 열면 정상 점검이 경고를 남기며 모든 카운터를 버린다. 발송 워크플로는
    runtime-ledger action이 원장을 복원하므로, 파일 존재 여부가 이 구분의 명시적
    경계다.
    """
    return runtime_database_path().is_file()


def _fundamentals_canonical() -> str:
    """원장 없이도 Supabase가 소유한 관심종목 수는 표시한다."""
    from investment_agent.reporting.notifications import earnings_report as db

    return f"관심종목 {len(db.watchlist_members())}"


def _calendar_canonical() -> str:
    """원장 없이도 현재 주의 원천 일정 수는 표시한다."""
    from investment_agent.notifications.earnings_calendar import candidates

    rows, _, _ = candidates.collect(candidates._default_store())
    return f"이번 주 발표 예정 {len(rows)}"


def _gurus_canonical() -> str:
    """원장 없이도 최신 13F 제출 현황은 표시한다."""
    from investment_agent.notifications.institutional import card, dataset

    data = dataset.load_snapshot()
    period = card._latest_period(data)
    return f"최신 13F {len(card._latest_filings(data, period))}건({period})"


def _fundamentals() -> str:
    if not _runtime_ledger_available():
        return _fundamentals_canonical()
    from investment_agent.notifications.earnings_report import candidates

    state = candidates.pending_state()
    return f"관심종목 {state['watchlist_count']} · 미발송 공시 {state['pending_filings']}"


def _calendar() -> str:
    if not _runtime_ledger_available():
        return _calendar_canonical()
    from investment_agent.notifications.earnings_calendar import candidates

    state = candidates.pending_state()
    return f"이번 주 발표 예정 {state['upcoming_releases']}"


def _gurus() -> str:
    if not _runtime_ledger_available():
        return _gurus_canonical()
    from investment_agent.notifications.institutional import state as gurus_state

    state = gurus_state.pending_state()
    return f"13F 미발송 {state['pending_filings']}({state['period']})"


_SOURCES: list[tuple[str, Callable[[], str]]] = [
    ("fundamentals", _fundamentals),
    ("calendar", _calendar),
    ("gurus", _gurus),
]


def collect() -> list[str]:
    """카드에 실을 한 줄짜리 카운터들. 실패한 것은 조용히 빠진다."""
    out: list[str] = []
    for name, source in _SOURCES:
        try:
            out.append(source())
        except Exception as exc:  # noqa: BLE001 - 카운터가 점검을 죽이면 안 된다
            log.warning("counters: %s 조회 실패 — 건너뛴다 (%s)", name, exc)
    return out


def summary(values: list[str] | None = None) -> str:
    """카드 한 줄. 아무것도 못 읽었으면 빈 문자열."""
    values = collect() if values is None else values
    return " · ".join(values)


def ping(url: str) -> bool:
    """외부 dead-man's switch에 '살아 있음'을 알린다.

    하트비트 자체가 죽으면 이 저장소 안의 무엇도 그걸 알릴 수 없다 — GitHub Actions가
    멈추면 감시자도 같이 멈춘다. 바깥에서 '핑이 끊겼다'를 봐 주는 곳이 있어야 한다.
    URL이 없으면 아무 일도 하지 않는다.
    """
    if not url:
        return False
    import requests

    try:
        requests.get(url, timeout=10).raise_for_status()
        log.info("heartbeat ping sent")
        return True
    except Exception as exc:  # noqa: BLE001 - 핑 실패가 점검 결과를 가리면 안 된다
        log.warning("heartbeat ping failed: %s", exc)
        return False


def as_dict() -> dict[str, Any]:
    """로깅용."""
    return {"counters": collect()}
