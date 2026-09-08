"""`.env`의 특정 키만 제자리에서 갱신한다.

기존 줄 순서·주석을 보존한다 — 통째로 다시 쓰면 사람이 적어둔 메모가 날아간다.
비밀값을 다루므로 **읽은 내용을 로그에 남기지 않는다**(키 이름만 남긴다).
"""
from __future__ import annotations

import re
from pathlib import Path

from investment_agent.platform.logging import get_logger

log = get_logger(__name__)


def update(path: Path, values: dict[str, str]) -> list[str]:
    """values의 키를 갱신하고, 없으면 끝에 덧붙인다. 바뀐 키 이름 목록을 돌려준다."""
    if not values:
        return []
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    changed: list[str] = []
    remaining = dict(values)

    for index, line in enumerate(lines):
        match = re.match(r"^([A-Z0-9_]+)=", line)
        if not match:
            continue
        key = match.group(1)
        if key in remaining:
            new_line = f"{key}={remaining.pop(key)}"
            if new_line != line:
                lines[index] = new_line
                changed.append(key)

    if remaining:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# Discord 채널 ID (investment_agent.notifications.discord_admin.entries.sync 가 채워 넣는다)")
        for key, value in remaining.items():
            lines.append(f"{key}={value}")
            changed.append(key)

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("env updated: %s", ", ".join(sorted(changed)) or "(변경 없음)")
    return changed
