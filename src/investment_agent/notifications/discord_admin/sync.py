"""매니페스트와 실제 서버를 대조해 할 일을 계산하는 순수 로직.

네트워크를 건드리지 않는다 — 픽스처로 검증할 수 있어야 '무엇을 만들지'를 믿고 적용한다.
"""
from __future__ import annotations

from typing import Any

from investment_agent.notifications.discord_admin import manifest

# 매니페스트가 관리하는 채널 종류. 카테고리는 별도로 다룬다.
_MANAGED = (manifest.TEXT, manifest.VOICE, manifest.FORUM)


def _by_name(existing: list[dict[str, Any]], *kinds: int) -> dict[str, dict[str, Any]]:
    return {str(c.get("name")): c for c in existing if c.get("type") in kinds}


def plan(existing: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """매니페스트 기준으로 (생성할 카테고리, 생성할 채널, 이미 있는 것, 매니페스트에 없는 것)."""
    categories = _by_name(existing, manifest.CATEGORY)
    # 이름은 카테고리를 제외한 모든 종류에서 찾는다 — 음성·포럼도 매니페스트가 관리한다.
    named = _by_name(existing, *_MANAGED)

    create_categories = [
        {"key": cat["key"], "name": cat["name"]}
        for cat in manifest.LAYOUT if cat["name"] not in categories
    ]

    create_channels: list[dict[str, Any]] = []
    matched: list[dict[str, Any]] = []
    for channel in manifest.channels():
        found = named.get(channel["name"])
        if found is None:
            create_channels.append(channel)
        else:
            matched.append({**channel, "id": str(found["id"]),
                            "topic_current": found.get("topic") or "",
                            "parent_current": str(found.get("parent_id") or ""),
                            "tags_current": list(found.get("available_tags") or [])})

    known = {c["name"] for c in manifest.channels()}
    unmanaged = [
        {"name": str(c.get("name")), "id": str(c.get("id")), "type": c.get("type")}
        for c in existing
        if c.get("type") not in (manifest.CATEGORY,) and str(c.get("name")) not in known
    ]
    return {"create_categories": create_categories, "create_channels": create_channels,
            "matched": matched, "unmanaged": unmanaged,
            "tag_updates": tag_updates(matched)}


def tag_updates(matched: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """이미 있는 포럼 중 태그가 매니페스트와 다른 것.

    태그는 이름 집합만 본다 — 순서까지 맞추려 들면 사람이 Discord에서 정렬만 바꿔도
    매번 '바뀜'으로 잡히고, 그때마다 태그를 다시 쓰면 스레드에 붙은 태그가 흔들린다.
    """
    out = []
    for channel in matched:
        wanted = list(channel.get("tags") or [])
        if not wanted:
            continue
        current = [str(tag.get("name")) for tag in channel.get("tags_current") or []]
        if set(current) != set(wanted):
            out.append({"name": channel["name"], "id": channel["id"], "tags": wanted,
                        "tags_current": channel.get("tags_current") or []})
    return out


def env_updates(matched: list[dict[str, Any]]) -> dict[str, str]:
    """.env에 써 넣을 {변수: 채널ID}."""
    return {c["env"]: c["id"] for c in matched if c.get("env")}
