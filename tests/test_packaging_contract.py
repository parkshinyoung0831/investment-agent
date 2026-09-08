"""v1 Python packaging 계약 회귀 테스트."""
from __future__ import annotations

import ast
import tomllib
import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
_PACKAGE = _SRC / "investment_agent"
_GROUPS = {
    "core", "data", "research", "ml", "rl", "dashboard", "notifications",
    "execution", "intelligence", "dev",
    # cvxpy는 pyqlib의 전이 의존으로만 잠겨 있었고, 의도한 상한(<1.9, NumPy 2 회피)은
    # 옛 requirements 파일에만 있었다. 그 파일이 사라졌으므로 group이 소유한다.
    "portfolio",
}


class PackagingContractTest(unittest.TestCase):
    def test_src_root_is_not_an_importable_package(self):
        self.assertFalse((_SRC / "__init__.py").exists())

    def test_project_declares_every_runtime_dependency_group_and_lockfile(self):
        project = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(set(project["dependency-groups"]), _GROUPS)
        self.assertTrue((_ROOT / "uv.lock").exists())

    def test_source_never_imports_through_the_src_namespace(self):
        offenders = []
        for path in _PACKAGE.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                if any(name == "src" or name.startswith("src.") for name in names):
                    offenders.append(path.relative_to(_ROOT).as_posix())
                    break
        self.assertEqual(offenders, [])

    def test_every_cli_entrypoint_loads_dotenv_after_import(self):
        exempt = {
            "notifications/earnings_report/__init__.py",
            "notifications/macro/__init__.py",
        }
        offenders = []
        for path in _PACKAGE.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if 'if __name__ == "__main__"' not in source:
                continue
            relative = path.relative_to(_PACKAGE).as_posix()
            if relative in exempt:
                continue
            if "from investment_agent.bootstrap import start_cli" not in source:
                offenders.append(relative)
        self.assertEqual(offenders, [])

    def test_script_entrypoints_load_dotenv_too(self):
        """`__main__` 블록이 없는 진입점도 진입점이다.

        Streamlit 앱은 파일을 스크립트로 그냥 실행하므로 `if __name__ == "__main__"`이
        없다. 위 검사가 그것을 건너뛰는 바람에 대시보드가 `.env`를 읽지 않았고, 모든
        화면이 "필수 연결 설정이 없습니다"로만 떴다 — 그 문구는 연결 실패와 구분되지
        않아서 원인을 DB에서 찾게 만든다.

        `launcher.py`는 대상이 아니다. 스스로 조회하지 않고 자식 프로세스를 띄우며,
        그 자식들이 각자 `.env`를 읽는다.
        """
        import json
        import re

        launched: set[str] = set()
        config = _ROOT / ".claude" / "launch.json"
        if config.is_file():
            for entry in json.loads(config.read_text(encoding="utf-8"))["configurations"]:
                launched |= {arg for arg in entry.get("runtimeArgs", []) if arg.endswith(".py")}
        launcher = _ROOT / "scripts" / "dashboard.bat"
        if launcher.is_file():
            launched |= set(re.findall(r"src/[\w/.]+\.py",
                                       launcher.read_text(encoding="utf-8")))
        # 대상을 못 찾으면 이 테스트는 공허하게 통과한다.
        self.assertIn("src/investment_agent/dashboard/app.py", launched)

        offenders = [
            name for name in sorted(launched)
            if (_ROOT / name).is_file()
            and "from investment_agent.bootstrap import start_cli"
            not in (_ROOT / name).read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])

if __name__ == "__main__":
    unittest.main()
