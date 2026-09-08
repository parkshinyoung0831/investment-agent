"""선언한 역할·권한을 서버에 맞춘다.

    python -m investment_agent.notifications.discord_admin.entries.roles            # 무엇이 바뀔지만 본다(기본 안전)
    python -m investment_agent.notifications.discord_admin.entries.roles --apply    # 실제로 반영한다

sync 다음, guide 앞이다. 오버라이트를 걸려면 채널이 먼저 있어야 하고, 온보딩은 여기서
만든 역할 ID를 참조한다: **sync → roles → guide → onboarding.**

권한은 되돌리기가 채널보다 어렵다 — 잘못 열면 그 사이에 일어난 일은 남는다. 그래서 여기도
기본이 dry-run이고, 출력은 비트가 아니라 사람이 읽는 이름으로 낸다.
"""
from __future__ import annotations

import argparse
from typing import Any

import requests

from investment_agent.platform.logging import configure_logging, get_logger
from investment_agent.notifications.discord_admin import client, manifest, roles
from investment_agent.notifications.discord_admin.entries.sync import _emit

log = get_logger(__name__)


def _role_ids(existing: list[dict[str, Any]], guild_id: str) -> dict[str, str]:
    """역할 key -> ID. 아직 없는 역할은 빠진다(그 오버라이트는 '역할 없음'으로 보고된다)."""
    by_name = {str(r.get("name")): str(r.get("id")) for r in existing}
    ids = {roles.EVERYONE_KEY: str(guild_id)}
    for declared in roles.ROLES:
        found = by_name.get(declared["name"])
        if found:
            ids[declared["key"]] = found
    return ids


def _label(role_key: str) -> str:
    return "@everyone" if role_key == roles.EVERYONE_KEY else roles.role(role_key)["name"]


def _report(everyone: dict[str, Any] | None, plan: dict[str, list[dict[str, Any]]],
            overwrites: dict[str, list[dict[str, Any]]], guild: dict[str, Any]) -> None:
    lines: list[str] = ["", "@everyone (길드 기본)"]
    if everyone is None:
        lines.append(f"  = 그대로  {roles.describe(roles.EVERYONE_PERMISSIONS)}")
    else:
        if everyone["removing"]:
            lines.append(f"  - 뺌      {roles.describe(everyone['removing'])}")
        if everyone["adding"]:
            lines.append(f"  + 줌      {roles.describe(everyone['adding'])}")
        lines.append(f"  → 최종    {roles.describe(everyone['wanted'])}")

    lines += ["", "역할"]
    for item in plan["create"]:
        lines.append(f"  + 생성    {item['name']}")
        lines.append(f"            {roles.describe(item['permissions'])}")
    for item in plan["update"]:
        lines.append(f"  ~ 수정    {item['name']}")
        lines.append(f"            지금: {roles.describe(item['permissions_current'])}")
        lines.append(f"            선언: {roles.describe(item['permissions'])}")
    for item in plan["ok"]:
        lines.append(f"  = 있음    {item['name']}  id={item['id']}")

    lines += ["", "채널 권한 (예외만 — 나머지는 길드 기본값이 그대로 적용됩니다)"]
    for item in overwrites["apply"]:
        mark = "🔒" if item["deny"] else "+"
        what = (f"차단: {roles.describe(item['deny'])}" if item["deny"]
                else f"허용: {roles.describe(item['allow'])}")
        lines.append(f"  {mark} {item['target']}  [{_label(item['role'])}]  {what}")
    for item in overwrites["ok"]:
        lines.append(f"  = {item['target']}  [{_label(item['role'])}]  그대로")
    for item in overwrites["missing"]:
        tail = ("이번 --apply에서 함께 처리됩니다" if item["why"] == "역할 없음"
                else "sync를 먼저 돌리세요")
        lines.append(f"  ! {item['target']}  [{_label(item['role'])}]  {item['why']} — {tail}")

    level = int(guild.get("verification_level") or 0)
    if level != roles.VERIFICATION_LEVEL:
        lines += ["", f"가입 문턱: {level} -> {roles.VERIFICATION_LEVEL} "
                      "(MEDIUM · 가입 5분이 안 된 계정은 말할 수 없음)"]
    _emit("\n".join(lines))


