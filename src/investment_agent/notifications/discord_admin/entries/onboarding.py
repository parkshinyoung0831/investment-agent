"""Server Guide(온보딩)를 선언대로 맞춘다.

    python -m investment_agent.notifications.discord_admin.entries.onboarding           # 무엇이 적용될지만 본다
    python -m investment_agent.notifications.discord_admin.entries.onboarding --apply   # 실제로 적용한다

길드가 Community일 때만 동작한다(sync가 포럼을 만들며 전환한다).
"""
from __future__ import annotations

import argparse

from investment_agent.platform.logging import configure_logging, get_logger
from investment_agent.notifications.discord_admin import client, manifest, onboarding, roles
from investment_agent.notifications.discord_admin.entries.sync import _emit

log = get_logger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Discord 온보딩 동기화")
    parser.add_argument("--apply", action="store_true", help="실제로 적용한다")
    args = parser.parse_args()

    configure_logging()
    if "COMMUNITY" not in set(client.fetch_guild().get("features") or []):
        _emit("길드가 Community가 아닙니다 — sync를 먼저 돌려 포럼과 함께 전환하세요.")
        return 1

    by_name = {str(c.get("name")): str(c.get("id")) for c in client.fetch_channels()}
    channel_ids = {c["key"]: by_name[c["name"]] for c in manifest.channels()
                   if c["name"] in by_name}
    # 역할을 주는 옵션은 역할이 있어야 의미가 있다 — roles를 먼저 돌려야 하는 이유다.
    role_by_name = {str(r.get("name")): str(r.get("id")) for r in client.fetch_roles()}
    role_ids = {d["key"]: role_by_name[d["name"]] for d in roles.ROLES
                if d["name"] in role_by_name}
    payload = onboarding.build(channel_ids, role_ids)

    name_of = {cid: name for name, cid in by_name.items()}
    role_of = {rid: name for name, rid in role_by_name.items()}
    lines = ["", f"기본 채널 {len(payload['default_channel_ids'])}개: "
                 + ", ".join(f"#{name_of[i]}" for i in payload["default_channel_ids"]), ""]
    for prompt in payload["prompts"]:
        lines.append(f"  ▸ {prompt['title']}")
        for option in prompt["options"]:
            targets = [f"#{name_of[i]}" for i in option["channel_ids"]]
            targets += [f"[{role_of[i]}]" for i in option["role_ids"]]
            lines.append(f"      {option['emoji_name']} {option['title']} -> "
                         + ", ".join(targets))
    if not payload["enabled"]:
        lines += ["", "  ! Server Guide는 꺼진 상태로 적용됩니다 "
                      "(onboarding.ENABLED=False — 이유는 그 파일 위에 있습니다)."]
    missing = [d["name"] for d in roles.ROLES if d["key"] not in role_ids]
    if missing:
        lines.append("")
        lines.append("  ! 서버에 없는 역할: " + ", ".join(missing)
                     + " — roles를 먼저 돌리세요(해당 옵션은 빠집니다)")
    _emit("\n".join(lines))

    if not args.apply:
        _emit("\n계획만 출력했습니다. 실제로 반영하려면 --apply 를 붙이세요.")
        return 0

    client.put_onboarding(payload)
    _emit("\n✓ Server Guide 적용 완료")
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
