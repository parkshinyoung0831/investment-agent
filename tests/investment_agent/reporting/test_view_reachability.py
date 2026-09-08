"""코드가 실제로 부르는 모양으로 reporting 뷰를 읽을 수 있어야 한다.

`ReportingQueries.read`는 이력 뷰가 통째로 스캔되는 것을 막으려고 `scope_column`을
요구한다. 그런데 그 요구는 **호출 모양과 따로** 선언돼 있어서, 아무 필터 없이 읽는
것이 유일한 용법인 뷰에 scope가 붙어도 아무 테스트가 잡지 못했다.

실제로 그랬다: `reporting.macro_measures`는 measure master(시간 컬럼 없음)인데
scope가 붙어 있어 화면(`dashboard/db.py`)과 read model(`reporting/readers/dashboard.py`)
둘 다 `ValueError`를 받았고, 두 곳 모두 그것을 `DataResult.error`로 삼켜서
경제지표 화면이 조용히 오류 카드만 띄웠다.

여기서는 소스에서 필터 없는 호출을 찾아 그 뷰가 정말 읽히는지 확인한다.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from investment_agent.reporting.readers.financial import VIEWS, ReportingQueries

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "src" / "investment_agent"
_READERS = {"load_reporting_view", "_read", "read"}


def _unfiltered_view_calls() -> dict[str, list[str]]:
    """`f("some_view")` 꼴로 인자 하나만 준 호출을 모은다."""
    found: dict[str, list[str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 문법 오류는 별도 검사가 잡는다
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or node.keywords:
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            if name not in _READERS or len(node.args) != 1:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value in VIEWS:
                found.setdefault(arg.value, []).append(
                    f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    return found


class UnfilteredViewCallsAreReadableTest(unittest.TestCase):
    def test_every_unfiltered_call_site_names_a_view_that_allows_it(self) -> None:
        queries = ReportingQueries(None)  # 연결 없이 인자 검증 단계까지만 간다
        offenders: list[str] = []
        for view, sites in sorted(_unfiltered_view_calls().items()):
            try:
                queries.read(view)
            except ValueError as error:
                offenders.append(f"{view}: {error} <- {', '.join(sites)}")
        self.assertEqual([], offenders)

    def test_the_scan_actually_finds_the_known_call_sites(self) -> None:
        """검사 대상을 못 찾으면 위 테스트는 공허하게 통과한다.

        여기서 특정 뷰를 이름으로 붙잡는 것은 `macro_measures` 하나뿐이다 — 그것은
        시간 컬럼이 없어 **필터 없이 읽는 것이 유일한 용법**이라 앞으로도 이 모양이
        유지된다. 다른 뷰는 필터가 생기면 이 목록에서 정당하게 빠지므로(실제로
        `macro_series`가 발표 도메인 필터를 얻으며 그랬다) 이름으로 고정하지 않는다.
        """
        found = _unfiltered_view_calls()
        self.assertIn("macro_measures", found)
        self.assertGreaterEqual(len(found["macro_measures"]), 1)


class MasterViewsHaveNoScopeTest(unittest.TestCase):
    """시간 컬럼이 없는 뷰에 scope를 걸면 범위로 풀 길이 없다 — 영구히 못 읽는다."""

    def test_a_scoped_view_can_always_be_unlocked_by_a_range(self) -> None:
        stuck = sorted(
            name for name, spec in VIEWS.items()
            if spec.scope_column and spec.time_column is None
        )
        # institutional_positions는 accession 하나를 받는 것이 유일한 용법이라 의도된 예외다.
        self.assertEqual(["institutional_positions"], stuck)


if __name__ == "__main__":
    unittest.main()