def _assign_bots() -> None:
    """봇 역할을 실제 봇에게 붙인다. 못 붙여도 나머지 적용을 되돌리지 않는다."""
    fresh = {str(r.get("name")): str(r.get("id")) for r in client.fetch_roles()}
    for declared in roles.ROLES:
        env_name = declared.get("bot_env")
        role_id = fresh.get(declared["name"])
        if not env_name or not role_id:
            continue
        user_id = client.bot_user_id(env_name)
        if not user_id:
            _emit(f"  ! {env_name}이 없어 {declared['name']} 부여를 건너뜁니다 "
                  "— Discord 서버 설정에서 직접 붙이세요")
            continue
        try:
            client.add_member_role(user_id, role_id)
        except requests.HTTPError as exc:
            # 50013: 관리 봇의 역할이 이 역할보다 아래다. 사람이 역할 순서를 올려야 한다.
            _emit(f"  ! {declared['name']} 부여 실패({exc.response.status_code}) "
                  "— ATLAS Architect 역할을 목록에서 더 위로 올린 뒤 다시 돌리세요")
            continue
        _emit(f"  ✓ {declared['name']} -> 봇 {user_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Discord 역할·권한 동기화")
    parser.add_argument("--apply", action="store_true", help="실제로 반영한다")
    parser.add_argument("--no-verification", action="store_true",
                        help="가입 문턱(verification level)은 건드리지 않는다")
    args = parser.parse_args()

    configure_logging()
    guild = client.fetch_guild()
    guild_id = str(guild["id"])
    existing_roles = client.fetch_roles()
    channels = client.fetch_channels()

    everyone = roles.plan_everyone(existing_roles, guild_id)
    plan = roles.plan_roles(existing_roles)
    overwrites = roles.plan_overwrites(channels, _role_ids(existing_roles, guild_id))
    _report(everyone, plan, overwrites, guild)

    if not args.apply:
        _emit("\n계획만 출력했습니다. 실제로 반영하려면 --apply 를 붙이세요.")
        return 0

    # @everyone을 먼저 좁힌다. 역할을 먼저 만들면 그 사이가 '아무나 쓸 수 있는' 창이 된다.
    if everyone is not None:
        client.edit_everyone(roles.EVERYONE_PERMISSIONS)
        _emit("\n  ✓ @everyone 길드 권한 적용")

    for item in plan["create"]:
        client.create_role(item["name"], permissions=item["permissions"],
                           color=item["color"], hoist=item["hoist"],
                           mentionable=item["mentionable"])
        _emit(f"  ✓ 역할 생성  {item['name']}")
    for item in plan["update"]:
        client.edit_role(item["id"], permissions=item["permissions"],
                         hoist=item["hoist"], mentionable=item["mentionable"])
        _emit(f"  ✓ 역할 수정  {item['name']}")

    _assign_bots()

    # 역할을 만든 뒤라 이번에는 ID가 다 잡힌다.
    fresh = client.fetch_roles()
    final = roles.plan_overwrites(channels, _role_ids(fresh, guild_id))
    for item in final["apply"]:
        client.put_overwrite(item["channel_id"], item["role_id"],
                             allow=item["allow"], deny=item["deny"])
        _emit(f"  ✓ 권한 적용  {item['target']}  [{_label(item['role'])}]")
    for item in final["missing"]:
        _emit(f"  ! 건너뜀    {item['target']}  [{_label(item['role'])}]  {item['why']}")

    if not args.no_verification and int(guild.get("verification_level") or 0) < roles.VERIFICATION_LEVEL:
        client.set_verification_level(roles.VERIFICATION_LEVEL)
        _emit(f"  ✓ 가입 문턱 {roles.VERIFICATION_LEVEL}(MEDIUM)")

    unmanaged = [str(r.get("name")) for r in fresh
                 if str(r.get("id")) != guild_id
                 and str(r.get("name")) not in {d["name"] for d in roles.ROLES}]
    if unmanaged:
        _emit("\n  ? 선언에 없는 역할: " + ", ".join(unmanaged)
              + "\n    (관리형 봇 역할과 사람이 만든 역할입니다 — 삭제는 하지 않습니다)")
    _emit(f"\n✓ 역할·권한 반영 완료 · 채널 {len(manifest.channels())}개 기준")
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
