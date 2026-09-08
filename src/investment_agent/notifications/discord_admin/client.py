"""Discord REST 호출 — 길드 조회/설정, 채널 조회·생성·수정, 역할·채널 권한, 웹훅 생성.

관리자 토큰(`DISCORD_ADMIN_TOKEN`)을 쓴다. 카드를 보내는 봇 토큰과 분리돼 있다 —
카드 발송에는 '메시지 보내기·파일 첨부'만 있으면 되고 채널 생성 권한은 필요 없다.

**삭제는 구현하지 않는다.** 되돌릴 수 없는 조작이라 사람이 Discord UI에서 직접 하는 게
맞다. sync는 만들거나(create) 보고할(report) 뿐이다.
"""
from __future__ import annotations

import os
from typing import Any

import requests

from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

_API = "https://discord.com/api/v10"
_TIMEOUT = 20


def _token() -> str:
    token = os.environ.get("DISCORD_ADMIN_TOKEN", "").strip()
    if not token:
        raise RuntimeError("DISCORD_ADMIN_TOKEN not set")
    return token


def guild_id() -> str:
    gid = os.environ.get("DISCORD_GUILD_ID", "").strip()
    if not gid:
        raise RuntimeError("DISCORD_GUILD_ID not set")
    return gid


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bot {_token()}", "Content-Type": "application/json"}





def fetch_guild() -> dict[str, Any]:
    """길드 메타(이름·features). 포럼을 만들 수 있는지는 features의 COMMUNITY가 정한다."""
    res = requests.get(f"{_API}/guilds/{guild_id()}", headers=_headers(), timeout=_TIMEOUT)
    res.raise_for_status()
    return res.json()


def enable_community(*, rules_channel_id: str, updates_channel_id: str) -> dict[str, Any]:
    """길드를 Community로 바꾼다 — 포럼·온보딩은 이 플래그가 없으면 아예 못 만든다.

    Discord가 함께 요구하는 값을 같은 요청에 넣는다: 규칙 채널, 모더레이터 전용 채널,
    인증 수준 LOW 이상, 콘텐츠 필터 전원, 기본 알림 '멘션만'. 하나라도 빠지면 400이다.
    되돌리기는 서버 설정에서 사람이 한다.
    """
    payload = {
        "features": ["COMMUNITY"],
        "rules_channel_id": rules_channel_id,
        "public_updates_channel_id": updates_channel_id,
        "verification_level": 1,            # LOW — Community 최소 요구
        "explicit_content_filter": 2,       # ALL_MEMBERS
        "default_message_notifications": 1, # ONLY_MENTIONS — 카드가 매일 오는 서버라 이 편이 맞다
    }
    res = requests.patch(f"{_API}/guilds/{guild_id()}", headers=_headers(),
                         json=payload, timeout=_TIMEOUT)
    res.raise_for_status()
    log.info("discord guild switched to community")
    return res.json()


def fetch_channels() -> list[dict[str, Any]]:
    """길드의 모든 채널(카테고리 포함)."""
    res = requests.get(f"{_API}/guilds/{guild_id()}/channels",
                       headers=_headers(), timeout=_TIMEOUT)
    res.raise_for_status()
    return res.json()


def create_channel(name: str, *, kind: int, parent_id: str | None = None,
                   topic: str | None = None, position: int | None = None,
                   tags: list[str] | None = None) -> dict[str, Any]:
    """채널 하나 생성. 이미 같은 이름이 있어도 Discord는 막지 않으므로 호출부가 걸러야 한다.

    tags는 포럼 전용이다. 태그 ID는 Discord가 만들어 주므로 발송 코드는 이름으로 찾는다.
    """
    payload: dict[str, Any] = {"name": name, "type": kind}
    if parent_id:
        payload["parent_id"] = parent_id
    if topic:
        payload["topic"] = topic
    if position is not None:
        payload["position"] = position
    if tags:
        payload["available_tags"] = [{"name": tag, "moderated": False} for tag in tags]
    res = requests.post(f"{_API}/guilds/{guild_id()}/channels",
                        headers=_headers(), json=payload, timeout=_TIMEOUT)
    res.raise_for_status()
    created = res.json()
    log.info("discord channel created: #%s (id=%s)", created.get("name"), created.get("id"))
    return created


def edit_channel(channel_id: str, **fields: Any) -> dict[str, Any]:
    """이름·주제 등 수정."""
    res = requests.patch(f"{_API}/channels/{channel_id}",
                         headers=_headers(), json=fields, timeout=_TIMEOUT)
    res.raise_for_status()
    log.info("discord channel updated: id=%s %s", channel_id, sorted(fields))
    return res.json()


def delete_channel(channel_id: str) -> None:
    """채널 하나를 지운다. **메시지와 스레드가 함께 사라지고 되돌릴 수 없다.**

    구조를 처음부터 다시 세울 때만 쓴다. 부르는 쪽이 사람에게 확인을 받는다 —
    이 함수는 확인하지 않는다.
    """
    res = requests.delete(f"{_API}/channels/{channel_id}", headers=_headers(), timeout=_TIMEOUT)
    res.raise_for_status()
    log.warning("discord channel deleted: id=%s", channel_id)


