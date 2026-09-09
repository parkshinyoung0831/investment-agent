"""문서가 말하는 것이 저장소에 실제로 있는지 본다.

문서는 코드와 달리 틀려도 아무도 알려주지 않는다. import 오류도, 테스트 실패도 없이
**읽는 사람만 잘못된 곳을 찾아간다.** 실제로 그랬다 — 저장 계층을 Postgres 한 곳에서
Postgres·SQLite·DuckDB 넷으로 나눈 뒤에도 여러 문서가 `notifications.outbox`,
`execution.control_state`처럼 **Supabase에 있는 것처럼** 적고 있었고, 이름이 바뀐
`fundamentals.company_financials`·`macro.observations`도 그대로 남아 있었다.

세 가지를 본다.

1. 상대 링크가 실재하는 파일을 가리키는가.
2. `schema.table` 꼴로 적힌 이름이 `db/**/v1/*.sql` 선언에 있는가.
3. 모든 문서에 H1이 하나 있고, 문서 이름 노릇을 하는가.

**DB에 접속하지 않는다.** 선언 파일만 읽는다.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 외부에서 설치·생성되는 것은 이 저장소가 형식을 정하지 않는다.
VENDORED = ("graphify-out/", ".claude/", ".agents/", ".codex/")

# Postgres 스키마 이름과 같은 이름을 가진 파이썬 패키지가 있다(`data/macro`,
# `research/strategies` …). 문서에서 `macro.releases`처럼 적히면 표가 아니라 모듈이다.
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

# 확장자가 붙었으면 표가 아니라 파일이다(`market.py`, `research.duckdb` …).
# 목록으로 세지 않고 규칙으로 거른다 — 새 확장자가 늘 때마다 예외가 자라지 않게.
_FILE_SUFFIXES = frozenset({"py", "sql", "md", "toml", "json", "duckdb", "sqlite3", "yml", "yaml"})

# 표가 아닌 것. 하나하나가 "왜 표처럼 보이는데 표가 아닌지"를 말한다.
NOT_A_TABLE = frozenset({
    # 파이썬 모듈·패키지 경로
    "macro.releases", "research.features", "research.strategies",
    "notifications.discord_admin", "universe.watchlists", "institutional.managers",
    # 계층 이름(패키지 안의 domain/application)
    "fundamentals.domain", "fundamentals.application",
    # SQL 함수
    "fundamentals.prune_expectation_snapshots", "macro.prune_release_snapshots",
    "execution.append_order_attempt_event",
})

STORAGE_MAP = ROOT / "docs" / "STORAGE_MAP.md"
_MIGRATION_HEADING = "## 옮겨간 이름"


def _removed_relations() -> set[str]:
    """지금은 없는 표 이름. `docs/STORAGE_MAP.md`의 이사표가 소유한다.

    없어진 이름을 문서가 쓰는 것은 **없어졌다는 사실을 적을 때**뿐이다. 그 목록을
    테스트 안에 또 두면 두 곳이 갈라지므로, 사람이 읽는 그 표 하나만 본다.
    """
    text = STORAGE_MAP.read_text(encoding="utf-8")
    section = text.split(_MIGRATION_HEADING, 1)[1].split(chr(10) + "## ", 1)[0]
    removed: set[str] = set()
    for line in section.splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        first_column = line.split("|")[1]
        removed.update(
            match.group(0).lower() for match in _REFERENCE.finditer(first_column))
    return removed


def _markdown_files() -> list[Path]:
    import subprocess

    listed = subprocess.run(
        ["git", "ls-files", "*.md"], capture_output=True, text=True, cwd=ROOT, check=True,
    ).stdout.split()
    return [
        ROOT / name for name in listed
        if not name.startswith(VENDORED)
    ]


def _declared_relations() -> set[str]:
    """실제로 존재하는 이름. 선언 파일과 read model 계약 두 곳에서 모은다.

    `reporting.*`는 SQL 뷰만이 아니다 — 절반은 로컬 SQLite를 읽는 논리 뷰라서
    `db/`에 DDL이 없다. 그 계약은 `ReportingQueries.VIEWS`가 소유하므로 거기서 읽는다.
    """
    names: set[str] = set()
    for sql in sorted((ROOT / "db").rglob("*.sql")):
        for match in _DDL.finditer(sql.read_text(encoding="utf-8")):
            names.add(match.group(1).lower())
    from investment_agent.reporting.readers.financial import VIEWS

    names.update(f"reporting.{view}" for view in VIEWS)
    return names


def _strip_code_fences(text: str) -> list[tuple[int, str]]:
    """```로 감싼 블록은 예시 SQL·출력이라 검사 대상이 아니다."""
    out: list[tuple[int, str]] = []
    fenced = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            out.append((number, line))
    return out


class MarkdownLinkTest(unittest.TestCase):
    def test_there_are_documents_to_check(self) -> None:
        """수집 규칙이 어긋나면 아래 검사가 전부 공허하게 통과한다."""
        self.assertGreaterEqual(len(_markdown_files()), 30)

    def test_every_relative_link_resolves(self) -> None:
        pattern = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
        broken: list[str] = []
        for path in _markdown_files():
            for label, target in pattern.findall(path.read_text(encoding="utf-8")):
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                head = target.split("#", 1)[0]
                if not head:
                    continue
                if not (path.parent / head).resolve().exists():
                    broken.append(
                        f"{path.relative_to(ROOT).as_posix()}: [{label}]({target})")
        self.assertEqual([], broken)


class DeclaredRelationTest(unittest.TestCase):
    """문서가 부르는 표 이름은 선언에 있어야 한다."""

    def test_the_declaration_scan_finds_relations(self) -> None:
        """선언을 못 읽으면 모든 이름이 '없는 표'가 되거나 그 반대가 된다."""
        declared = _declared_relations()
        self.assertIn("universe.entities", declared)
        self.assertIn("notification_outbox", declared)
        self.assertIn("reporting.security_decisions", declared)
        self.assertGreaterEqual(len(declared), 60)

    def test_every_named_relation_is_declared(self) -> None:
        declared = _declared_relations()
        removed = _removed_relations()
        offenders: list[str] = []
        for path in _markdown_files():
            relative = path.relative_to(ROOT).as_posix()
            # 설계 기록은 그때의 이름을 적는 것이 정확하다 — 현재 선언으로 맞추면
            # 무엇을 왜 바꿨는지가 사라진다.
            if relative.startswith("docs/superpowers/specs/"):
                continue
            for number, line in _strip_code_fences(path.read_text(encoding="utf-8")):
                for match in _REFERENCE.finditer(line):
                    name = match.group(0).lower()
                    if match.group(2) in _FILE_SUFFIXES:
                        continue
                    if name in declared or name in NOT_A_TABLE or name in removed:
                        continue
                    # `schema.table.column`은 표가 아니라 컬럼을 가리킨다.
                    if line[match.end():match.end() + 1] == ".":
                        continue
                    offenders.append(f"{relative}:{number} {name}")
        self.assertEqual([], offenders)

    def test_the_exception_list_has_no_dead_entries(self) -> None:
        """쓰이지 않는 예외가 남으면 다음 사람이 그것을 근거로 삼는다."""
        seen: set[str] = set()
        for path in _markdown_files():
            for _, line in _strip_code_fences(path.read_text(encoding="utf-8")):
                for match in _REFERENCE.finditer(line):
                    if match.group(2) not in _FILE_SUFFIXES:
                        seen.add(match.group(0).lower())
        self.assertEqual(set(), NOT_A_TABLE - seen)

    def test_the_migration_table_is_read(self) -> None:
        """이사표를 못 읽으면 옛 이름이 전부 위반으로 잡히거나 그 반대가 된다."""
        removed = _removed_relations()
        self.assertIn("notifications.subscriptions", removed)
        self.assertGreaterEqual(len(removed), 8)

    def test_removed_relations_are_really_gone(self) -> None:
        """되살아난 표가 이사표에 남아 있으면 문서가 그것을 계속 부정한다."""
        self.assertEqual([], sorted(_removed_relations() & _declared_relations()))


class DocumentShapeTest(unittest.TestCase):
    """형식을 하나로 둔다 — 제목 한 줄이 문서의 이름이다."""

    def test_every_document_starts_with_a_single_h1(self) -> None:
        offenders: list[str] = []
        for path in _markdown_files():
            # 코드 블록 안의 `# 주석`은 제목이 아니다.
            lines = _strip_code_fences(path.read_text(encoding="utf-8"))
            headings = [number for number, line in lines if line.startswith("# ")]
            relative = path.relative_to(ROOT).as_posix()
            if len(headings) != 1:
                offenders.append(f"{relative}: H1 {len(headings)}개 (줄 {headings[:5]})")
            elif headings[0] != 1:
                offenders.append(f"{relative}: H1이 {headings[0]}번째 줄에 있다")
        self.assertEqual([], offenders)

    def test_every_title_says_what_the_document_is(self) -> None:
        """제목은 `이름 — 정체` 한 줄이다.

        `# Fundamentals`만 있으면 목록에서 무엇인지 알 수 없다. 이름과 한 줄 정체를
        em dash로 잇는 것이 이 저장소의 문서 형식이다.
        """
        offenders: list[str] = []
        for path in _markdown_files():
            title = path.read_text(encoding="utf-8").splitlines()[0]
            if "—" not in title:
                offenders.append(f"{path.relative_to(ROOT).as_posix()}: {title}")
        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
