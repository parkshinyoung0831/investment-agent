"""기존 로컬 DB를 canonical 디렉터리로 복사하고 내용 일치를 검증한다.

원본은 삭제하거나 이름을 바꾸지 않는다. 대상이 이미 있으면 자동 병합하거나 덮어쓰지
않으며, ``apply``는 명시적인 확인 인자를 요구한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from investment_agent.platform.storage_paths import (
    intelligence_database_path,
    legacy_candidates,
    local_artifact_root,
    research_database_path,
    runtime_database_path,
)

ROOT = Path(__file__).resolve().parents[1]


class LocalStorageConflict(RuntimeError):
    """원본과 대상이 모두 있어 자동으로 어느 쪽도 선택할 수 없다."""


@dataclass(frozen=True)
class MigrationPlan:
    store: str
    engine: str
    source: Path
    target: Path
    action: str
    source_exists: bool
    target_exists: bool
    source_size: int | None
    sidecars: tuple[Path, ...]


@dataclass(frozen=True)
class Verification:
    source: Path
    target: Path
    source_sha256: str
    target_sha256: str
    source_rows: int
    target_rows: int
    table_rows: dict[str, int]


def _rooted(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _sidecars(path: Path, engine: str) -> tuple[Path, ...]:
    suffixes = ("-wal", "-shm", "-journal") if engine == "sqlite" else (".wal",)
    return tuple(candidate for suffix in suffixes if (candidate := Path(f"{path}{suffix}")).exists())


def plan_migrations(root: Path = ROOT) -> tuple[MigrationPlan, ...]:
    """현재 파일 상태만 읽어 세 저장소의 이관 계획을 만든다."""
    root = Path(root)
    targets = {
        "intelligence": ("duckdb", intelligence_database_path()),
        "research": ("duckdb", research_database_path()),
        "runtime": ("sqlite", runtime_database_path()),
    }
    plans: list[MigrationPlan] = []
    for store, (engine, target_path) in targets.items():
        target = _rooted(root, target_path)
        existing_sources = [
            _rooted(root, path)
            for path in legacy_candidates(store)
            if _rooted(root, path).is_file()
        ]
        if len(existing_sources) > 1:
            raise LocalStorageConflict(
                f"{store}: legacy source가 여러 개다: "
                + ", ".join(str(path) for path in existing_sources)
            )
        source = existing_sources[0] if existing_sources else _rooted(
            root, legacy_candidates(store)[0]
        )
        same_path = source.resolve() == target.resolve()
        source_exists = source.is_file()
        target_exists = target.is_file()
        if source_exists and target_exists and not same_path:
            raise LocalStorageConflict(
                f"{store}: legacy와 canonical 파일이 모두 존재한다: {source} / {target}"
            )
        if same_path and source_exists:
            action = "already_canonical"
        elif source_exists:
            action = "copy"
        elif target_exists:
            action = "target_only"
        else:
            action = "missing_source"
        plans.append(
            MigrationPlan(
                store=store,
                engine=engine,
                source=source,
                target=target,
                action=action,
                source_exists=source_exists,
                target_exists=target_exists,
                source_size=source.stat().st_size if source_exists else None,
                sidecars=_sidecars(source, engine) if source_exists else (),
            )
        )
    return tuple(plans)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _quoted_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _sqlite_logical_snapshot(path: Path) -> tuple[str, dict[str, int]]:
    with closing(sqlite3.connect(_sqlite_uri(path), uri=True)) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise RuntimeError(f"SQLite integrity check failed for {path}: {integrity}")
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        rows = {
            table: int(
                connection.execute(
                    f"SELECT count(*) FROM {_quoted_identifier(table)}"
                ).fetchone()[0]
            )
            for table in tables
        }
        logical = "\n".join(connection.iterdump()).encode("utf-8")
    return hashlib.sha256(logical).hexdigest(), rows


def _temporary_target(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    temporary.unlink()
    return temporary


def _publish_without_overwrite(temporary: Path, target: Path) -> None:
    try:
        os.link(temporary, target)
    except FileExistsError as exc:
        raise LocalStorageConflict(f"target appeared during migration: {target}") from exc
    temporary.unlink()


def copy_sqlite_snapshot(source: Path, target: Path) -> Verification:
    source = Path(source)
    target = Path(target)
    if not source.is_file():
        raise FileNotFoundError(source)
    if target.exists():
        raise LocalStorageConflict(f"target already exists: {target}")
    temporary = _temporary_target(target)
    try:
        with closing(
            sqlite3.connect(_sqlite_uri(source), uri=True)
        ) as source_connection:
            with closing(sqlite3.connect(temporary)) as target_connection:
                source_connection.backup(target_connection)
        source_hash, source_tables = _sqlite_logical_snapshot(source)
        target_hash, target_tables = _sqlite_logical_snapshot(temporary)
        if source_tables != target_tables or source_hash != target_hash:
            raise RuntimeError(f"SQLite snapshot verification failed: {source} -> {target}")
        _publish_without_overwrite(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return Verification(
        source=source,
        target=target,
        source_sha256=source_hash,
        target_sha256=target_hash,
        source_rows=sum(source_tables.values()),
        target_rows=sum(target_tables.values()),
        table_rows=source_tables,
    )


def _duckdb_snapshot(path: Path) -> tuple[tuple[tuple[Any, ...], ...], dict[str, int]]:
    import duckdb

    with duckdb.connect(str(path), read_only=True) as connection:
        schema = tuple(
            tuple(row)
            for row in connection.execute(
                """
                SELECT table_schema, table_name, column_name, ordinal_position,
                       data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
                ORDER BY table_schema, table_name, ordinal_position
                """
            ).fetchall()
        )
        tables = connection.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
              AND table_schema NOT IN ('information_schema', 'pg_catalog')
            ORDER BY table_schema, table_name
            """
        ).fetchall()
        rows = {}
        for schema_name, table_name in tables:
            qualified = (
                f"{_quoted_identifier(str(schema_name))}."
                f"{_quoted_identifier(str(table_name))}"
            )
            rows[f"{schema_name}.{table_name}"] = int(
                connection.execute(f"SELECT count(*) FROM {qualified}").fetchone()[0]
            )
    return schema, rows


