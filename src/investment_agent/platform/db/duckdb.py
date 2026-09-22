"""로컬 DuckDB 파일을 여는 공통 기술 경계.

## 도메인 이름을 두지 않는다

어떤 표가 있는지는 `db/duckdb/<name>/v1/*.sql`이 소유한다. 이 모듈은 "파일을 열고
선언을 적용한다"까지만 안다. 표 이름을 여기에 적으면 선언과 코드 두 곳이 진실을
주장하게 되고, 둘이 어긋나는 것은 예외 없이 조용히 일어난다.

## 왜 읽기 전용을 따로 두는가

DuckDB는 파일당 쓰기 프로세스가 하나다. 화면이 쓰기 모드로 열고 있으면 수집 잡이
그 파일을 열지 못해 죽는다. 그래서 읽는 쪽은 `read_only=True` 외의 경로를 갖지 않는다.

## 왜 여는 순간을 기다리는가

DuckDB는 다른 프로세스가 파일을 잡고 있으면 기다리지 않고 즉시 IOException을 낸다.
하네스는 feature 적재·ML 후보·System Portfolio를 서로 다른 프로세스로 동시에 돌리므로, 한쪽이
짧게 쓰는 순간 다른 쪽이 34분짜리 적재를 통째로 잃는다. 열기만 제한 시간 동안 재시도한다.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path
from contextlib import contextmanager
from threading import RLock
from typing import Any, Callable

from investment_agent.platform.logging import get_logger

log = get_logger(__name__)
_WRITER_LOCKS: dict[str, RLock] = {}
# 이 프로세스가 이미 선언을 적용한 (파일 신원, 선언 내용). 연결마다 CREATE ×10을 다시 돌리면
# 저장 한 건이 0.25초라 백필 루프가 분 단위로 느려진다(실측 242ms 중 DDL 약 140ms).
_PREPARED: set[tuple[str, int, int, str]] = set()
# 다른 프로세스의 짧은 쓰기 창을 넘길 만큼. 넘으면 잠금이 아니라 장애로 보고 올린다.
DEFAULT_OPEN_TIMEOUT_SECONDS = 180.0
_OPEN_RETRY_SECONDS = 1.0


def _open_with_retry(
    open_file: Callable[[], Any],
    *,
    target: Path,
    timeout_seconds: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> Any:
    """파일 잠금으로 여는 데 실패하면 제한 시간 안에서 다시 연다. 다른 오류는 바로 올린다."""
    import duckdb

    limit = timeout_seconds if timeout_seconds is not None else float(
        os.environ.get("DUCKDB_OPEN_TIMEOUT_SEC") or DEFAULT_OPEN_TIMEOUT_SECONDS
    )
    deadline = monotonic() + max(0.0, limit)
    attempts = 0
    while True:
        try:
            return open_file()
        except duckdb.IOException as exc:
            # 잠금 메시지는 OS 언어로 번역돼 문구로 가를 수 없다. 여는 단계의 IOException만 재시도한다.
            # 단 "유효한 DuckDB 파일이 아님"은 **DuckDB 자신이 만드는 영어 문구**라 번역되지 않고,
            # 기다려도 풀리지 않는다. 그것까지 재시도하면 깨진 artifact 하나에 3분을 태우고 죽는다.
            if _is_permanent_open_failure(exc):
                raise
            attempts += 1
            if monotonic() >= deadline:
                raise
            if attempts == 1:
                log.warning("DuckDB file is busy; waiting file=%s", target.name)
            sleep(_OPEN_RETRY_SECONDS)


def _is_permanent_open_failure(error: Exception) -> bool:
    """기다려도 풀리지 않는 열기 실패인가. 잠금 경합과 구분한다."""
    return "not a valid duckdb database" in str(error).lower()


class DuckDBStoreError(RuntimeError):
    """DuckDB 파일을 열거나 선언을 적용하지 못했다."""


def ddl_statements(ddl_dir: Path | str) -> tuple[str, ...]:
    """선언 파일을 이름 순서대로 읽어 실행할 문장 목록을 만든다.

    파일 이름의 숫자 접두어가 곧 적용 순서다. 순서를 코드가 따로 들고 있으면
    파일을 추가할 때 한쪽만 고쳐 조용히 어긋난다.

    문장 분리는 세미콜론으로 한다 — 그래서 선언 파일은 **문자열 리터럴 안에
    세미콜론을 두지 않는다**.
    """
    directory = Path(ddl_dir)
    if not directory.is_dir():
        raise DuckDBStoreError(f"DDL directory is missing: {directory.as_posix()}")
    statements: list[str] = []
    for path in sorted(directory.glob("*.sql")):
        for chunk in path.read_text(encoding="utf-8").split(";"):
            text = chunk.strip()
            if text:
                statements.append(text)
    if not statements:
        raise DuckDBStoreError(f"DDL directory has no statements: {directory.as_posix()}")
    return tuple(statements)


def connect(
    path: Path | str,
    *,
    ddl_dir: Path | str | None = None,
    read_only: bool = False,
) -> Any:
    """DuckDB 파일을 연다. 읽기 전용 연결은 파일을 만들지도, 선언을 적용하지도 않는다."""
    import duckdb

    target = Path(path)
    if read_only:
        if not target.is_file():
            raise DuckDBStoreError(f"DuckDB file is not available: {target.as_posix()}")
        return _open_with_retry(lambda: duckdb.connect(str(target), read_only=True), target=target)
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = _open_with_retry(lambda: duckdb.connect(str(target)), target=target)
    try:
        if ddl_dir is not None:
            for statement in ddl_statements(ddl_dir):
                connection.execute(statement)
    except BaseException:
        connection.close()
        raise
    return connection


_SQL_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)


def _without_sql_comments(statement: str) -> str:
    """컬럼 파싱 전에 주석을 지운다. 문자열 리터럴 안의 `--`는 이 선언들에 없다."""
    return _SQL_COMMENT.sub(" ", statement)


_COLUMN_DECLARATION = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)",
    re.IGNORECASE | re.DOTALL,
)


def _declared_columns(statements: tuple[str, ...]) -> dict[str, set[str]]:
    """선언이 만들려는 표마다 최상위 컬럼 이름을 모은다.

    괄호 깊이 1의 첫 토큰만 본다 — `CHECK(...)`·`PRIMARY KEY(...)` 안의 이름을 컬럼으로
    세면 실재하지 않는 컬럼을 요구하게 된다. 타입·제약은 보지 않는다. 여기서 잡으려는 것은
    **표가 이미 있어 CREATE가 통째로 건너뛰어진 경우의 컬럼 부재**이지 타입 변경이 아니다.

    주석을 먼저 지운다. 이 저장소의 선언은 컬럼 사이에 한국어 주석을 둔다 —
    지우지 않으면 주석의 낱말이 컬럼으로 잡혀 있지도 않은 컬럼을 요구하게 된다.
    """
    result: dict[str, set[str]] = {}
    for statement in statements:
        match = _COLUMN_DECLARATION.search(_without_sql_comments(statement))
        if not match:
            continue
        table, body = match.group(1).lower(), match.group(2)
        columns: set[str] = set()
        depth, token, expecting_name = 1, "", True
        for character in body:
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    break
            if depth == 1 and character == ",":
                expecting_name = True
                token = ""
                continue
            if depth == 1 and expecting_name:
                if character.isalnum() or character == "_":
                    token += character
                elif token:
                    if token.upper() not in {"PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "CONSTRAINT"}:
                        columns.add(token.lower())
                    expecting_name = False
                    token = ""
        if token and token.upper() not in {"PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "CONSTRAINT"}:
            columns.add(token.lower())
        if columns:
            result.setdefault(table, set()).update(columns)
    return result


def _assert_no_column_drift(connection: Any, statements: tuple[str, ...], *, target: Path) -> None:
    """이미 있는 표가 현재 선언의 컬럼을 모두 갖고 있는가.

    `CREATE TABLE IF NOT EXISTS`는 표가 있으면 통째로 건너뛴다. 그래서 캐시에서 복원한 옛
    artifact는 새 컬럼 없이 살아남고, 한참 뒤 엉뚱한 INSERT가 Binder Error로 죽는다.
    그 지점에서는 원인이 "옛 artifact"라는 것이 보이지 않으므로 여기서 먼저 말한다.

    **선언과 `after_ddl` 이관이 모두 끝난 뒤에 부른다.** 이관이 옮길 옛 표를 드리프트로
    신고하면 정상적인 이관 경로가 막힌다.

    자동으로 고치지 않는다 — 컬럼 추가는 기본값·제약을 알아야 하고, 파일을 지우는 것은
    데이터 손실이다. 무엇이 어긋났는지와 무엇을 하면 되는지만 정확히 알린다.
    """
    existing = {
        str(row[0]).lower()
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
        ).fetchall()
    }
    drift: list[str] = []
    for table, declared in sorted(_declared_columns(statements).items()):
        if table not in existing:
            continue  # 없는 표는 선언이 만든다 — 드리프트가 아니다
        present = {
            str(row[0]).lower()
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND lower(table_name) = ?",
                [table],
            ).fetchall()
        }
        missing = sorted(declared - present)
        if missing:
            drift.append(f"{table}: {', '.join(missing)}")
    if drift:
        raise DuckDBStoreError(
            f"restored DuckDB artifact predates the current declarations ({target.name}); "
            f"missing columns -> {'; '.join(drift)}. "
            "Rebuild the store from source instead of reusing this cached artifact."
        )


def _prepared_key(target: Path, statements: tuple[str, ...]) -> tuple[str, int, int, str] | None:
    """파일이 아직 없으면 None — 새로 만든 파일에는 반드시 선언을 적용한다.

    파일 신원(dev·inode)을 키에 넣어, 지우고 같은 경로에 다시 만든 파일이 "이미 적용됨"으로
    오인되지 않게 한다. 선언 내용이 바뀌면 키가 달라져 다시 적용된다.
    """
    try:
        stat = target.stat()
    except FileNotFoundError:
        return None
    digest = hashlib.sha256(";".join(statements).encode("utf-8")).hexdigest()
    return (str(target).casefold(), stat.st_dev, stat.st_ino, digest)


@contextmanager
def transactional_connection(
    path: Path | str,
    *,
    ddl_dir: Path | str | None = None,
    after_ddl: Callable[[Any], None] | None = None,
):
    """한 프로세스의 쓰기를 직렬화하고 DDL·읽기·쓰기를 함께 commit한다.

    선언은 프로세스당·파일당 한 번만 적용한다. `after_ddl`(예: 옛 스키마 이관)은 선언을
    적용할 때만 같은 트랜잭션에서 실행된다.
    """
    target = Path(path).resolve()
    lock = _WRITER_LOCKS.setdefault(str(target).casefold(), RLock())
    with lock:
        statements = ddl_statements(ddl_dir) if ddl_dir is not None else ()
        already_prepared = _prepared_key(target, statements) in _PREPARED if statements else True
        connection = connect(target)
        try:
            connection.execute("BEGIN TRANSACTION")
            if not already_prepared:
                for statement in statements:
                    connection.execute(statement)
                if after_ddl is not None:
                    after_ddl(connection)
                # 선언과 이관이 끝난 **뒤에** 본다. 앞에서 보면 `after_ddl`이 옮길 옛 표를
                # 드리프트로 오인한다(예: strategy_allocations의 JSON→관계형 이관).
                # 여기까지 와서도 없는 컬럼은 어떤 이관도 책임지지 않는 진짜 드리프트다.
                _assert_no_column_drift(connection, statements, target=target)
            yield connection
            connection.execute("COMMIT")
            if not already_prepared and statements:
                key = _prepared_key(target, statements)
                if key is not None:
                    _PREPARED.add(key)
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()


__all__ = ["DuckDBStoreError", "connect", "ddl_statements"]
