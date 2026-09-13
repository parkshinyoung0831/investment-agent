"""포럼으로 선언된 목적지에 보내는 topic은 스레드를 함께 그려야 한다.

Discord 포럼 채널은 `/channels/{id}/messages`를 **400으로 거절한다** — 첫 글이 곧
스레드다. 그래서 목적지가 포럼인 topic을 발행하는 패키지는 `Rendered(thread=ForumThread(...))`를
만들어야 하는데, 그 실패는 원장의 포기 행으로만 남고 ETL 워크플로는 초록으로 끝난다.
선언(포럼)과 전송(메시지)이 어긋난 채 오래 갈 수 있는 모양이다.

여기서는 topic 카탈로그에서 포럼 채널을 가리키는 topic을 골라, 그 topic을 선언하는 알림
패키지가 실제로 `ForumThread`를 만드는지 소스에서 확인한다.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from investment_agent.notifications.discord_admin import manifest
from investment_agent.notifications.subscriptions import KIND_ENV
from investment_agent.notifications.topics import TOPICS

ROOT = Path(__file__).resolve().parents[3]
PRODUCERS = ROOT / "src" / "investment_agent" / "notifications"


def _forum_topics() -> set[str]:
    envs = {c["env"] for c in manifest.channels() if c.get("env") and c["kind"] == manifest.FORUM}
    return {name for name, topic in TOPICS.items() if KIND_ENV.get(topic.channel_kind) in envs}


def _packages() -> dict[str, dict[str, bool]]:
    """패키지 -> {선언한 topic 이름: 패키지 안에서 ForumThread를 만드는가}."""
    found: dict[str, dict[str, bool]] = {}
    for package in sorted(p for p in PRODUCERS.iterdir() if p.is_dir() and not p.name.startswith("_")):
        declared: set[str] = set()
        builds_thread = False
        for path in package.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                if node.func.id == "topic" and node.args and isinstance(node.args[0], ast.Constant):
                    declared.add(str(node.args[0].value))
                if node.func.id == "ForumThread":
                    builds_thread = True
        if declared:
            found[package.name] = {name: builds_thread for name in declared}
    return found


class ForumTopicsBuildAThreadTest(unittest.TestCase):
    def test_every_forum_topic_is_published_with_a_thread(self) -> None:
        forum = _forum_topics()
        offenders = sorted(
            f"{package}:{name}"
            for package, topics in _packages().items()
            for name, builds_thread in topics.items()
            if name in forum and not builds_thread
        )
        self.assertEqual([], offenders)

    def test_the_scan_knows_which_topics_are_forums(self) -> None:
        """대상을 못 고르면 위 테스트는 공허하게 통과한다."""
        forum = _forum_topics()
        self.assertTrue({"earnings.report", "earnings.flash", "strategy.allocation", "guru.filing"} <= forum, forum)
        self.assertNotIn("macro.daily", forum)
        packages = _packages()
        # 스캔이 run.py 밖의 선언도 보는지 — 캘린더 topic은 candidates.py에 있다.
        self.assertIn("earnings.schedule", packages.get("earnings_calendar", {}))
        # 포럼이 아닌 패키지는 스레드를 만들지 않는다 — 스캔이 무엇이든 참으로 보지 않는지.
        self.assertFalse(any(packages["macro"].values()))


if __name__ == "__main__":
    unittest.main()