def set_forum_tags(channel_id: str, tags: list[str],
                   existing: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """포럼 태그를 매니페스트에 맞춘다.

    이미 있는 태그는 **ID를 그대로 실어 보낸다** — 이름만 보내면 Discord가 새 태그로 보고
    다시 만들고, 그 순간 이전 스레드에 붙어 있던 태그가 떨어진다.
    """
    by_name = {str(tag.get("name")): tag for tag in (existing or [])}
    payload = [
        {"id": by_name[tag]["id"], "name": tag, "moderated": False} if tag in by_name
        else {"name": tag, "moderated": False}
        for tag in tags
    ]
    return edit_channel(channel_id, available_tags=payload)


def fetch_webhooks(channel_id: str) -> list[dict[str, Any]]:
    """그 채널에 이미 있는 웹훅."""
    res = requests.get(f"{_API}/channels/{channel_id}/webhooks",
                       headers=_headers(), timeout=_TIMEOUT)
    res.raise_for_status()
    return res.json()


def ensure_webhook(channel_id: str, name: str) -> dict[str, Any]:
    """같은 이름의 웹훅이 있으면 그것을, 없으면 새로 만들어 돌려준다.

    sync는 여러 번 돌리는 도구다(그것이 dry-run 기본값의 전제다). 매번 새로
    만들면 채널마다 웹훅이 쌓이고, 그중 어느 것이 `.env`에 있는지 알 수 없게 된다.
    """
    for hook in fetch_webhooks(channel_id):
        if str(hook.get("name")) == name and hook.get("url"):
            log.info("discord webhook reused: ch=%s id=%s", channel_id, hook.get("id"))
            return hook
    return create_webhook(channel_id, name)


def create_webhook(channel_id: str, name: str) -> dict[str, Any]:
    """운영 알림용 웹훅. 채널을 새로 만들면 기존 웹훅 URL은 죽은 채널을 가리킨다."""
    res = requests.post(f"{_API}/channels/{channel_id}/webhooks", headers=_headers(),
                        json={"name": name}, timeout=_TIMEOUT)
    res.raise_for_status()
    created = res.json()
    log.info("discord webhook created: ch=%s id=%s", channel_id, created.get("id"))
    return created


def reorder(entries: list[dict[str, Any]]) -> None:
    """카테고리·채널의 표시 순서를 한 번에 맞춘다.

    생성 시점의 position만으로는 순서가 지켜지지 않는다 — 새 카테고리는 무조건 맨 아래에
    붙고, 채널도 나중에 만든 것이 뒤로 간다. 매니페스트가 '설계도'이려면 순서까지
    매니페스트가 정해야 한다.
    """
    if not entries:
        return
    res = requests.patch(f"{_API}/guilds/{guild_id()}/channels", headers=_headers(),
                         json=entries, timeout=_TIMEOUT)
    res.raise_for_status()
    log.info("discord channels reordered: %d", len(entries))


def admin_user_id() -> str:
    """관리 봇의 사용자 ID — 안내문을 다시 올리지 않고 고쳐 쓰려면 자기 글을 찾아야 한다."""
    res = requests.get(f"{_API}/users/@me", headers=_headers(), timeout=_TIMEOUT)
    res.raise_for_status()
    return str(res.json()["id"])


def fetch_messages(channel_id: str, limit: int = 50) -> list[dict[str, Any]]:
    res = requests.get(f"{_API}/channels/{channel_id}/messages", headers=_headers(),
                       params={"limit": limit}, timeout=_TIMEOUT)
    res.raise_for_status()
    return res.json()


def upsert_message(channel_id: str, embeds: list[dict[str, Any]]) -> dict[str, Any]:
    """채널의 안내문을 올리거나, 이미 있으면 **고쳐 쓴다**.

    매번 새로 올리면 안내문이 쌓여 어느 것이 최신인지 알 수 없다. 관리 봇이 쓴 가장 오래된
    글을 안내문으로 보고 그걸 갱신한다 — 안내문은 채널의 첫 글이어야 위에 고정돼 보인다.

    **안내문은 카드가 아니라 서버 구조의 일부라 관리 토큰으로 쓴다.** `✦ START HERE`는
    @everyone에게 쓰기가 막힌 읽기 전용 카테고리이고, 거기에 쓸 수 있는 건 관리 봇이다.
    카드 봇에 권한을 새로 열면 매일 25개 잡이 쓰는 토큰이 안내문까지 고칠 수 있게 된다.
    """
    author = admin_user_id()
    mine = [m for m in fetch_messages(channel_id) if str(m.get("author", {}).get("id")) == author]
    payload = {"content": "", "embeds": embeds}
    if mine:
        target = mine[-1]
        res = requests.patch(f"{_API}/channels/{channel_id}/messages/{target['id']}",
                             headers=_headers(), json=payload, timeout=_TIMEOUT)
        res.raise_for_status()
        log.info("discord guide updated: ch=%s msg=%s", channel_id, target["id"])
        return res.json()
    res = requests.post(f"{_API}/channels/{channel_id}/messages",
                        headers=_headers(), json=payload, timeout=_TIMEOUT)
    res.raise_for_status()
    log.info("discord guide posted: ch=%s", channel_id)
    return res.json()


def fetch_roles() -> list[dict[str, Any]]:
    """길드의 모든 역할. @everyone은 ID가 길드 ID와 같다."""
    res = requests.get(f"{_API}/guilds/{guild_id()}/roles", headers=_headers(), timeout=_TIMEOUT)
    res.raise_for_status()
    return res.json()


def create_role(name: str, *, permissions: int, color: int = 0,
                hoist: bool = False, mentionable: bool = False) -> dict[str, Any]:
    """역할 하나 생성. 권한은 문자열로 보낸다 — 비트가 53개라 JSON 정수로는 정밀도가 샌다."""
    payload = {"name": name, "permissions": str(permissions), "color": color,
               "hoist": hoist, "mentionable": mentionable}
    res = requests.post(f"{_API}/guilds/{guild_id()}/roles", headers=_headers(),
                        json=payload, timeout=_TIMEOUT)
    res.raise_for_status()
    created = res.json()
    log.info("discord role created: %s (id=%s)", created.get("name"), created.get("id"))
    return created


def edit_role(role_id: str, **fields: Any) -> dict[str, Any]:
    """역할 수정. permissions는 문자열로 바꿔 보낸다."""
    if "permissions" in fields:
        fields["permissions"] = str(fields["permissions"])
    res = requests.patch(f"{_API}/guilds/{guild_id()}/roles/{role_id}", headers=_headers(),
                         json=fields, timeout=_TIMEOUT)
    res.raise_for_status()
    log.info("discord role updated: id=%s %s", role_id, sorted(fields))
    return res.json()


def edit_everyone(permissions: int) -> dict[str, Any]:
    """@everyone의 길드 권한. 역할 ID가 길드 ID와 같다는 점만 다르고 나머지는 같다."""
    return edit_role(guild_id(), permissions=permissions)


def put_overwrite(channel_id: str, target_id: str, *, allow: int, deny: int,
                  kind: int = 0) -> None:
    """채널 권한 오버라이트 하나를 **통째로 덮어쓴다**(kind 0=역할, 1=멤버).

    부분 갱신이 없는 API다. 그래서 선언한 값이 그대로 최종 상태가 되고, 그 편이 낫다 —
    코드에 적힌 것과 서버에 있는 것이 같아야 코드를 읽고 권한을 판단할 수 있다.
    """
    res = requests.put(f"{_API}/channels/{channel_id}/permissions/{target_id}",
                       headers=_headers(),
                       json={"allow": str(allow), "deny": str(deny), "type": kind},
                       timeout=_TIMEOUT)
    res.raise_for_status()
    log.info("discord overwrite set: ch=%s target=%s allow=%s deny=%s",
             channel_id, target_id, allow, deny)


def add_member_role(user_id: str, role_id: str) -> None:
    """멤버에게 역할을 붙인다. 관리 봇의 최고 역할이 이 역할보다 위여야 한다(아니면 50013)."""
    res = requests.put(f"{_API}/guilds/{guild_id()}/members/{user_id}/roles/{role_id}",
                       headers=_headers(), timeout=_TIMEOUT)
    res.raise_for_status()
    log.info("discord role assigned: user=%s role=%s", user_id, role_id)


def bot_user_id(env_name: str) -> str | None:
    """다른 봇 토큰의 사용자 ID를 그 토큰으로 묻는다.

    카드 봇에게 역할을 붙이려면 그 봇의 사용자 ID가 필요하다. 관리형 역할에서 역추적할
    수도 있지만, 이름이 겹치거나 아직 역할이 없을 때 틀린 봇을 잡는다. 토큰이 곧 정체다.
    """
    token = os.environ.get(env_name, "").strip()
    if not token:
        return None
    res = requests.get(f"{_API}/users/@me",
                       headers={"Authorization": f"Bot {token}"}, timeout=_TIMEOUT)
    res.raise_for_status()
    return str(res.json()["id"])


def set_verification_level(level: int) -> dict[str, Any]:
    """가입 문턱. Community 전환이 켠 LOW(1)를 올릴 때 쓴다."""
    res = requests.patch(f"{_API}/guilds/{guild_id()}", headers=_headers(),
                         json={"verification_level": level}, timeout=_TIMEOUT)
    res.raise_for_status()
    log.info("discord verification level set: %d", level)
    return res.json()


def put_onboarding(payload: dict[str, Any]) -> dict[str, Any]:
    """Server Guide(온보딩)를 통째로 교체한다. Community 길드에서만 동작한다."""
    res = requests.put(f"{_API}/guilds/{guild_id()}/onboarding", headers=_headers(),
                       json=payload, timeout=_TIMEOUT)
    res.raise_for_status()
    log.info("discord onboarding applied: prompts=%d", len(payload.get("prompts") or []))
    return res.json()
