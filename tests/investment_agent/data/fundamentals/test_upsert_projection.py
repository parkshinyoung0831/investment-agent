"""upsert가 `on_conflict`로 부르는 컬럼은 payload에 있어야 한다.

`earnings_results` 저장은 행에서 허용 컬럼만 골라 보낸다. 그 목록에서 `accession_no`가
빠져 있었는데, 그것은 PK의 일부이자 `filings` FK다. 결과는 `23502 not-null` —
**그 종목의 실적 속보가 통째로 저장되지 않았다**(실측 27종목: AVGO·CRM·CRWD·DELL …).

`on_conflict`가 어떤 컬럼을 부르는데 payload에 그 컬럼이 없다는 것은 그 자체로
모순이다. 소스에서 그 모순을 찾는다 — DB에 물어보지 않고도 알 수 있는 사실이다.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SUPABASE = ROOT / "src" / "investment_agent" / "data" / "fundamentals" / "infrastructure" / "supabase"


def _payload_key_sets(tree: ast.Module) -> dict[str, set[str]]:
    """`*_keys = {...}` 꼴의 문자열 집합 상수."""
    found: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Set):
            continue
        values = {e.value for e in node.value.elts
                  if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.endswith("_keys") and values:
                found[target.id] = values
    return found


def _conflict_columns(tree: ast.Module) -> list[str]:
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "on_conflict" and isinstance(keyword.value, ast.Constant) \
                    and isinstance(keyword.value.value, str):
                out += [c.strip() for c in keyword.value.value.split(",") if c.strip()]
    return out


class ConflictColumnsAreSentTest(unittest.TestCase):
    def test_every_projected_upsert_keeps_its_conflict_columns(self) -> None:
        offenders: list[str] = []
        for path in sorted(SUPABASE.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            key_sets = _payload_key_sets(tree)
            if not key_sets:
                continue
            columns = set(_conflict_columns(tree))
            for name, keys in key_sets.items():
                missing = sorted(columns - keys)
                # 한 파일에 여러 표가 있으면 다른 표의 키가 섞인다 — 겹치는 것만 본다.
                if missing and columns & keys:
                    offenders.append(f"{path.name}:{name} 빠짐 {missing}")
        self.assertEqual([], offenders)

    def test_the_scan_sees_the_real_projection(self) -> None:
        """대상을 못 찾으면 이 테스트는 공허하게 통과한다."""
        tree = ast.parse((SUPABASE / "earnings_events.py").read_text(encoding="utf-8"))
        keys = _payload_key_sets(tree)
        self.assertIn("payload_keys", keys)
        self.assertIn("accession_no", keys["payload_keys"])
        self.assertIn("accession_no", _conflict_columns(tree))


if __name__ == "__main__":
    unittest.main()
