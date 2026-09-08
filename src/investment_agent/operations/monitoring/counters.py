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

log = get_logger(__name__)


def _fundamentals() -> str:
    from investment_agent.notifications.earnings_report import candidates

    state = candidates.pending_state()
    return f"관심종목 {state['watchlist_count']} · 미발송 공시 {state['pending_filings']}"


def _calendar() -> str:
    from investment_agent.notifications.earnings_calendar import candidates

    state = candidates.pending_state()
    return f"이번 주 발표 예정 {state['upcoming_releases']}"


def _gurus() -> str:
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
