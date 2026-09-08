"""CLI 진입점은 전부 같은 준비 과정을 거친다.

`configure_logging()`이 안 불리면 루트 로거에 처리기가 없고, `logging`의 lastResort
처리기가 WARNING 위만 stderr로 흘린다 — **진행·결과 줄은 전부 INFO라서 조용히
버려진다.** 13F 백필이 그랬다: 4,927행을 적재하고 로그 파일이 0바이트였다. 종료
코드는 0이라 아무것도 이상해 보이지 않는다.

`.env`도 마찬가지다 — 빠지면 첫 연결에서 자격증명이 없다고 죽는다. 둘 다
`bootstrap.start_cli()` 하나가 책임지고, 여기서는 모든 진입점이 그것을 거치는지만
본다.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "investment_agent"


def _entrypoints() -> list[Path]:
    """`python -m ...`으로 실행되도록 만든 모듈 — `__main__` 블록이 그 표식이다."""
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if '__name__ == "__main__"' in path.read_text(encoding="utf-8"):
            found.append(path)
    return found


def _calls_start_cli(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "start_cli"
        for node in ast.walk(tree)
    )


class CliEntrypointContractTest(unittest.TestCase):
    def test_there_are_entrypoints_to_check(self) -> None:
        """수집 규칙이 어긋나면 이 파일의 모든 검사가 공허하게 통과한다."""
        self.assertGreater(len(_entrypoints()), 50)

    def test_every_entrypoint_starts_the_cli(self) -> None:
        offenders = [
            path.relative_to(ROOT).as_posix()
            for path in _entrypoints()
            if not _calls_start_cli(path)
        ]
        self.assertEqual([], offenders)

    def test_start_cli_configures_logging(self) -> None:
        """이름만 바뀌고 로깅 설정이 빠지면 위 검사는 통과한 채 로그만 사라진다."""
        source = (PACKAGE / "bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("configure_logging()", source)


if __name__ == "__main__":
    unittest.main()