def copy_duckdb_snapshot(source: Path, target: Path) -> Verification:
    import duckdb

    source = Path(source)
    target = Path(target)
    if not source.is_file():
        raise FileNotFoundError(source)
    if target.exists():
        raise LocalStorageConflict(f"target already exists: {target}")
    temporary = _temporary_target(target)
    try:
        with duckdb.connect(str(source)) as connection:
            connection.execute("CHECKPOINT")
        source_hash = _sha256(source)
        shutil.copy2(source, temporary)
        target_hash = _sha256(temporary)
        source_schema, source_tables = _duckdb_snapshot(source)
        target_schema, target_tables = _duckdb_snapshot(temporary)
        if (
            source_schema != target_schema
            or source_tables != target_tables
            or source_hash != target_hash
        ):
            raise RuntimeError(f"DuckDB snapshot verification failed: {source} -> {target}")
        _publish_without_overwrite(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return Verification(
        source=source,
        target=target,
        source_sha256=source_hash,
        target_sha256=target_hash,
        source_rows=sum(source_tables.values()),
        target_rows=sum(target_tables.values()),
        table_rows=source_tables,
    )


def _plan_dict(plan: MigrationPlan) -> dict[str, Any]:
    data = asdict(plan)
    for key in ("source", "target"):
        data[key] = str(data[key])
    data["sidecars"] = [str(path) for path in plan.sidecars]
    return data


def _verification_dict(result: Verification) -> dict[str, Any]:
    data = asdict(result)
    data["source"] = str(result.source)
    data["target"] = str(result.target)
    return data


def _write_manifest(
    root: Path,
    plans: tuple[MigrationPlan, ...],
    results: list[Verification],
) -> Path:
    directory = _rooted(root, local_artifact_root()) / "storage-migration"
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    target = directory / f"{timestamp}.json"
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "plans": [_plan_dict(plan) for plan in plans],
        "verifications": [_verification_dict(result) for result in results],
    }
    temporary = _temporary_target(target)
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        _publish_without_overwrite(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _print_plan(plans: tuple[MigrationPlan, ...]) -> None:
    for plan in plans:
        sidecars = ",".join(path.name for path in plan.sidecars) or "-"
        size = str(plan.source_size) if plan.source_size is not None else "-"
        print(
            f"{plan.store:12s} {plan.action:17s} engine={plan.engine} "
            f"bytes={size} sidecars={sidecars}\n"
            f"  source={plan.source}\n  target={plan.target}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan", help="파일 상태만 읽고 이관 계획을 출력한다")
    apply_parser = subparsers.add_parser("apply", help="원본을 보존하며 검증된 snapshot을 복사한다")
    apply_parser.add_argument("--confirm-local-storage", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "apply" and not args.confirm_local_storage:
        parser.error("apply에는 --confirm-local-storage가 필요합니다")
    try:
        plans = plan_migrations(ROOT)
    except LocalStorageConflict as exc:
        print(f"CONFLICT: {exc}")
        return 2
    _print_plan(plans)
    if args.command == "plan":
        return 0
    results = []
    for plan in plans:
        if plan.action != "copy":
            continue
        copy = copy_sqlite_snapshot if plan.engine == "sqlite" else copy_duckdb_snapshot
        result = copy(plan.source, plan.target)
        results.append(result)
        print(f"VERIFIED {plan.store}: rows={result.source_rows} sha256={result.source_sha256}")
    manifest = _write_manifest(ROOT, plans, results)
    print(f"manifest={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
