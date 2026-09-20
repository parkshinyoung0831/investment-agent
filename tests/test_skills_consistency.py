"""AI 에이전트 스킬(.claude, .codex, .agents) 일관성 및 무결성 회귀 테스트.

이 저장소는 복수의 AI 도구 환경을 지원한다:
- `.claude/skills/`: Claude Code 전용
- `.codex/skills/`: OpenAI Codex 전용
- `.agents/skills/`: Google Antigravity / Gemini CLI 전용

각 도구는 자신의 전용 디스커버리 경로에서 스킬을 자동 로드하므로 세 경로 모두
필요하다. 이 테스트는 공통 참조 문서(references)와 버전 파일이 서로 drift되지 않고
각 플랫폼별 문법 차이(Codex spawn_agent vs Claude/Antigravity Agent tool)가
의도된 대로 유지되는지 검증한다.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAUDE_SKILL_DIR = ROOT / ".claude" / "skills" / "graphify"
CODEX_SKILL_DIR = ROOT / ".codex" / "skills" / "graphify"
AGENTS_SKILL_DIR = ROOT / ".agents" / "skills" / "graphify"

SKILL_DIRS = {
    "claude": CLAUDE_SKILL_DIR,
    "codex": CODEX_SKILL_DIR,
    "agents": AGENTS_SKILL_DIR,
}


class SkillsConsistencyTest(unittest.TestCase):
    def test_all_agent_skill_directories_exist(self) -> None:
        """세 플랫폼 디스커버리 경로가 모두 파일시스템에 실재해야 한다."""
        for name, path in SKILL_DIRS.items():
            with self.subTest(platform=name):
                self.assertTrue(path.is_dir(), f"{path} 디렉터리가 없습니다")
                self.assertTrue((path / "SKILL.md").is_file(), f"{path}/SKILL.md 가 없습니다")
                self.assertTrue((path / ".graphify_version").is_file(), f"{path}/.graphify_version 이 없습니다")

    def test_skill_versions_are_identical(self) -> None:
        """세 플랫폼의 스킬 버전이 일치해야 한다."""
        versions = {
            name: (path / ".graphify_version").read_text(encoding="utf-8").strip()
            for name, path in SKILL_DIRS.items()
        }
        self.assertEqual(len(set(versions.values())), 1, f"스킬 버전 불일치: {versions}")

    def test_common_reference_documents_are_synchronized(self) -> None:
        """references/*.md 파일들의 내용이 세 플랫폼 간에 drift 없이 동기화되어 있어야 한다."""
        claude_refs = {p.name: p for p in (CLAUDE_SKILL_DIR / "references").glob("*.md")}
        agents_refs = {p.name: p for p in (AGENTS_SKILL_DIR / "references").glob("*.md")}
        codex_refs = {p.name: p for p in (CODEX_SKILL_DIR / "references").glob("*.md")}

        # 파일 목록 일치 확인
        self.assertEqual(set(claude_refs.keys()), set(agents_refs.keys()))
        self.assertEqual(set(claude_refs.keys()), set(codex_refs.keys()))

        # Claude와 Agents는 100% 동일해야 함
        for name, path in claude_refs.items():
            with self.subTest(file=name, check="claude_vs_agents"):
                self.assertEqual(
                    path.read_text(encoding="utf-8"),
                    agents_refs[name].read_text(encoding="utf-8"),
                    f"references/{name} 내용 불일치 (claude vs agents)",
                )

        # Codex와 Claude의 플랫폼 독립적인 references(add-watch, exports, github-and-merge, hooks, query, transcribe, update) 일치
        common_identical = {"add-watch.md", "exports.md", "github-and-merge.md", "hooks.md", "query.md", "transcribe.md", "update.md"}
        for name in common_identical:
            with self.subTest(file=name, check="claude_vs_codex"):
                self.assertEqual(
                    claude_refs[name].read_text(encoding="utf-8"),
                    codex_refs[name].read_text(encoding="utf-8"),
                    f"references/{name} 내용 불일치 (claude vs codex)",
                )

    def test_platform_specific_instructions_are_preserved(self) -> None:
        """각 플랫폼별 특화 subagent 디스패치 문법이 올바르게 보존되어야 한다."""
        codex_skill = (CODEX_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        claude_skill = (CLAUDE_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        agents_skill = (AGENTS_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

        # Codex는 spawn_agent / wait_agent 사용
        self.assertIn("spawn_agent", codex_skill)
        self.assertIn("wait_agent", codex_skill)

        # Claude 및 Agents는 Agent tool 및 general-purpose subagent_type 사용
        self.assertIn('subagent_type="general-purpose"', claude_skill)
        self.assertIn('subagent_type="general-purpose"', agents_skill)


if __name__ == "__main__":
    unittest.main()
