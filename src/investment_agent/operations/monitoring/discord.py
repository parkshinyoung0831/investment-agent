"""Discord 채널이 실제로 카드를 받았는지 읽는다.

**여기가 GitHub Actions로는 못 보는 것을 본다.** 잡이 성공해도 카드는 엉뚱한 채널로
갈 수 있고, 그 채널이 지워졌을 수도 있다. 도착 여부는 도착지에서만 확인된다.

두 가지를 읽는다.
- **마지막 활동 시각**: `last_message_id`를 스노플레이크로 풀어 쓴다. 채널 조회 한
  번이면 되고 **포럼에서도 동작한다**(포럼의 last_message_id는 최근 스레드를 가리킨다).
- **창 안의 건수**: `/messages?after=`로 센다. 포럼은 글이 메시지가 아니라 스레드라
  이 방법으로 셀 수 없어 건수를 내지 않는다(생존 판정은 위 시각으로 그대로 된다).

메시지 **내용은 읽지 않는다** — 개수와 시각만 본다. MESSAGE_CONTENT 권한이 필요 없고,
운영 점검이 카드 본문을 들여다볼 이유도 없다.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests

from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

_API = "https://discord.com/api/v10"
_TIMEOUT = 20
# Discord 스노플레이크의 기준 시각(2015-01-01 UTC, 밀리초).
_EPOCH_MS = 1420070400000


def _headers() -> dict[str, str]:
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN not set")
    return {"Authorization": f"Bot {token}"}


def snowflake_time(snowflake: str | int) -> datetime:
    """스노플레이크 ID에 박혀 있는 생성 시각(UTC)."""
    return datetime.fromtimestamp(
        ((int(snowflake) >> 22) + _EPOCH_MS) / 1000, tz=timezone.utc
    )


def time_snowflake(moment: datetime) -> int:
    """시각을 조회 경계로 쓸 수 있는 스노플레이크로. 실제 메시지가 없어도 된다."""
    return (int(moment.timestamp() * 1000) - _EPOCH_MS) << 22


def activity(channel_id: str, since: datetime, *, forum: bool = False) -> dict[str, Any]:
    """채널 하나의 (마지막 활동 시각, 창 안 건수).

    조회가 실패해도 예외를 올리지 않는다 — 채널 하나를 못 읽었다고 일일 점검 전체가
    사라지면, 점검이 없는 것보다 나쁘다(문제가 있는 날 침묵한다).
    """
    # 채널 생성 시각도 ID에 박혀 있다. 어제 만든 채널을 '오래 조용하다'고 경보하면
    # 첫 카드가 올 때까지 며칠을 거짓으로 우는데, 그 며칠이 경보를 못 믿게 만든다.
    out: dict[str, Any] = {
        "last_at": None, "count": None, "error": None,
        "created_at": snowflake_time(channel_id),
    }
    try:
        res = requests.get(f"{_API}/channels/{channel_id}",
                           headers=_headers(), timeout=_TIMEOUT)
        res.raise_for_status()
        last = res.json().get("last_message_id")
        out["last_at"] = snowflake_time(last) if last else None
    except Exception as exc:  # noqa: BLE001 - 점검이 죽는 것보다 한 줄 비는 게 낫다
        out["error"] = str(exc)[:80]
        log.warning("discord channel read failed: ch=%s %s", channel_id, exc)
        return out

    if forum:
        return out                       # 포럼의 글은 메시지가 아니라 스레드다

    try:
        res = requests.get(
            f"{_API}/channels/{channel_id}/messages", headers=_headers(),
            params={"after": time_snowflake(since), "limit": 100}, timeout=_TIMEOUT,
        )
        res.raise_for_status()
        out["count"] = len(res.json())
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)[:80]
        log.warning("discord message count failed: ch=%s %s", channel_id, exc)
    return out


def collect(watched: list[dict[str, Any]], since: datetime) -> list[dict[str, Any]]:
    """감시 대상 선언 + 환경변수 → 채널별 활동 목록.

    ID가 주입되지 않은 채널은 `configured=False`로 남긴다 — 조용히 빼면 시크릿을
    빠뜨린 날 그 채널이 감시 대상에서 사라진 것을 아무도 모른다.
    """
    directory = None
    out = []
    for entry in watched:
        if entry.get("env"):
            channel_id = os.environ.get(entry["env"], "").strip()
        else:
            # 이름으로 찾는 항목. 길드 조회는 한 번만 하고, 실패해도 감시 전체를
            # 멈추지 않는다 — 못 찾은 채널은 configured=False로 남아 눈에 띈다.
            if directory is None:
                directory = _guild_directory()
            found = directory.find(entry["name"]) if directory else None
            channel_id = found.channel_id if found else ""
        row = {**entry, "configured": bool(channel_id)}
        if channel_id:
            row.update(activity(channel_id, since, forum=bool(entry.get("forum"))))
        out.append(row)
    return out


def _guild_directory():
    """길드 채널 디렉터리. 없으면 `None`을 돌려주고 이유를 남긴다."""
    from investment_agent.config import load_config
    from investment_agent.notifications.channels.directory import guild_directory

    try:
        return guild_directory(load_config())
    except Exception as exc:  # noqa: BLE001 - 감시가 감시 때문에 죽지 않게 한다
        log.warning("discord guild directory unavailable", extra={"error": repr(exc)})
        return None
