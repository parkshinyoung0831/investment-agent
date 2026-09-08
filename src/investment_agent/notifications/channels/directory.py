"""길드의 채널을 **이름으로** 찾는다. 채널 ID를 환경변수로 늘리지 않기 위해서다.

## 왜 이름으로 찾나

거장 채널은 한 사람당 하나였고, 그 ID가 한 사람당 시크릿 하나였다. 거장을 한 명
추가하려면 채널을 만들고, 시크릿을 넣고, 라우팅 표와 manifest를 고쳐야 했다 — 네
곳 중 하나만 빠뜨려도 카드가 갈 곳을 잃는데 그것은 조용히 일어난다.

채널 이름은 이미 `discord_admin`의 선언이 소유한다(규칙 12). 그 이름으로 봇이
직접 찾으면 ID를 사람이 옮겨 적는 자리가 사라진다.

## 포럼 태그도 여기서 나온다

`GET /guilds/{id}/channels`는 포럼 채널의 `available_tags`까지 한 번에 준다.
태그는 이름이 아니라 snowflake로 지정해야 하므로, 이름→ID 대응이 필요한 곳이
채널과 태그 둘이고 둘 다 이 응답 하나로 해결된다.

## HTTP는 여기 없다

길드 조회도 Discord REST다. 그 호출은 `channels/discord.py` 하나가 소유하고, 이
모듈은 그 응답을 이름 색인으로 접는 일만 한다 — 순수 함수라 네트워크 없이 시험한다.

## 실패는 조용하지 않게

찾지 못하면 `None`을 돌려주고 부르는 쪽이 결정한다. 여기서 예외를 삼키면 "채널이
없다"와 "봇이 그 채널을 못 본다"가 같은 얼굴이 된다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from investment_agent.config import Config
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

FORUM = 15

# 한 프로세스 안에서 길드 구조는 바뀌지 않는다고 본다. 카드 한 장마다 길드 전체를
# 다시 받아오면 발송이 느려지고 rate limit에 먼저 걸린다.
_CACHE: dict[str, "GuildDirectory"] = {}


@dataclass(frozen=True)
class GuildChannel:
    """이름으로 찾은 채널 하나."""

    channel_id: str
    name: str
    kind: int
    #: 포럼 태그 이름 -> 태그 ID. 포럼이 아니면 비어 있다.
    tag_ids: Mapping[str, str] = field(default_factory=dict)

    @property
    def is_forum(self) -> bool:
        return self.kind == FORUM


@dataclass(frozen=True)
class GuildDirectory:
    """이름 -> 채널. 같은 이름이 둘이면 어느 쪽인지 말할 수 없으므로 담지 않는다."""

    channels: Mapping[str, GuildChannel]
    duplicated_names: tuple[str, ...] = ()

    def find(self, name: str) -> GuildChannel | None:
        return self.channels.get(_normalize(name))

    def find_by_id(self, channel_id: str) -> GuildChannel | None:
        """ID로 찾는다. 고정 채널은 목적지를 env의 ID로 받으므로 이 방향도 필요하다 —
        그 채널의 포럼 태그를 이름에서 snowflake로 바꾸려면 채널을 먼저 집어야 한다."""
        wanted = str(channel_id)
        for channel in self.channels.values():
            if channel.channel_id == wanted:
                return channel
        return None

    def tag_ids(self, channel_name: str, tag_names: tuple[str, ...]) -> list[str]:
        """포럼 태그 이름을 ID로 바꾼다. 없는 이름은 조용히 버리지 않고 로그로 남긴다."""
        return self.tags_on(self.find(channel_name), tag_names, label=channel_name)

    def tag_ids_by_channel_id(self, channel_id: str, tag_names: tuple[str, ...]) -> list[str]:
        return self.tags_on(self.find_by_id(channel_id), tag_names, label=str(channel_id))

    def tags_on(self, channel: GuildChannel | None, tag_names: tuple[str, ...],
                *, label: str) -> list[str]:
        channel_name = label
        if channel is None:
            return []
        resolved, missing = [], []
        for tag in tag_names:
            tag_id = channel.tag_ids.get(_normalize(tag))
            (resolved.append(tag_id) if tag_id else missing.append(tag))
        if missing:
            log.warning(
                "discord forum tags are not declared on the channel",
                extra={"channel": channel_name, "missing_tags": missing},
            )
        return resolved


def _normalize(name: str) -> str:
    """Discord는 채널 이름을 소문자로 정규화한다. 비교도 같은 기준으로 한다."""
    return str(name).strip().lower()


def build_directory(rows: list[dict[str, Any]]) -> GuildDirectory:
    """API 응답을 이름 색인으로 접는다. 순수 함수라 네트워크 없이 시험할 수 있다."""
    seen: dict[str, GuildChannel] = {}
    duplicated: set[str] = set()
    for row in rows:
        name = _normalize(row.get("name") or "")
        channel_id = str(row.get("id") or "")
        if not name or not channel_id.isdigit():
            continue
        tags = {
            _normalize(tag.get("name") or ""): str(tag.get("id") or "")
            for tag in (row.get("available_tags") or [])
            if tag.get("name") and str(tag.get("id") or "").isdigit()
        }
        channel = GuildChannel(channel_id=channel_id, name=name, kind=int(row.get("type", 0)), tag_ids=tags)
        if name in seen:
            # 이름이 겹치면 어느 쪽으로 보낼지 고를 수 없다. 하나를 찍어 보내면
            # 절반이 엉뚱한 채널로 가고 그건 로그에도 안 남는다.
            duplicated.add(name)
            continue
        seen[name] = channel
    for name in duplicated:
        seen.pop(name, None)
    if duplicated:
        log.warning(
            "discord guild has channels sharing one name",
            extra={"duplicated_names": sorted(duplicated)},
        )
    return GuildDirectory(channels=seen, duplicated_names=tuple(sorted(duplicated)))


def guild_directory(
    config: Config, *, fetch: Callable[[Config], list[dict[str, Any]]] | None = None,
    refresh: bool = False,
) -> GuildDirectory:
    """길드 채널 디렉터리. 프로세스당 한 번만 받아온다."""
    guild_id, = config.require("DISCORD_GUILD_ID")
    if refresh:
        _CACHE.pop(guild_id, None)
    cached = _CACHE.get(guild_id)
    if cached is None:
        if fetch is None:  # HTTP는 channels/discord.py 하나가 소유한다.
            from investment_agent.notifications.channels.discord import fetch_guild_channels

            fetch = fetch_guild_channels
        cached = build_directory(fetch(config))
        _CACHE[guild_id] = cached
    return cached


def reset_cache() -> None:
    """테스트와 장기 실행 프로세스가 디렉터리를 다시 읽게 한다."""
    _CACHE.clear()


__all__ = [
    "FORUM",
    "GuildChannel",
    "GuildDirectory",
    "build_directory",
    "guild_directory",
    "reset_cache",
]
