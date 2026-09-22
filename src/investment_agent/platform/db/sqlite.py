"""로컬 실행 원장의 SQLite 연결 경계.

실제 주문·승인·알림 중복 방지는 네트워크 DB가 아니라 실행 컴퓨터의 단일 파일에
기록한다. WAL은 독자를 막지 않고, FULL 동기화와 foreign key는 주문 원장의 내구성과
관계를 우선한다.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from investment_agent.platform.storage_paths import (
    RUNTIME_DATABASE_PATH_ENV,
    repository_root,
    runtime_database_path,
)

RUNTIME_DB_PATH_ENV = RUNTIME_DATABASE_PATH_ENV
DDL_DIR = Path("db/sqlite/runtime/v1")
_PROJECT_ROOT = repository_root()


def _declaration_fingerprint() -> int:
    """현재 선언 파일들의 지문. `PRAGMA user_version`에 들어가므로 32비트 부호 있는 정수다.

    파일 mtime이 아니라 **내용**으로 만든다. git checkout이 mtime만 바꿔도 스키마를
    다시 적용하는 것은 낭비이고, 내용이 같으면 적용할 것이 없다.
    """
    digest = hashlib.sha256()
    for path in sorted((_PROJECT_ROOT / DDL_DIR).glob("*.sql")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    # user_version은 32비트다. 0은 "적용된 적 없음"으로 남겨 둔다.
    return int.from_bytes(digest.digest()[:4], "big") & 0x7FFFFFFF or 1


def _schema_is_current(connection: sqlite3.Connection, fingerprint: int) -> bool:
    """이 DB가 현재 선언으로 만들어졌는가.

    **진실을 파일시스템이 아니라 DB가 갖는다.** 전에는 `(경로, st_dev, st_ino, 선언 지문)`을
    캐시 키로 썼는데, 그러면 세 가지를 못 본다 —
    파일을 제자리에서 비운 경우(inode 그대로), 삭제 후 OS가 inode를 재사용한 경우,
    그리고 다른 프로세스가 만든 DB. 어느 쪽이든 **빈 DB를 스키마가 있는 것으로 착각한다.**
    """
    return int(connection.execute("PRAGMA user_version").fetchone()[0]) == fingerprint


class RuntimeMigrationRequired(RuntimeError):
    """기존 주문을 새 원장으로 검증해 옮겨야 한다."""


def default_runtime_database_path() -> Path:
    return runtime_database_path()


def _apply_schema(connection: sqlite3.Connection, fingerprint: int | None = None) -> None:
    """선언을 적용하고, 어느 선언으로 적용했는지를 DB 자신에게 새긴다.

    지문을 남기지 않으면 다음 연결이 그것을 알 방법이 없어 매번 다시 적용하거나
    (느림) 파일시스템 신원에 기대야 한다(틀림).
    """
    connection.execute("BEGIN IMMEDIATE")
    try:
        _migrate_legacy_execution_tables(connection)
        _migrate_legacy_decision_tables(connection)
        for path in sorted((_PROJECT_ROOT / DDL_DIR).glob("*.sql")):
            statement = ""
            for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    connection.execute(statement)
                    statement = ""
        if fingerprint is not None:
            # PRAGMA는 값 바인딩을 받지 않는다. 정수임을 위에서 보장한다.
            connection.execute(f"PRAGMA user_version = {int(fingerprint)}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _migrate_legacy_decision_tables(connection: sqlite3.Connection) -> None:
    """축약 prototype의 빈 표만 실제 판단 계약으로 교체한다."""
    tables = ("risk_violations", "risk_decisions", "portfolio_weights", "portfolio_proposals", "security_decisions", "decision_runs")
    if not _columns(connection, "decision_runs") or "as_of_at" in _columns(connection, "decision_runs"):
        return
    for table in tables:
        if _columns(connection, table) and connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
            raise RuntimeMigrationRequired("nonempty prototype decision ledger requires verified migration")
    for table in tables:
        if _columns(connection, table):
            connection.execute(f"DROP TABLE {table}")


def _migrate_legacy_execution_tables(connection: sqlite3.Connection) -> None:
    """데이터가 없는 초기 runtime 원장만 새 execution 계약으로 절체한다.

    첫 구현은 integer intent와 축약된 approval을 사용했다. 현재 원장은 manifest와
    승인 소비 상태를 함께 검증하므로 그 행을 억지로 새 의미로 변환하면 주문 증거가
    바뀔 수 있다. 행이 있으면 명시적 이관을 요구하고, 빈 표는 제거한 뒤 다시 만든다.
    빈 표를 rename하면 SQLite의 전역 index 이름이 남아 새 원장 index 생성을 조용히
    막으므로 보존하지 않는다.
    """
    legacy_tables = (
        "legacy_v0_fills", "legacy_v0_orders", "legacy_v0_order_events",
        "legacy_v0_order_attempts", "legacy_v0_approvals",
        "legacy_v0_reconciliation_runs", "legacy_v0_intents",
    )
    for archived in legacy_tables:
        if _columns(connection, archived) and connection.execute(f"SELECT 1 FROM {archived} LIMIT 1").fetchone():
            raise RuntimeMigrationRequired("archived execution ledger requires verified migration")
    for archived in legacy_tables:
        if _columns(connection, archived):
            connection.execute(f"DROP TABLE {archived}")
    if not _columns(connection, "intents") or "risk_decision_id" in _columns(connection, "intents"):
        return
    # 주문이 있었던 원장을 빈 새 원장처럼 열면 대사와 중복 주문 차단이 사라진다.
    # 자동 변환은 데이터가 없는 초기 설치만 허용한다.
    for table in ("intents", "approvals", "order_attempts", "order_events", "orders", "fills"):
        if _columns(connection, table) and connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
            raise RuntimeMigrationRequired("nonempty legacy execution ledger requires verified migration")
    for table in (
        "fills", "orders", "order_events", "order_attempts", "approvals",
        "reconciliation_runs", "intents",
    ):
        if _columns(connection, table):
            connection.execute(f"DROP TABLE {table}")


@contextmanager
def runtime_connection(
    path: Path | str | None = None, *, read_only: bool = False
) -> Iterator[sqlite3.Connection]:
    """로컬 runtime DB를 열고 필요한 경우 새 스키마를 만든다."""
    database_path = Path(path) if path is not None else default_runtime_database_path()
    if read_only:
        connection = sqlite3.connect(
            f"{database_path.resolve().as_uri()}?mode=ro", uri=True, timeout=5.0
        )
    else:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database_path, timeout=5.0)
    try:
        connection.create_function("regexp", 2, lambda pattern, value: int(re.search(pattern, str(value or "")) is not None), deterministic=True)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        if not read_only:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            fingerprint = _declaration_fingerprint()
            if not _schema_is_current(connection, fingerprint):
                # 이관이 거절되면 예외가 나므로 지문이 새겨지지 않고, 다음 연결이 다시 시도한다.
                _apply_schema(connection, fingerprint)
            connection.execute("BEGIN IMMEDIATE")
        yield connection
        if not read_only:
            connection.commit()
    except Exception:
        if not read_only:
            connection.rollback()
        raise
    finally:
        connection.close()


__all__ = [
    "DDL_DIR", "RUNTIME_DB_PATH_ENV",
    "RuntimeMigrationRequired", "default_runtime_database_path", "runtime_connection",
]
