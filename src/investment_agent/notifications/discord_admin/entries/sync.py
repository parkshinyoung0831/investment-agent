"""매니페스트대로 Discord 채널을 맞춘다.

    python -m investment_agent.notifications.discord_admin.entries.sync            # 계획만 보여준다(기본 안전)
    python -m investment_agent.notifications.discord_admin.entries.sync --apply    # 없는 것을 만들고 .env에 ID를 쓴다
    ... --apply --recreate --confirm "<길드 이름>"                                  # 전부 지우고 처음부터

기본이 dry-run인 이유: 서버 구조는 사람들이 보는 표면이라 실수로 채널이 늘어나면
눈에 띈다. 만들기 전에 무엇을 만들지 먼저 읽게 한다.

`--recreate`는 길드의 **모든 채널과 카테고리를 지운다** — 메시지와 포럼 스레드가
함께 사라지고 되돌릴 수 없다. 그래서 길드 이름을 그대로 다시 치게 한다
(`scripts/db_bootstrap.py apply --confirm <ref>`와 같은 관례다). 한 글자라도 다르면
아무것도 하지 않는다.

포럼이 있으면 길드를 먼저 Community로 바꾼다 — 순서가 뒤집히면 포럼 생성이 403이다.
"""
from __future__ import annotations

import argparse
from typing import Any

from investment_agent.platform.logging import configure_logging, get_logger
from investment_agent.notifications.discord_admin import client, envfile, manifest, sync
from investment_agent.platform.storage_paths import repository_root

log = get_logger(__name__)

_ENV_PATH = repository_root() / ".env"


def _emit(text: str) -> None:
    """이모지가 섞이므로 Windows 콘솔에서도 죽지 않게 바이트로 쓴다."""
    import sys
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        print(text)  # noqa: T201 - 사람이 읽으라고 있는 출력이다
        return
    stream.write(text.encode("utf-8", "replace") + b"\n")
    stream.flush()


def _ensure_community(created: dict[str, dict[str, Any]]) -> None:
    """포럼을 만들기 전에 길드가 Community인지 확인하고, 아니면 바꾼다."""
    if "COMMUNITY" in set(client.fetch_guild().get("features") or []):
        return
    rules, updates = manifest.role_channel("rules"), manifest.role_channel("updates")
    if not rules or not updates:
        raise RuntimeError("포럼을 쓰려면 매니페스트에 role='rules'/'updates' 채널이 있어야 합니다")
    missing = [c["name"] for c in (rules, updates) if c["name"] not in created]
    if missing:
        raise RuntimeError(f"Community 전환에 필요한 채널을 찾지 못했습니다: {missing}")
    client.enable_community(rules_channel_id=created[rules["name"]]["id"],
                            updates_channel_id=created[updates["name"]]["id"])
    _emit("  ✓ 길드를 Community로 전환 (포럼·온보딩 사용 가능)")


def _reorder(category_ids: dict[str, str], matched: list[dict[str, Any]]) -> None:
    """카테고리와 채널을 매니페스트 선언 순서대로 다시 세운다.

    이미 있던 채널은 자기 자리에 있지 않다 — 새로 만든 것만 position을 받으므로
    한 번은 전체를 맞춰 줘야 한다. 매니페스트에 없는 채널은 건드리지 않는다.

    카테고리 이동은 벌크에 섞지 못한다 — Discord는 한 요청에서 parent_id를 바꾸는 채널을
    하나만 받는다(40009). 그래서 옮길 것은 먼저 하나씩 옮기고, 순서만 벌크로 맞춘다.
    """
    by_name = {c["name"]: c for c in matched}
    for channel in manifest.channels():
        found = by_name.get(channel["name"])
        wanted = category_ids.get(channel["category"])
        if found and wanted and found.get("parent_current") not in (None, wanted):
            client.edit_channel(found["id"], parent_id=wanted)
            _emit(f"  → 이동      #{channel['name']}  ({channel['category']})")

    entries: list[dict[str, Any]] = [
        {"id": category_ids[category["name"]], "position": order}
        for order, category in enumerate(manifest.LAYOUT)
        if category["name"] in category_ids
    ]
    entries += [
        {"id": by_name[channel["name"]]["id"], "position": channel["position"]}
        for channel in manifest.channels() if channel["name"] in by_name
    ]
    client.reorder(entries)
    _emit(f"  ↕ 순서 정렬  항목 {len(entries)}개")


