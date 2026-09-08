"""문서와 코드가 부르는 Discord 채널 이름은 선언에 실재해야 한다.

채널 구조는 `discord_admin/manifest.py`가 SSOT다(규칙 12). 그런데 안내 문구와
화면 라벨은 채널 이름을 **문자열로** 적는다 — 선언에서 채널을 지우거나 이름을 바꿔도
그 문자열은 그대로 남고, 사람은 없는 채널을 찾으러 간다. 에러가 나지 않으므로
아무도 모른다.

실제로 운영 채널을 넷으로 가른 뒤 `#시스템-로그`를 가리키는 문구가 여러 곳에
남아 있었다.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from investment_agent.notifications.discord_admin import manifest

ROOT = Path(__file__).resolve().parents[3]
SEARCH_ROOTS = (ROOT / "src", ROOT / "docs")

#: 채널처럼 보이지만 선언 대상이 아닌 것. 이유를 함께 적는다.
_NOT_CHANNELS = frozenset({
    "everyone",      # @everyone 역할
    "here",          # @here
})

_MENTION = re.compile(r"#([가-힣A-Za-z0-9][가-힣A-Za-z0-9-]{1,30})")
#: 마크다운 앵커 링크(`](#...)`)는 채널이 아니다.
_ANCHOR = re.compile(r"\]\([^)]*#")


def _declared_names() -> set[str]:
    return {str(channel["name"]) for channel in manifest.channels()}


def _mentions() -> dict[str, list[str]]:
    declared = _declared_names()
    found: dict[str, list[str]] = {}
    for root in SEARCH_ROOTS:
        for path in sorted(root.rglob("*")):
            if path.suffix not in {".py", ".md"} or "__pycache__" in path.parts:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if _ANCHOR.search(line):
                    continue
                for name in _MENTION.findall(line):
                    # 한국어는 조사가 붙는다 — `#실적-리포트의`는 그 채널을 가리킨다.
                    if any(name.startswith(known) for known in declared):
                        continue
                    if name in _NOT_CHANNELS:
                        continue
                    # 한글이 없는 이름은 앵커·해시태그일 가능성이 높다.
                    if not re.search(r"[가-힣]", name):
                        continue
                    found.setdefault(name, []).append(
                        f"{path.relative_to(ROOT).as_posix()}:{lineno}")
    return found


class MentionedChannelsExistTest(unittest.TestCase):
    def test_no_document_points_at_a_channel_that_is_not_declared(self) -> None:
        self.assertEqual({}, _mentions())

    def test_the_scan_actually_reads_channel_mentions(self) -> None:
        """대상을 못 찾으면 이 테스트는 공허하게 통과한다."""
        self.assertIn("운영-요약", _declared_names())
        hits = sum(
            len(_MENTION.findall(line))
            for path in (ROOT / "src" / "investment_agent" / "operations" / "README.md",)
            for line in path.read_text(encoding="utf-8").splitlines()
        )
        self.assertGreater(hits, 3)


if __name__ == "__main__":
    unittest.main()
