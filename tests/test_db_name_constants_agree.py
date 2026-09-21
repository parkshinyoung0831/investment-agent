"""같은 이름의 DB 이름 상수는 모듈마다 같은 값을 가진다(HC-11·12).

`SCHEMA_UNIVERSE`가 15곳에 다시 선언돼 있는 구조에서 진짜 위험은 중복 그 자체가 아니라 한 곳만 고쳐지는 것이다.
이름이 같은데 값이 다르면 한쪽은 조용히 없는 표를 본다.
"""
from __future__ import annotations

import ast
import collections
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "investment_agent"
PREFIXES = ("SCHEMA_", "T_", "RPC_", "V_")
# 다른 저장소(로컬 DuckDB 미러)의 표라서 원격 Postgres와 같은 이름일 이유가 없다.
DIFFERENT_STORE = {"data/market/local_mirror/store.py"}


def _declarations() -> dict[str, dict[str, list[str]]]:
    found: dict[str, dict[str, list[str]]] = collections.defaultdict(lambda: collections.defaultdict(list))
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC).as_posix()
        if relative in DIFFERENT_STORE:
            continue
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if (
                isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id.startswith(PREFIXES)
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
            ):
                found[node.targets[0].id][node.value.value].append(relative)
    return found


class DbNameConstantsAgreeTest(unittest.TestCase):
    def test_same_name_means_same_value(self) -> None:
        declarations = _declarations()
        self.assertGreater(len(declarations), 50, "선언을 못 찾으면 가드가 공허하게 통과한다")
        conflicts = {name: dict(values) for name, values in declarations.items() if len(values) > 1}
        self.assertEqual({}, conflicts)


if __name__ == "__main__":
    unittest.main()