def _teardown(args: Any) -> bool:
    """길드의 채널·카테고리를 전부 지운다. 막혔으면 True(=중단)를 돌려준다.

    되돌릴 수 없으므로 길드 이름을 그대로 다시 치게 한다. 확인 문구가 다르면
    아무것도 지우지 않는다.
    """
    if not args.apply:
        _emit("--recreate는 --apply와 함께 써야 합니다.")
        return True
    guild_name = str(client.fetch_guild().get("name") or "")
    if args.confirm != guild_name:
        _emit(f'길드 이름이 일치하지 않습니다. --confirm "{guild_name}" 를 그대로 넘기세요.')
        return True

    guild = client.fetch_guild()
    # Community 길드의 규칙·모더레이터 채널은 Discord가 삭제를 거절한다(400).
    # 이름이 아니라 길드가 가리키는 ID로 고른다 — 이름은 매니페스트가 바꿀 수 있다.
    protected = {
        str(guild.get("rules_channel_id") or ""),
        str(guild.get("public_updates_channel_id") or ""),
    } - {""}

    existing = client.fetch_channels()
    channels = [c for c in existing
                if c.get("type") != manifest.CATEGORY and str(c["id"]) not in protected]
    categories = [c for c in existing if c.get("type") == manifest.CATEGORY]
    _emit(f"삭제 대상: 채널 {len(channels)}개 · 카테고리 {len(categories)}개 "
          f"(길드 {guild_name}, Community 필수 채널 {len(protected)}개는 보존)")
    # 채널을 먼저 지운다 — 카테고리를 먼저 지우면 자식이 최상위로 올라와
    # 남은 목록과 어긋난다.
    for channel in channels + categories:
        try:
            client.delete_channel(str(channel["id"]))
        except Exception as exc:  # noqa: BLE001 - 하나가 막혀도 나머지는 지운다
            # 여기서 멈추면 구조가 반만 남는다 — 그 상태가 가장 읽기 어렵다.
            _emit(f"  ! 삭제 실패  #{channel.get('name')}  {exc}")
            continue
        _emit(f"  - 삭제      #{channel.get('name')}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Discord 채널 구조 동기화")
    parser.add_argument("--apply", action="store_true", help="실제로 만들고 .env를 갱신한다")
    parser.add_argument("--no-env", action="store_true", help=".env는 건드리지 않는다")
    parser.add_argument("--recreate", action="store_true",
                        help="모든 채널·카테고리를 지우고 매니페스트대로 다시 만든다 (되돌릴 수 없음)")
    parser.add_argument("--confirm", default="",
                        help="--recreate에 필요한 길드 이름. 정확히 일치해야 실행한다")
    args = parser.parse_args()

    configure_logging()
    if args.recreate and _teardown(args):
        return 2

    existing = client.fetch_channels()
    result = sync.plan(existing)

    lines = ["", f"서버 채널 {len(existing)}개 · 매니페스트 {len(manifest.channels())}개", ""]
    for cat in result["create_categories"]:
        lines.append(f"  + 카테고리  {cat['name']}")
    for ch in result["create_channels"]:
        kind = "포럼" if ch["kind"] == manifest.FORUM else "채널"
        lines.append(f"  + {kind}      #{ch['name']}  ({ch['category']})")
    for ch in result["matched"]:
        lines.append(f"  = 있음      #{ch['name']}  id={ch['id']}")
    for ch in result["tag_updates"]:
        lines.append(f"  ~ 태그      #{ch['name']}  -> {', '.join(ch['tags'])}")
    for ch in result["unmanaged"]:
        lines.append(f"  ? 매니페스트에 없음  #{ch['name']}  id={ch['id']}")
    _emit("\n".join(lines))

    if not args.apply:
        _emit("\n계획만 출력했습니다. 실제로 반영하려면 --apply 를 붙이세요.")
        return 0

    # 카테고리를 먼저 만들어야 채널의 parent_id를 채울 수 있다.
    category_ids = {
        str(c.get("name")): str(c.get("id"))
        for c in existing if c.get("type") == manifest.CATEGORY
    }
    for cat in result["create_categories"]:
        created_cat = client.create_channel(cat["name"], kind=manifest.CATEGORY)
        category_ids[cat["name"]] = str(created_cat["id"])

    matched = list(result["matched"])
    known: dict[str, dict[str, Any]] = {c["name"]: c for c in matched}

    # 포럼은 Community 전환 뒤에야 만들 수 있고, 전환에는 규칙·모더레이터 채널이 먼저 있어야 한다.
    todo = sorted(result["create_channels"], key=lambda c: c["kind"] == manifest.FORUM)
    for ch in todo:
        if ch["kind"] == manifest.FORUM and manifest.needs_community():
            _ensure_community(known)
        created = client.create_channel(
            ch["name"], kind=ch["kind"],
            parent_id=category_ids.get(ch["category"]), topic=ch.get("topic"),
            position=ch.get("position"), tags=ch.get("tags"),
        )
        entry = {**ch, "id": str(created["id"])}
        matched.append(entry)
        known[ch["name"]] = entry

    for ch in result["tag_updates"]:
        client.set_forum_tags(ch["id"], ch["tags"], ch["tags_current"])
        _emit(f"  ~ 태그 갱신  #{ch['name']}")

    _reorder(category_ids, matched)

    # 운영 알림은 봇 토큰이 아니라 webhook으로 나간다(Actions에 봇 토큰을 주지
    # 않으려고). 채널을 새로 만들면 옛 webhook URL은 죽은 채널을 가리키므로 함께 만든다.
    values = sync.env_updates(matched)
    by_key = {c["key"]: c for c in matched}
    for key, env_name in manifest.webhook_bindings().items():
        channel = by_key.get(key)
        if channel is None:
            continue
        created = client.ensure_webhook(channel["id"], f"ATLAS {channel['name']}")
        values[env_name] = str(created["url"])
        _emit(f"  + webhook   #{channel['name']} -> {env_name}")

    if not args.no_env:
        changed = envfile.update(_ENV_PATH, values)
        _emit(f"\n.env 갱신: {', '.join(sorted(changed)) or '변경 없음'}")
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
