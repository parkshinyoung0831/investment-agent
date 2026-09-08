"""안내문(#시작하기·#서버-규칙)을 서버에 맞춘다.

    python -m investment_agent.notifications.discord_admin.entries.guide            # 무엇이 올라갈지만 본다
    python -m investment_agent.notifications.discord_admin.entries.guide --apply    # 올리거나, 이미 있으면 고쳐 쓴다

sync와 같은 규칙이다 — 기본이 dry-run이고, 다시 돌려도 결과가 같다(새 글을 쌓지 않고
기존 안내문을 수정한다).
"""
from __future__ import annotations

import argparse
import json

from investment_agent.platform.logging import configure_logging, get_logger
from investment_agent.notifications.discord_admin import client, guide, manifest
from investment_agent.notifications.discord_admin.entries.sync import _emit

log = get_logger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Discord 안내문 동기화")
    parser.add_argument("--apply", action="store_true", help="실제로 올리거나 고쳐 쓴다")
    args = parser.parse_args()

    configure_logging()
    by_key = {c["key"]: c for c in manifest.channels()}
    existing = {str(c.get("name")): str(c.get("id")) for c in client.fetch_channels()}

    targets = []
    for key, build in guide.PAGES.items():
        channel = by_key.get(key)
        if channel is None:
            _emit(f"  ! 매니페스트에 '{key}' 채널이 없습니다 — 건너뜁니다")
            continue
        channel_id = existing.get(channel["name"])
        if not channel_id:
            _emit(f"  ! #{channel['name']} 채널이 서버에 없습니다 — sync를 먼저 돌리세요")
            continue
        targets.append((channel["name"], channel_id, build()))

    for name, channel_id, embeds in targets:
        titles = ", ".join(str(e.get("title")) for e in embeds)
        _emit(f"  → #{name}  embed {len(embeds)}개 ({titles})")
        if not args.apply:
            _emit(json.dumps(embeds, ensure_ascii=False, indent=2)[:600] + " ...")

    if not args.apply:
        _emit("\n계획만 출력했습니다. 실제로 반영하려면 --apply 를 붙이세요.")
        return 0

    for name, channel_id, embeds in targets:
        client.upsert_message(channel_id, embeds)
        _emit(f"  ✓ #{name} 안내문 반영")
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
