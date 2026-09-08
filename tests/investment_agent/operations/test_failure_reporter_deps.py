"""실패 보고 워크플로의 최소 의존성 계약."""
from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class FailureReporterDependencyTest(unittest.TestCase):
    def test_reporter_uses_the_locked_core_group(self):
        workflow = (ROOT / ".github/workflows/ops_failure_report.yml").read_text(encoding="utf-8")
        groups = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["dependency-groups"]
        # 인라인 uv sync든 composite action이든 "가벼운 core만"이 이 검사의 뜻이다.
        self.assertIn("group: core", workflow)
        self.assertIn("python-dotenv", "\n".join(groups["core"]).lower())


if __name__ == "__main__":
    unittest.main()
