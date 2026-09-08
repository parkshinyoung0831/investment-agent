"""Intelligence Parquet archive와 DuckDB catalog의 유일한 경계.

본문은 날짜 파티션 Parquet에만 저장한다. DuckDB는 고유성·보존·언급 연결용 작은
index와 Parquet view를 소유한다. 따라서 90일 정리는 큰 table DELETE가 아니라 오래된
partition directory 제거로 끝나며, Dashboard는 계속 DuckDB의 읽기 전용 view만 읽는다.
"""
from __future__ import annotations

import json
import os
import uuid
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from investment_agent.intelligence.infrastructure import db
from investment_agent.intelligence.domain.models import (
    CollectionRun, EntityMention, NewsArticleRecord, PruneResult,
    SocialPostRecord, StoreResult,
)
from investment_agent.platform.db import duckdb as duckdb_store
from investment_agent.platform.storage_paths import repository_root
from investment_agent.platform.db.sqlite import runtime_connection, default_runtime_database_path, RUNTIME_DB_PATH_ENV


class IntelligenceRepository:
    """본문 archive와 작은 Intelligence catalog를 함께 관리한다."""

    def __init__(self, path: Path | str | None = None, *, read_only: bool = False, runtime_path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else db.default_database_path()
        self.read_only = read_only
        self.archive_root = db.parquet_root(self.path)
        self.runtime_path = Path(runtime_path) if runtime_path is not None else (
            default_runtime_database_path() if path is None or self.path == db.DEFAULT_DATABASE_PATH or os.environ.get(RUNTIME_DB_PATH_ENV)
            else self.path.parent / f"{self.path.stem}.runtime.sqlite3"
        )

    @contextmanager
    def _connect(self) -> Any:
        if self.read_only:
            with duckdb_store.connect(self.path, read_only=True) as connection:
                yield connection
            return
        ddl = repository_root() / db.DDL_DIR
        with duckdb_store.transactional_connection(self.path, ddl_dir=ddl) as connection:
            self._migrate_legacy_content_tables(connection)
            self._refresh_content_views(connection)
            yield connection

    def _guard_write(self) -> None:
        if self.read_only:
            raise PermissionError("intelligence repository is read-only")

    @staticmethod
    def _rows(connection: Any) -> list[dict[str, Any]]:
        columns = [str(item[0]) for item in (connection.description or ())]
        return [dict(zip(columns, row)) for row in connection.fetchall()]

    @staticmethod
    def _observed_at(value: datetime | None, fallback: datetime) -> datetime:
        return value or fallback

    @staticmethod
    def _partition_date(value: datetime) -> date:
        return value.astimezone(timezone.utc).date()

    def _files(self, connection: Any, domain: str) -> list[Path]:
        return [Path(row[0]) for row in connection.execute("SELECT path FROM content_files WHERE domain=? ORDER BY path", [domain]).fetchall()]

    @staticmethod
    def _parquet_sql(files: Sequence[Path], empty_columns: Sequence[tuple[str, str]]) -> str:
        if not files:
            fields = ", ".join(f"CAST(NULL AS {kind}) AS {name}" for name, kind in empty_columns)
            return f"SELECT {fields} WHERE FALSE"
        paths = ", ".join("'" + path.resolve().as_posix().replace("'", "''") + "'" for path in files)
        fields = ", ".join(f"CAST({name} AS {kind}) AS {name}" for name, kind in empty_columns)
        return f"SELECT {fields} FROM read_parquet([{paths}], union_by_name = true, hive_partitioning = false)"

    def _refresh_content_views(self, connection: Any) -> None:
        """현재 archive 파일 목록을 persistent DuckDB view로 고정한다."""
        news_sql = self._parquet_sql(self._files(connection, "news"), (
            ("article_id", "VARCHAR"), ("provider", "VARCHAR"), ("source_name", "VARCHAR"),
            ("canonical_url", "VARCHAR"), ("url_hash", "VARCHAR"), ("title", "VARCHAR"),
            ("summary", "VARCHAR"), ("content_hash", "VARCHAR"), ("published_at", "TIMESTAMPTZ"),
            ("available_at", "TIMESTAMPTZ"), ("first_seen_at", "TIMESTAMPTZ"), ("collected_at", "TIMESTAMPTZ"),
        ))
        social_sql = self._parquet_sql(self._files(connection, "social"), (
            ("post_id", "VARCHAR"), ("platform", "VARCHAR"), ("channel", "VARCHAR"),
            ("native_id", "VARCHAR"), ("author_hash", "VARCHAR"), ("title", "VARCHAR"),
            ("body", "VARCHAR"), ("permalink", "VARCHAR"), ("score", "INTEGER"),
            ("num_comments", "INTEGER"), ("flair", "VARCHAR"), ("posted_at", "TIMESTAMPTZ"),
            ("available_at", "TIMESTAMPTZ"), ("first_seen_at", "TIMESTAMPTZ"), ("collected_at", "TIMESTAMPTZ"),
            ("content_hash", "VARCHAR"),
        ))
        connection.execute(f"CREATE OR REPLACE VIEW {db.V_NEWS} AS {news_sql}")
        connection.execute(f"CREATE OR REPLACE VIEW {db.V_SOCIAL} AS {social_sql}")

    def _is_legacy_table(self, connection: Any, name: str) -> bool:
        row = connection.execute(
            "SELECT table_type FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = ?", [name]
        ).fetchone()
        return row is not None and str(row[0]).upper() == "BASE TABLE"

    def _migrate_legacy_content_tables(self, connection: Any) -> None:
        """이전 v1 DuckDB 본문 table을 한 번만 Parquet로 옮긴다."""
        if connection.execute("SELECT 1 FROM content_catalog_state WHERE version=1").fetchone():
            return
        # 옛 본문 table의 식별자 컬럼은 종류마다 다르다. 통합 index의 `content_id`가
        # 아니라 그 이름으로 읽어야 한다.
        for domain, legacy, index, id_column, observed_column in (
            ("news", db.V_NEWS, db.T_CONTENT, "article_id", "published_at"),
            ("social", db.V_SOCIAL, db.T_CONTENT, "post_id", "posted_at"),
        ):
            exists = connection.execute("SELECT table_type FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=?", [legacy]).fetchone()
            if not exists:
                continue
            connection.execute(f"SELECT * FROM {legacy}")
            rows = self._rows(connection)
            if rows:
                prepared = []
                for row in rows:
                    observed = self._observed_at(row.get(observed_column), row["first_seen_at"])
                    prepared.append({**row, "_observed_at": observed, "_partition_date": self._partition_date(observed)})
                self._write_parquet(connection, domain, prepared)
                connection.executemany(
                    f"INSERT INTO {index} VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                    [[row[id_column], domain, row.get("url_hash"), row["content_hash"],
                      row["_observed_at"], row["first_seen_at"], row["collected_at"],
                      row["_partition_date"]] for row in prepared],
                )
            if self._is_legacy_table(connection, legacy):
                connection.execute(f"DROP TABLE {legacy}")
        connection.execute("INSERT INTO content_catalog_state VALUES (1)")

    def _write_parquet(self, connection: Any, domain: str, rows: Sequence[dict[str, Any]]) -> None:
        """날짜별 새 part 파일을 ZSTD로 쓴다. 기존 파일은 절대 다시 쓰지 않는다."""
        if not rows:
            return
        import pyarrow as pa
        import pyarrow.parquet as pq

        grouped: dict[date, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[row["_partition_date"]].append({key: value for key, value in row.items() if not key.startswith("_")})
        for partition, items in grouped.items():
            target_dir = self.archive_root / domain / f"date={partition.isoformat()}"
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"part-{uuid.uuid4().hex}.parquet"
            temporary = target.with_suffix(".parquet.tmp")
            # 전부 NULL인 optional 시각도 고정 타입으로 써서 다음 파일과 충돌하지 않는다.
            timestamps = {"published_at", "posted_at", "available_at", "first_seen_at", "collected_at"}
            integers = {"score", "num_comments"}
            schema = pa.schema([(key, pa.timestamp("us", tz="UTC") if key in timestamps else pa.int64() if key in integers else pa.string()) for key in items[0]])
            pq.write_table(pa.Table.from_pylist(items, schema=schema), temporary, compression="zstd")
            with temporary.open("r+b") as stream:
                os.fsync(stream.fileno())
            temporary.replace(target)
            connection.execute("INSERT INTO content_files VALUES (?, ?, ?)", [domain, partition, str(target.resolve())])

    @staticmethod
    def _existing(connection: Any, table: str, column: str, values: Iterable[str]) -> set[str]:
        unique = sorted({value for value in values if value})
        if not unique:
            return set()
        found: set[str] = set()
        for start in range(0, len(unique), 500):
            batch = unique[start:start + 500]
            placeholders = ", ".join("?" for _ in batch)
            rows = connection.execute(f"SELECT {column} FROM {table} WHERE {column} IN ({placeholders})", batch).fetchall()
            found.update(str(row[0]) for row in rows)
        return found

    # ── 쓰기 ────────────────────────────────────────────────────────────
    def store_news(self, records: Sequence[NewsArticleRecord]) -> StoreResult:
        self._guard_write()
        if not records:
            return StoreResult()
        with self._connect() as connection:
            seen_ids = self._existing(connection, db.T_CONTENT, "content_id", (row.article_id for row in records))
            seen_urls = self._existing(connection, db.T_CONTENT, "url_hash", (row.url_hash for row in records))
            seen_content = self._existing(connection, db.T_CONTENT, "content_hash", (row.content_hash for row in records))
            accepted: list[dict[str, Any]] = []
            for row in records:
                if row.article_id in seen_ids or row.url_hash in seen_urls or row.content_hash in seen_content:
                    continue
                observed = self._observed_at(row.published_at, row.first_seen_at)
                accepted.append({
                    "article_id": row.article_id, "provider": row.provider, "source_name": row.source_name,
                    "canonical_url": row.canonical_url, "url_hash": row.url_hash, "title": row.title,
                    "summary": row.summary, "content_hash": row.content_hash, "published_at": row.published_at,
                    "available_at": row.available_at, "first_seen_at": row.first_seen_at,
                    "collected_at": row.collected_at, "_observed_at": observed,
                    "_partition_date": self._partition_date(observed),
                })
                seen_ids.add(row.article_id); seen_urls.add(row.url_hash); seen_content.add(row.content_hash)
            self._write_parquet(connection, "news", accepted)
            if accepted:
                connection.executemany(
                    f"INSERT INTO {db.T_CONTENT} VALUES (?, 'news', ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                    [[row["article_id"], row["url_hash"], row["content_hash"], row["_observed_at"], row["first_seen_at"], row["collected_at"], row["_partition_date"]] for row in accepted],
                )
                self._refresh_content_views(connection)
        return StoreResult(stored=len(accepted), duplicates=len(records) - len(accepted))

    def store_social(self, records: Sequence[SocialPostRecord]) -> StoreResult:
        self._guard_write()
        if not records:
            return StoreResult()
        with self._connect() as connection:
            seen_ids = self._existing(connection, db.T_CONTENT, "content_id", (row.post_id for row in records))
            seen_content = self._existing(connection, db.T_CONTENT, "content_hash", (row.content_hash for row in records))
            accepted: list[dict[str, Any]] = []
            for row in records:
                if row.post_id in seen_ids or row.content_hash in seen_content:
                    continue
                observed = self._observed_at(row.posted_at, row.first_seen_at)
                accepted.append({
                    "post_id": row.post_id, "platform": row.platform, "channel": row.channel,
                    "native_id": row.native_id, "author_hash": row.author_hash, "title": row.title,
                    "body": row.body, "permalink": row.permalink, "score": row.score,
                    "num_comments": row.num_comments, "flair": row.flair, "posted_at": row.posted_at,
                    "available_at": row.available_at, "first_seen_at": row.first_seen_at,
                    "collected_at": row.collected_at, "content_hash": row.content_hash,
                    "_observed_at": observed, "_partition_date": self._partition_date(observed),
                })
                seen_ids.add(row.post_id); seen_content.add(row.content_hash)
            self._write_parquet(connection, "social", accepted)
            if accepted:
                connection.executemany(
                    # 소셜에는 url 축이 없다. NULL로 두면 DuckDB의 UNIQUE가 서로 다른
                    # 값으로 보므로 소셜 행끼리 부딪히지 않는다.
                    f"INSERT INTO {db.T_CONTENT} VALUES (?, 'social', NULL, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                    [[row["post_id"], row["content_hash"], row["_observed_at"], row["first_seen_at"], row["collected_at"], row["_partition_date"]] for row in accepted],
                )
                self._refresh_content_views(connection)
        return StoreResult(stored=len(accepted), duplicates=len(records) - len(accepted))

    def store_mentions(self, mentions: Sequence[EntityMention]) -> int:
        self._guard_write()
        if not mentions:
            return 0
        with self._connect() as connection:
            before = connection.execute(f"SELECT count(*) FROM {db.T_MENTIONS}").fetchone()[0]
            connection.executemany(
                f"INSERT INTO {db.T_MENTIONS} (mention_id, source_kind, source_id, ticker, match_kind, confidence, observed_at, first_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                [[m.mention_id, m.source_kind, m.source_id, m.ticker, m.match_kind, m.confidence, m.observed_at, m.first_seen_at] for m in mentions],
            )
            after = connection.execute(f"SELECT count(*) FROM {db.T_MENTIONS}").fetchone()[0]
        return int(after) - int(before)

    def record_run(self, run: CollectionRun) -> None:
        self._guard_write()
        # runtime job-state는 성공/실패/진행만 표현한다. 수집 도메인의 ``error``는
        # 화면용 detail에 그대로 보존하고 SQLite 상태값은 ``failed``로 정규화한다.
        runtime_status = "failed" if run.status == "error" else run.status
        if runtime_status not in {"ok", "failed", "running"}:
            runtime_status = "failed"
        with runtime_connection(self.runtime_path) as connection:
            connection.execute(
                "INSERT INTO local_job_state (job_name,last_started_at,last_finished_at,last_status,detail) VALUES (?,?,?,?,?) ON CONFLICT(job_name) DO UPDATE SET last_started_at=excluded.last_started_at,last_finished_at=excluded.last_finished_at,last_status=excluded.last_status,detail=excluded.detail",
                (f"intelligence:{run.kind}:{run.domain}", run.started_at.isoformat(), run.finished_at.isoformat() if run.finished_at else None, runtime_status, json.dumps({
                    "run_id": run.run_id, "provider": run.provider, "stored_count": run.stored_count,
                    "duplicate_count": run.duplicate_count, "deleted_count": run.deleted_count,
                    "message": run.message,
                }, ensure_ascii=False, separators=(",", ":"))),
            )

    def _delete_mentions(self, connection: Any, kind: str, source_ids: Sequence[str]) -> int:
        if not source_ids:
            return 0
        deleted = 0
        for start in range(0, len(source_ids), 500):
            batch = list(source_ids[start:start + 500]
            )
            marks = ", ".join("?" for _ in batch)
            deleted += len(connection.execute(f"DELETE FROM {db.T_MENTIONS} WHERE source_kind = ? AND source_id IN ({marks}) RETURNING 1", [kind, *batch]).fetchall())
        return deleted

    def prune(self, *, cutoff: Any) -> PruneResult:
        """정확한 UTC 경계로 목록을 먼저 commit하고 참조가 끝난 파일을 지운다."""
        self._guard_write()
        if not isinstance(cutoff, datetime) or cutoff.tzinfo is None:
            raise ValueError("retention cutoff must include a timezone")
        cutoff = cutoff.astimezone(timezone.utc)
        boundary = cutoff.astimezone(timezone.utc).date()
        obsolete: list[Path] = []
        counts: dict[str, int] = {}
        mentions = 0
        with self._connect() as connection:
            # 두 종류가 한 표를 쓰므로 매 조회를 `content_kind`로 좁힌다. 빠뜨리면
            # 첫 회차가 소셜 행까지 지우고 소셜 언급은 남는다.
            for domain, table, view, identity, observed in (
                ("news", db.T_CONTENT, db.V_NEWS, "content_id", "published_at"),
                ("social", db.T_CONTENT, db.V_SOCIAL, "content_id", "posted_at"),
            ):
                stale = connection.execute(
                    f"SELECT {identity} FROM {table} WHERE content_kind = ? AND observed_at < ?",
                    [domain, cutoff],
                ).fetchall()
                counts[domain] = len(stale)
                if not stale:
                    continue
                old_files = connection.execute("SELECT path FROM content_files WHERE domain=? AND partition_date<=?", [domain, boundary]).fetchall()
                # 경계 날짜의 살아 있는 내용만 새 파일로 보존한다.
                connection.execute(f"SELECT * FROM {view} WHERE coalesce({observed}, first_seen_at)>=? AND CAST(coalesce({observed}, first_seen_at) AT TIME ZONE 'UTC' AS DATE)=?", [cutoff, boundary])
                survivors = [{**row, "_partition_date": boundary} for row in self._rows(connection)]
                connection.execute("DELETE FROM content_files WHERE domain=? AND partition_date<=?", [domain, boundary])
                self._write_parquet(connection, domain, survivors)
                mentions += self._delete_mentions(connection, domain, [str(row[0]) for row in stale])
                connection.execute(f"DELETE FROM {table} WHERE content_kind = ? AND observed_at < ?", [domain, cutoff])
                obsolete.extend(Path(row[0]) for row in old_files)
            self._refresh_content_views(connection)
        # rollback 시 기존 파일은 그대로 남는다. commit 후 삭제 실패도 재시도할 수 있다.
        root = self.archive_root.resolve()
        for path in obsolete:
            target = path.resolve()
            if not target.is_relative_to(root):
                raise ValueError("archive file is outside the configured root")
            target.unlink(missing_ok=True)
            if target.parent.exists() and not any(target.parent.iterdir()):
                target.parent.rmdir()
        return PruneResult(news=counts["news"], social=counts["social"], mentions=mentions)

    # ── 읽기 ────────────────────────────────────────────────────────────
    def freshness(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            connection.execute(f"SELECT * FROM {db.V_FRESHNESS} ORDER BY domain")
            return self._rows(connection)

    def recent_news(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            connection.execute(f"SELECT article_id, provider, source_name, canonical_url, title, summary, published_at, first_seen_at, collected_at FROM {db.V_NEWS} ORDER BY coalesce(published_at, first_seen_at) DESC LIMIT ?", [int(limit)])
            return self._rows(connection)

    def recent_social(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            connection.execute(f"SELECT post_id, platform, channel, title, body, permalink, score, num_comments, flair, posted_at, first_seen_at, collected_at FROM {db.V_SOCIAL} ORDER BY coalesce(posted_at, first_seen_at) DESC LIMIT ?", [int(limit)])
            return self._rows(connection)

    def mention_counts(self, *, since: str, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as connection:
            connection.execute(f"SELECT ticker, sum(mention_count) AS mention_count FROM {db.V_MENTION_DAILY} WHERE observed_date >= ? GROUP BY ticker ORDER BY mention_count DESC, ticker LIMIT ?", [since, int(limit)])
            return self._rows(connection)

    def recent_runs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if not self.runtime_path.is_file():
            return []
        with runtime_connection(self.runtime_path, read_only=True) as connection:
            rows = connection.execute("SELECT job_name,last_started_at,last_finished_at,last_status,detail FROM local_job_state WHERE job_name LIKE 'intelligence:%' ORDER BY last_started_at DESC LIMIT ?", (int(limit),)).fetchall()
        result = []
        for row in rows:
            try:
                detail = json.loads(row[4] or "{}")
            except json.JSONDecodeError:
                detail = {"message": row[4]}
            parts = str(row[0]).split(":", 2)
            result.append({
                "run_id": detail.get("run_id", row[0]), "kind": parts[1], "domain": parts[2],
                "started_at": row[1], "finished_at": row[2], "status": row[3],
                "message": detail.get("message"), "provider": detail.get("provider"),
                "stored_count": int(detail.get("stored_count", 0)),
                "duplicate_count": int(detail.get("duplicate_count", 0)),
                "deleted_count": int(detail.get("deleted_count", 0)),
            })
        return result


__all__ = ["IntelligenceRepository"]
