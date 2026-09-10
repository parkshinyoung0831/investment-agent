"""읽기만 하는 경로는 research 저장소를 쓰기로 열지 않는다.

DuckDB는 쓰기 연결에 배타 잠금을 건다. 읽으면서 쓰기로 열면 같은 파일을 보는 다른
프로세스가 있을 때 조회가 IOException으로 죽는다 — 하네스가 지표를 쓰는 동안
대시보드나 후보 선정이 그렇게 막혔다("다른 프로세스가 파일을 사용 중"). 읽는
쪽에서 잠금을 잡을 이유는 없다.

`platform/db/duckdb.py`가 같은 규칙을 이미 문서로 갖고 있다 — 여기서는 trading이
그것을 지키는지 잰다.
"""
from __future__ import annotations

import ast
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TARGET = ROOT / "src" / "investment_agent" / "trading" / "supabase_repository.py"

#: 읽기 전용 연결로 충분한 호출. 나머지(upsert_*)는 쓰기라 잠금이 필요하다.
READ_METHODS = frozenset({"records", "features_for_ticker", "allocations"})


def _read_only_kwarg(node: ast.Call) -> bool:
    return any(
        keyword.arg == "read_only" and getattr(keyword.value, "value", None) is True
        for keyword in node.keywords
    )


def _offenders() -> list[str]:
    tree = ast.parse(TARGET.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in READ_METHODS:
            continue
        owner = node.func.value
        if not (isinstance(owner, ast.Call) and isinstance(owner.func, ast.Name)
                and owner.func.id == "ResearchStore"):
            continue
        if not _read_only_kwarg(owner):
            found.append(f"line {node.lineno}: {node.func.attr}")
    return found


class ResearchStoreReadPathTest(unittest.TestCase):
    def test_technical_snapshot_does_not_request_writer_connection(self) -> None:
        from investment_agent.research.features import db
        from investment_agent.research.storage.repository import ResearchStore

        def read_snapshot(store, *args, **kwargs):
            if not store.read_only:
                raise PermissionError("writer conflicts with another process reader")
            return [{"ticker": "AAPL"}]

        with patch.object(ResearchStore, "latest_feature_as_of", read_snapshot):
            rows = db.latest_signal_as_of("AAPL", datetime(2026, 9, 9, tzinfo=timezone.utc))
        self.assertEqual(rows, [{"ticker": "AAPL"}])

    def test_there_are_read_calls_to_check(self) -> None:
        """호출이 없으면 아래 검사는 아무것도 보증하지 않는다."""
        tree = ast.parse(TARGET.read_text(encoding="utf-8"))
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in READ_METHODS
        ]
        self.assertGreater(len(calls), 3)

    def test_read_calls_open_the_store_read_only(self) -> None:
        self.assertEqual([], _offenders())


if __name__ == "__main__":
    unittest.main()
