"""워크플로가 주고받는 로컬 저장소 경로는 `storage_paths`와 같아야 한다.

로컬 저장소(DuckDB·Parquet)는 Actions 안에서 **artifact로 건네진다** —
`tech_indicators`가 만들고, `strategy_monthly`가 올리고, `notify_strategy`가 받는다.
그 경로가 YAML에 문자열로 박혀 있어서, 저장소 위치를 옮겼을 때 코드만 따라오고
워크플로는 옛 자리를 계속 봤다.

실측(2026-09-08): `tech_indicators`가 지표를 다 계산해 놓고
`No files were found with the provided path: artifacts/research/research.duckdb`로
실패했다. 계산은 성공하고 결과만 버려진 것이다. 월간인 나머지 둘은 아직 그 날이
오지 않았을 뿐 같은 상태였다.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from investment_agent.platform.storage_paths import research_database_path, research_root

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

#: artifact를 주고받는 워크플로와 그 경로가 가리켜야 하는 것.
_ARTIFACT_PATHS = {
    "tech_indicators.yml": research_database_path(),
    "strategy_monthly.yml": research_database_path(),
    "notify_strategy.yml": research_root(),
}

_PATH_LINE = re.compile(r"^\s+path:\s*(.+?)\s*$", re.M)
_ENV_REF = re.compile(r"^\$\{\{\s*env\.([A-Z0-9_]+)\s*\}\}$")


def _job_env(document: dict) -> dict[str, str]:
    """job에 선언된 env. 여러 단계가 같은 자리를 보게 하는 정상적인 방법이다."""
    found: dict[str, str] = {}
    for job in (document.get("jobs") or {}).values():
        for key, value in (job.get("env") or {}).items():
            if isinstance(value, str):
                found[str(key)] = value
    return found


def _resolved_research_paths(name: str) -> list[str]:
    import yaml

    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    env = _job_env(yaml.safe_load(text) or {})
    out = []
    for value in _PATH_LINE.findall(text):
        reference = _ENV_REF.match(value)
        resolved = env.get(reference.group(1), value) if reference else value
        if "research" in resolved:
            out.append(resolved)
    return out


class WorkflowArtifactPathsFollowStorageTest(unittest.TestCase):
    def test_every_research_artifact_path_matches_storage_paths(self) -> None:
        offenders = []
        for name, expected in sorted(_ARTIFACT_PATHS.items()):
            found = _resolved_research_paths(name)
            wanted = expected.as_posix()
            offenders += [f"{name}: {value} != {wanted}" for value in found if value != wanted]
            if not found:
                offenders.append(f"{name}: research artifact path 없음")
        self.assertEqual([], offenders)

    def test_no_workflow_still_names_the_previous_location(self) -> None:
        """옛 자리를 가리키는 줄이 하나라도 남으면 그 워크플로가 조용히 빈손이 된다."""
        stale = [
            f"{path.name}:{lineno}"
            for path in sorted(WORKFLOWS.glob("*.yml"))
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if "artifacts/research" in line
        ]
        self.assertEqual([], stale)

    def test_the_scan_reads_the_real_files(self) -> None:
        """대상을 못 찾으면 위 검사는 공허하게 통과한다."""
        self.assertTrue((WORKFLOWS / "tech_indicators.yml").is_file())
        self.assertIn("research", research_database_path().as_posix())


if __name__ == "__main__":
    unittest.main()
