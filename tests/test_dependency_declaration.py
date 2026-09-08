"""의존성을 선언하는 자리는 `pyproject.toml` 하나다.

전에는 `requirements/*.txt` 31개와 루트 `requirements.txt`가 같은 것을 한 번 더
주장했다. 설치는 이미 `uv sync --group X`로 옮겨졌는데 파일만 남아 있었고, 그래서
선택 의존성이 없을 때 뜨는 안내 11곳이 **이제 없는 파일을 설치하라고 말했다** —
사람이 그대로 따라 하면 아무 일도 일어나지 않는다.

여기서 두 가지를 지킨다.

* 옛 선언 파일이 돌아오지 않는다.
* 코드가 말하는 group 이름이 실제로 있는 group이다. 오타 난 안내는 없는 파일
  이름만큼이나 쓸모없는데, 그건 그 의존성이 빠진 사람에게만 보인다.
"""
from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "investment_agent"

_GROUP_HINT = re.compile(r"uv sync --group ([a-z_]+)")


def _declared_groups() -> set[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return set(data["dependency-groups"])


class DependencyDeclarationTest(unittest.TestCase):
    def test_requirements_files_do_not_come_back(self) -> None:
        found = sorted(
            path.relative_to(ROOT).as_posix()
            for path in ROOT.glob("requirements*")
        ) + sorted(
            path.relative_to(ROOT).as_posix()
            for path in ROOT.glob("requirements/*.txt")
        )
        self.assertEqual([], found, "의존성 선언은 pyproject.toml 하나가 소유한다")

    def test_every_install_hint_names_a_real_group(self) -> None:
        groups = _declared_groups()
        offenders: list[str] = []
        for path in sorted(PACKAGE.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for name in _GROUP_HINT.findall(path.read_text(encoding="utf-8")):
                if name not in groups:
                    offenders.append(f"{path.relative_to(ROOT).as_posix()} -> {name}")
        self.assertEqual([], sorted(offenders))

    def test_optional_dependencies_are_reachable_through_some_group(self) -> None:
        """안내가 가리키는 group이 그 패키지를 실제로 담고 있어야 한다."""
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        groups = data["dependency-groups"]

        def flatten(name: str, seen: set[str] | None = None) -> set[str]:
            seen = seen or set()
            if name in seen:
                return set()
            seen.add(name)
            out: set[str] = set()
            for item in groups[name]:
                if isinstance(item, str):
                    out.add(re.split(r"[\[<>=!; ]", item, 1)[0].lower())
                elif isinstance(item, dict) and item.get("include-group"):
                    out |= flatten(item["include-group"], seen)
            return out

        for group, package in (
            ("research", "lumibot"), ("research", "pyqlib"), ("research", "duckdb"),
            ("ml", "lightgbm"), ("ml", "xgboost"),
            ("rl", "gymnasium"), ("rl", "stable-baselines3"),
            ("portfolio", "cvxpy"),
            ("data", "edgartools"),
        ):
            with self.subTest(group=group, package=package):
                self.assertIn(package, flatten(group))

    def test_the_unpackaged_dependency_keeps_its_pin_in_code(self) -> None:
        """TradingAgents는 git 의존이라 lock에 넣지 않는다 — 그러면 모든 CI가 그
        저장소의 가용성에 묶인다. 대신 검증된 commit을 코드가 들고 있어야 한다."""
        from investment_agent.trading.decision.llm.agents.tradingagents_adapter import (
            TRADINGAGENTS_PIN,
        )

        self.assertIn("git+https://github.com/TauricResearch/TradingAgents.git@", TRADINGAGENTS_PIN)
        self.assertRegex(TRADINGAGENTS_PIN, r"@[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
