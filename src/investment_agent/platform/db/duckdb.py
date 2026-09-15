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

import os
import time
from pathlib import Path
from contextlib import contextmanager
from threading import RLock
from typing import Any, Callable

from investment_agent.platform.logging import get_logger

log = get_logger(__name__)
_WRITER_LOCKS: dict[str, RLock] = {}
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
        except duckdb.IOException:
            # 잠금 메시지는 OS 언어로 번역돼 문구로 가를 수 없다. 여는 단계의 IOException만 재시도한다.
            attempts += 1
            if monotonic() >= deadline:
                raise
            if attempts == 1:
                log.warning("DuckDB file is busy; waiting file=%s", target.name)
            sleep(_OPEN_RETRY_SECONDS)


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
