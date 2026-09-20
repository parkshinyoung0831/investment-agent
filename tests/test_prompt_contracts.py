"""외부 GPT용 질의 템플릿(prompts/*.md)의 DB 계약 회귀 테스트.

`prompts/`는 코드가 아니라 외부 GPT에 주입하는 템플릿이므로 import 오류나 런타임
예외가 발생하지 않는다. 따라서 테이블명이나 스키마명이 변경되었을 때 프롬프트가
조용히 깨지는 것을 방지하기 위해 이 테스트가 정적으로 선언과 일치하는지 검증한다.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = ROOT / "prompts"

_SCHEMAS = (
    "universe|market|fundamentals|macro|institutional"
    "|notifications|reporting|trading|execution|research|holdings|intelligence"
)
_REFERENCE = re.compile(rf"\b({_SCHEMAS})\.([a-z_][a-z_0-9]*)\b")
_DDL = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|MATERIALIZED\s+VIEW)"
    r"\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_0-9.]+)",
    re.IGNORECASE,
)

_FILE_SUFFIXES = frozenset({"py", "sql", "md", "toml", "json", "duckdb", "sqlite3", "yml", "yaml"})


def _declared_relations() -> set[str]:
    names: set[str] = set()
    for sql in sorted((ROOT / "db").rglob("*.sql")):
        for match in _DDL.finditer(sql.read_text(encoding="utf-8")):
            names.add(match.group(1).lower())
    from investment_agent.reporting.readers.financial import VIEWS

    names.update(f"reporting.{view}" for view in VIEWS)
    return names


class PromptContractsTest(unittest.TestCase):
    def test_prompt_files_exist(self) -> None:
        files = list(PROMPTS_DIR.glob("*.md"))
        self.assertGreaterEqual(len(files), 2)
        names = {f.name for f in files}
        self.assertIn("stock_analysis.md", names)
        self.assertIn("etf_analysis.md", names)

    def test_all_table_references_in_prompts_are_declared(self) -> None:
        """프롬프트에 하드코딩된 schema.table 이름이 실제 DDL에 존재해야 한다."""
        declared = _declared_relations()
        offenders: list[str] = []

        for prompt_file in sorted(PROMPTS_DIR.glob("*.md")):
            text = prompt_file.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), 1):
                for match in _REFERENCE.finditer(line):
                    schema, table = match.group(1), match.group(2)
                    if table in _FILE_SUFFIXES:
                        continue
                    # schema.table.column 형태는 컬럼 참조이므로 스킵
                    if line[match.end():match.end() + 1] == ".":
                        continue
                    full_name = f"{schema}.{table}".lower()
                    if full_name not in declared:
                        offenders.append(
                            f"{prompt_file.name}:{line_no} '{full_name}' is not a declared relation"
                        )

        self.assertEqual([], offenders, "프롬프트에 선언되지 않은 테이블/뷰 참조가 있습니다")

    def test_prompts_do_not_reference_retired_schemas_or_tables(self) -> None:
        """폐기된 옛 DB 객체나 로컬 저장소로 이전된 이름이 Supabase 프롬프트에 남아 있으면 안 된다."""
        retired_patterns = [
            r"\bai_investor\b",
            r"\btrading\.[a-z_]+",
            r"\bexecution\.[a-z_]+",
            r"\boperations\.[a-z_]+",
            r"\btech_indicators\.[a-z_]+",
        ]
        offenders: list[str] = []
        for prompt_file in sorted(PROMPTS_DIR.glob("*.md")):
            text = prompt_file.read_text(encoding="utf-8")
            for pat in retired_patterns:
                for match in re.finditer(pat, text):
                    offenders.append(f"{prompt_file.name}: found retired pattern '{match.group(0)}'")
        self.assertEqual([], offenders, "프롬프트에 폐기된 스키마/테이블 패턴이 포함되어 있습니다")


if __name__ == "__main__":

    unittest.main()
