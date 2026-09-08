"""포럼으로 선언된 목적지에는 스레드 제목을 함께 보내야 한다.

Discord 포럼 채널은 `/channels/{id}/messages`를 **400으로 거절한다** — 첫 글이 곧
스레드다. 그래서 목적지가 포럼인 알림은 `enqueue(..., thread_name=...)`을 넘겨야
하는데, 그 실패는 outbox의 실패 행으로만 남고 ETL 워크플로는 초록으로 끝난다.
선언(포럼)과 전송(메시지)이 어긋난 채 오래 갈 수 있는 모양이다.

여기서는 `KIND_ENV`가 포럼 채널을 가리키는 kind를 골라, 그 kind를 보내는
`run.py`가 실제로 `thread_name`을 넘기는지 소스에서 확인한다.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from investment_agent.notifications.discord_admin import manifest
from investment_agent.notifications.subscriptions import KIND_ENV

ROOT = Path(__file__).resolve().parents[3]
PRODUCERS = ROOT / "src" / "investment_agent" / "notifications"


def _forum_envs() -> set[str]:
    return {c["env"] for c in manifest.channels()
            if c.get("env") and c["kind"] == manifest.FORUM}


def _forum_kinds() -> set[str]:
    envs = _forum_envs()
    return {kind for kind, env in KIND_ENV.items() if env in envs}


def _enqueued_kinds_without_thread() -> dict[str, list[str]]:
    """`enqueue(kind="x", ...)` 호출 중 `thread_name`이 없는 것."""
    offenders: dict[str, list[str]] = {}
    # `run.py`만 보면 안 된다 — strategy는 `service.py`에서 보낸다.
    for path in sorted(PRODUCERS.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "enqueue"):
                continue
            keywords = {k.arg for k in node.keywords}
            kind = next((k.value.value for k in node.keywords
                         if k.arg == "kind" and isinstance(k.value, ast.Constant)), None)
            if kind is None or "thread_name" in keywords:
                continue
            offenders.setdefault(str(kind), []).append(
                f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    return offenders


class ForumKindsCarryAThreadNameTest(unittest.TestCase):
    def test_every_forum_kind_sends_a_thread_name(self) -> None:
        forum_kinds = _forum_kinds()
        offenders = {
            kind: sites for kind, sites in _enqueued_kinds_without_thread().items()
            if kind in forum_kinds
        }
        self.assertEqual({}, offenders)

    def test_the_scan_knows_which_kinds_are_forums(self) -> None:
        """대상을 못 고르면 위 테스트는 공허하게 통과한다."""
        self.assertIn("fundamentals_earnings", _forum_kinds())
        self.assertIn("fundamentals_flash", _forum_kinds())
        self.assertIn("strategy", _forum_kinds())
        self.assertNotIn("macro_core", _forum_kinds())
        # 스캔이 `run.py` 밖의 발송자도 보는지 — strategy는 service.py에 있다.
        seen = {site for sites in _enqueued_kinds_without_thread().values() for site in sites}
        self.assertTrue(any("macro" in site for site in seen), sorted(seen))


if __name__ == "__main__":
    unittest.main()
