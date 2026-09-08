"""로컬 DuckDB 파일을 여는 공통 기술 경계.

## 도메인 이름을 두지 않는다

어떤 표가 있는지는 `db/duckdb/<name>/v1/*.sql`이 소유한다. 이 모듈은 "파일을 열고
선언을 적용한다"까지만 안다. 표 이름을 여기에 적으면 선언과 코드 두 곳이 진실을
주장하게 되고, 둘이 어긋나는 것은 예외 없이 조용히 일어난다.

## 왜 읽기 전용을 따로 두는가

DuckDB는 파일당 쓰기 프로세스가 하나다. 화면이 쓰기 모드로 열고 있으면 수집 잡이
그 파일을 열지 못해 죽는다. 그래서 읽는 쪽은 `read_only=True` 외의 경로를 갖지 않는다.
"""
from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager
from threading import RLock
from typing import Any

from investment_agent.platform.logging import get_logger

log = get_logger(__name__)
_WRITER_LOCKS: dict[str, RLock] = {}


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
        return duckdb.connect(str(target), read_only=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(target))
    try:
        if ddl_dir is not None:
            for statement in ddl_statements(ddl_dir):
                connection.execute(statement)
    except BaseException:
        connection.close()
        raise
    return connection


@contextmanager
def transactional_connection(path: Path | str, *, ddl_dir: Path | str | None = None):
    """한 프로세스의 쓰기를 직렬화하고 DDL·읽기·쓰기를 함께 commit한다."""
    target = Path(path).resolve()
    lock = _WRITER_LOCKS.setdefault(str(target).casefold(), RLock())
    with lock:
        connection = connect(target)
        try:
            connection.execute("BEGIN TRANSACTION")
            if ddl_dir is not None:
                for statement in ddl_statements(ddl_dir):
                    connection.execute(statement)
            yield connection
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()


__all__ = ["DuckDBStoreError", "connect", "ddl_statements"]
