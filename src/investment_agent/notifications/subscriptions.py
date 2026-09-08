"""알림 채널 라우팅: notification kind → Discord 채널 ID.

과거에는 이 매핑을 ``notifications.subscriptions`` 테이블에 그대로 복제해
저장했다. 실제로는 채널당 값 하나(``security_id`` 전부 NULL, ``is_enabled``
전부 true, ``active_from`` 전부 오늘)만 쓰였으므로 DB 왕복 없이 환경변수를
그대로 읽는다. 종목별 구독이나 채널 비활성화가 실제로 필요해지면 그때
저장소를 다시 설계한다.
"""
from __future__ import annotations

from investment_agent.config import Config, load_config

# 운영 채널의 env 선언은 discord_admin manifest와 맞춘다.
KIND_ENV: dict[str, str] = {
    "macro_core": "DISCORD_CHANNEL_MACRO_DAILY",
    "macro_watch": "DISCORD_CHANNEL_MACRO_ALERT",
    "econ_calendar_release": "DISCORD_CHANNEL_ECON_CALENDAR_RELEASE",
    "fundamentals_calendar": "DISCORD_CHANNEL_EARNINGS_CALENDAR",
    # 주간 요약(위)과 별개로, 종목별 다음 발표 예정은 그 종목의 실적 스레드에
    # 쌓인다 — 예정·속보·정밀 분석이 한 줄기로 읽힌다.
    "fundamentals_schedule": "DISCORD_CHANNEL_EARNINGS",
    "fundamentals_flash": "DISCORD_CHANNEL_EARNINGS",
    "fundamentals_earnings": "DISCORD_CHANNEL_EARNINGS",
    "institutional": "DISCORD_CHANNEL_GURUS",
    # 거장 공시는 포럼 하나에 사람마다 스레드 하나로 쌓인다. 분기 비교 요약(위)과
    # 읽는 방향이 다르다 — 하나는 "이번 분기에 다들 뭘 했나", 하나는 "이 사람의 흐름".
    "gurus_forum": "DISCORD_CHANNEL_GURU_FORUM",
    "strategy_summary": "DISCORD_CHANNEL_STRATEGY_MONTHLY",
    "strategy": "DISCORD_CHANNEL_STRATEGY_FORUM",
    "investment_portfolio": "DISCORD_CHANNEL_AI_REPORTS",
    "investment_candidates": "DISCORD_CHANNEL_AI_REPORTS",
    "investment_trades": "DISCORD_CHANNEL_AI_TRADES",
}


class SubscriptionConfigurationError(RuntimeError):
    """알림 종류에 대해 전송 가능한 Discord 채널이 구성되지 않았다."""


def discord_targets(kind: str, *, config: Config | None = None) -> tuple[str, ...]:
    """``kind``에 적용되는 Discord target을 환경변수에서 읽는다.

    채널이 구성되지 않으면 조용히 건너뛰지 않고 실패한다.
    """
    try:
        env_name = KIND_ENV[kind]
    except KeyError as exc:
        raise SubscriptionConfigurationError(f"unknown notification kind {kind!r}") from exc
    try:
        target, = (config or load_config()).require(env_name)
    except Exception as exc:
        raise SubscriptionConfigurationError(
            f"no active Discord subscription for notification kind {kind!r}"
        ) from exc
    return (target,)


__all__ = ["KIND_ENV", "SubscriptionConfigurationError", "discord_targets"]
