"""Research 전용 로컬 DuckDB 저장소.

Research 산출물은 Production Supabase 스키마에 저장하지 않는다. 이 모듈은
재계산 가능한 feature와 전략 배분을 로컬 파일에 보관하고,
대시보드·알림이 같은 파일을 읽을 때 필요한 작은 조회 계약만 제공한다.
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import tempfile
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence
from investment_agent.platform.db import duckdb as duckdb_store
from investment_agent.platform.serialization import canonical_json, normalize_ticker, parse_datetime
from investment_agent.platform.storage_paths import (
    RESEARCH_ROOT_ENV,
    repository_root,
    research_database_path,
)
from investment_agent.research.datasets.contracts import TrainingSample
from investment_agent.research.promotion.gate import (
    EvaluationSummary,
    PromotionDecision,
    aggregate_evaluations,
    approval_confirmation,
)
from investment_agent.research.rl.contracts import FeatureSnapshot, ForwardReturnLabel, normalize_symbols

DEFAULT_RESEARCH_ROOT = Path("data/local/research")
DATABASE_NAME = "research.duckdb"
RESEARCH_DDL_DIR = Path("db/duckdb/research/v1")
_PROJECT_ROOT = repository_root()

T_STRATEGIES = "strategy_runs"
T_ALLOCATION_ROWS = "strategy_allocations"
T_FEATURE_SETS = "feature_sets"
T_DATASET_RUNS = "dataset_runs"
FEATURE_VERSION = "technical_v1"
_DATASET_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_PAYLOAD_FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def default_database_path() -> Path:
    """현재 실행이 사용할 Research DB 경로를 계산한다."""
    return research_database_path()


class ResearchStore:
    """DuckDB 파일을 열어 Research 산출물을 읽고 쓴다."""

    def __init__(self, path: Path | str | None = None, *, read_only: bool = False) -> None:
        self.path = Path(path) if path is not None else default_database_path()
        self.read_only = read_only

    @contextmanager
    def _connect(self) -> Any:
        if self.read_only:
            if not self.path.is_file():
                raise FileNotFoundError("Research snapshot is not available on this host")
            with duckdb_store.connect(self.path, read_only=True) as connection:
                yield connection
            return
        with duckdb_store.transactional_connection(
            self.path,
            ddl_dir=_PROJECT_ROOT / RESEARCH_DDL_DIR,
        ) as connection:
            self._migrate_legacy_strategy_allocations(connection)
            self._migrate_legacy_bulk_tables(connection)
            yield connection

    @staticmethod
    def _columns(connection: Any, table: str) -> set[str]:
        return {str(row[0]) for row in connection.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=?", [table]
        ).fetchall()}

    def _migrate_legacy_strategy_allocations(self, connection: Any) -> None:
        """JSON weight 표를 관계형 run/allocation 표로 한 번 옮긴다."""
        columns = self._columns(connection, T_ALLOCATION_ROWS)
        if "weights" not in columns:
            return
        connection.execute(f"ALTER TABLE {T_ALLOCATION_ROWS} RENAME TO legacy_v1_strategy_allocations")
        connection.execute(
            f"CREATE TABLE IF NOT EXISTS {T_STRATEGIES} (run_id VARCHAR PRIMARY KEY, strategy_id VARCHAR NOT NULL, decision_date DATE NOT NULL, apply_date DATE NOT NULL, mode VARCHAR NOT NULL, signals JSON NOT NULL, UNIQUE(strategy_id, apply_date))"
        )
        connection.execute(
            f"CREATE TABLE {T_ALLOCATION_ROWS} (run_id VARCHAR NOT NULL REFERENCES {T_STRATEGIES}(run_id), asset_symbol VARCHAR NOT NULL, weight DOUBLE NOT NULL CHECK (isfinite(weight) AND weight > 0 AND weight <= 1), PRIMARY KEY(run_id, asset_symbol))"
        )
        connection.execute("SELECT strategy_id, decision_date, apply_date, mode, weights, signals FROM legacy_v1_strategy_allocations")
        for strategy_id, decision_date, apply_date, mode, weights, signals in connection.fetchall():
            run_id = f"{strategy_id}:{apply_date}"
            connection.execute(f"INSERT INTO {T_STRATEGIES} VALUES (?, ?, ?, ?, ?, ?)", [run_id, strategy_id, decision_date, apply_date, mode, signals])
            connection.executemany(f"INSERT INTO {T_ALLOCATION_ROWS} VALUES (?, ?, ?)", [[run_id, symbol, float(weight)] for symbol, weight in _decode_json(weights).items()])
        connection.execute("DROP TABLE legacy_v1_strategy_allocations")

    def _migrate_legacy_bulk_tables(self, connection: Any) -> None:
        """기존 DuckDB 대용량 행을 ZSTD Parquet로 한 번 옮긴다."""
        if self._columns(connection, "feature_signals_daily"):
            years = [str(row[0]) for row in connection.execute(
                "SELECT DISTINCT year(trade_date) FROM feature_signals_daily ORDER BY 1"
            ).fetchall()]
            for year in years:
                target = self._feature_root / f"year={year}" / "data.parquet"
                connection.execute("DROP TABLE IF EXISTS migrated_features")
                if target.is_file():
                    connection.execute("""
                        CREATE TEMP TABLE migrated_features AS
                        SELECT ticker,trade_date,rsi14,macd,macd_signal,ingested_at
                        FROM (
                            SELECT *, row_number() OVER (
                                PARTITION BY ticker,trade_date ORDER BY ingested_at DESC
                            ) AS rank
                            FROM (
                                SELECT * FROM read_parquet(?)
                                UNION ALL
                                SELECT * FROM feature_signals_daily WHERE year(trade_date)=?
                            ) source
                        ) ranked WHERE rank=1 ORDER BY ticker,trade_date
                    """, [target.resolve().as_posix(), int(year)])
                else:
                    connection.execute("""
                        CREATE TEMP TABLE migrated_features AS
                        SELECT ticker,trade_date,rsi14,macd,macd_signal,ingested_at
                        FROM feature_signals_daily WHERE year(trade_date)=?
                        ORDER BY ticker,trade_date
                    """, [int(year)])
                self._write_parquet(connection, "migrated_features", target)
            latest = connection.execute(
                "SELECT max(trade_date),max(ingested_at) FROM feature_signals_daily"
            ).fetchone()
            if latest and latest[0] is not None:
                connection.execute(f"INSERT OR REPLACE INTO {T_FEATURE_SETS} VALUES (?,?,?,?)", [
                    FEATURE_VERSION, str(self._feature_root), latest[0], latest[1]
                ])
            connection.execute("DROP TABLE feature_signals_daily")

        if self._columns(connection, "research_records"):
            datasets = [str(row[0]) for row in connection.execute(
                "SELECT DISTINCT dataset FROM research_records ORDER BY dataset"
            ).fetchall()]
            for dataset in datasets:
                root = self._dataset_root(dataset)
                years = [str(row[0]) for row in connection.execute("""
                    SELECT DISTINCT CASE
                        WHEN regexp_matches(coalesce(cast(as_of_at AS VARCHAR),cast(available_at AS VARCHAR),''),
                                            '^[0-9]{4}-')
                        THEN substr(coalesce(cast(as_of_at AS VARCHAR),cast(available_at AS VARCHAR)),1,4)
                        ELSE 'undated' END
                    FROM research_records WHERE dataset=? ORDER BY 1
                """, [dataset]).fetchall()]
                for year in years:
                    target = root / f"year={year}" / "data.parquet"
                    connection.execute("DROP TABLE IF EXISTS migrated_records")
                    year_expression = "CASE WHEN regexp_matches(coalesce(cast(as_of_at AS VARCHAR),cast(available_at AS VARCHAR),''),'^[0-9]{4}-') THEN substr(coalesce(cast(as_of_at AS VARCHAR),cast(available_at AS VARCHAR)),1,4) ELSE 'undated' END"
                    if target.is_file():
                        connection.execute(f"""
                            CREATE TEMP TABLE migrated_records AS
                            SELECT record_key,ticker,as_of_at,available_at,payload FROM (
                                SELECT *,row_number() OVER (PARTITION BY record_key ORDER BY source_rank DESC) AS rank
                                FROM (
                                    SELECT record_key,ticker,as_of_at,available_at,payload,1 AS source_rank FROM read_parquet(?)
                                    UNION ALL
                                    SELECT record_key,ticker,cast(as_of_at AS VARCHAR),cast(available_at AS VARCHAR),cast(payload AS VARCHAR),2
                                    FROM research_records WHERE dataset=? AND {year_expression}=?
                                ) source
                            ) ranked WHERE rank=1 ORDER BY as_of_at,record_key
                        """, [target.resolve().as_posix(), dataset, year])
                    else:
                        connection.execute(f"""
                            CREATE TEMP TABLE migrated_records AS
                            SELECT record_key,ticker,cast(as_of_at AS VARCHAR) AS as_of_at,
                                   cast(available_at AS VARCHAR) AS available_at,
                                   cast(payload AS VARCHAR) AS payload
                            FROM research_records WHERE dataset=? AND {year_expression}=?
                            ORDER BY as_of_at,record_key
                        """, [dataset, year])
                    self._write_parquet(connection, "migrated_records", target)
                count = int(connection.execute(
                    "SELECT count(*) FROM research_records WHERE dataset=?", [dataset]
                ).fetchone()[0])
                updated = connection.execute(
                    "SELECT max(created_at) FROM research_records WHERE dataset=?", [dataset]
                ).fetchone()[0]
                connection.execute(f"INSERT OR REPLACE INTO {T_DATASET_RUNS} VALUES (?,?,?,?)", [
                    dataset, str(root), count, updated
                ])
            connection.execute("DROP TABLE research_records")

    @staticmethod
    def _rows(connection: Any) -> list[dict[str, Any]]:
        description = connection.description or ()
        columns = [str(item[0]) for item in description]
        return [dict(zip(columns, row)) for row in connection.fetchall()]

    # ── 기술지표 ────────────────────────────────────────────────────────
    @property
    def _parquet_root(self) -> Path:
        return self.path.parent / "parquet"

    @property
    def _feature_root(self) -> Path:
        return self._parquet_root / "features" / FEATURE_VERSION

    @staticmethod
    def _parquet_pattern(root: Path) -> str:
        return (root / "**" / "*.parquet").resolve().as_posix()

    @staticmethod
    def _write_parquet(connection: Any, table: str, target: Path) -> None:
        """같은 파일시스템의 임시 파일에 쓴 뒤 원자 교체한다."""
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            prefix=target.stem + ".", suffix=".parquet", dir=target.parent, delete=False
        )
        temporary = Path(handle.name)
        handle.close()
        escaped = temporary.resolve().as_posix().replace("'", "''")
        try:
            connection.execute(
                f"COPY {table} TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def _feature_files(self) -> list[Path]:
        return sorted(self._feature_root.glob("year=*/*.parquet"))

    def _ensure_bulk_migrated(self) -> None:
        if not self.read_only:
            with self._connect():
                pass

    def latest_feature_date(self) -> str | None:
        self._ensure_bulk_migrated()
        if not self._feature_files():
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT max(trade_date) FROM read_parquet(?, union_by_name=true)",
                [self._parquet_pattern(self._feature_root)],
            ).fetchone()
        return str(row[0]) if row and row[0] is not None else None

    def latest_feature_write_at(self) -> str | None:
        self._ensure_bulk_migrated()
        if not self._feature_files():
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT max(ingested_at) FROM read_parquet(?, union_by_name=true)",
                [self._parquet_pattern(self._feature_root)],
            ).fetchone()
        return _iso(row[0]) if row and row[0] is not None else None

    def features_since(self, since: str) -> list[dict[str, Any]]:
        """한 창의 feature를 종목 구분 없이 한 번에 읽는다.

        종목마다 따로 부르면 연결이 종목 수만큼 열린다 — 후보 선정이 503번을
        열면서 파일 잠금을 그만큼 잡았다.
        """
        self._ensure_bulk_migrated()
        if not self._feature_files():
            return []
        with self._connect() as connection:
            connection.execute(
                """
                SELECT ticker, trade_date, rsi14, macd, macd_signal, ingested_at
                FROM read_parquet(?, union_by_name=true)
                WHERE trade_date >= ?
                ORDER BY ticker, trade_date
                """,
                [self._parquet_pattern(self._feature_root), since],
            )
            rows = self._rows(connection)
        for row in rows:
            row["trade_date"] = str(row["trade_date"])
            row["ingested_at"] = _iso(row["ingested_at"])
        return rows

    def features_for_ticker(self, ticker: str, *, limit: int = 520) -> list[dict[str, Any]]:
        self._ensure_bulk_migrated()
        if not self._feature_files():
            return []
        with self._connect() as connection:
            connection.execute(
                """
                SELECT ticker, trade_date, rsi14, macd, macd_signal, ingested_at
                FROM read_parquet(?, union_by_name=true)
                WHERE ticker = ?
                ORDER BY trade_date DESC
                LIMIT ?
                """,
                [self._parquet_pattern(self._feature_root), ticker, limit],
            )
            rows = self._rows(connection)
        for row in rows:
            row["trade_date"] = str(row["trade_date"])
            row["ingested_at"] = _iso(row["ingested_at"])
        return rows

    def upsert_features(self, rows: Iterable[dict[str, Any]], *, ingested_at: str) -> int:
        normalized = [_feature_row(row, ingested_at) for row in rows]
        if not normalized:
            return 0
        with self._connect() as connection:
            changed_count = 0
            by_year: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in normalized:
                by_year[str(row["trade_date"])[:4]].append(row)
            for year, candidates in by_year.items():
                target = self._feature_root / f"year={year}" / "data.parquet"
                connection.execute("DROP TABLE IF EXISTS feature_partition")
                connection.execute("""
                    CREATE TEMP TABLE feature_partition (
                        ticker VARCHAR, trade_date DATE, rsi14 DOUBLE, macd DOUBLE,
                        macd_signal DOUBLE, ingested_at TIMESTAMPTZ
                    )
                """)
                if target.is_file():
                    connection.execute(
                        "INSERT INTO feature_partition SELECT ticker,trade_date,rsi14,macd,macd_signal,ingested_at FROM read_parquet(?)",
                        [target.resolve().as_posix()],
                    )
                existing = {
                    (str(item[0]), str(item[1])): item[2:]
                    for item in connection.execute(
                        "SELECT ticker,trade_date,rsi14,macd,macd_signal FROM feature_partition"
                    ).fetchall()
                }
                changed = [row for row in candidates if (
                    (row["ticker"], row["trade_date"]) not in existing
                    or any(
                        not _same_number(
                            row[name], existing[(row["ticker"], row["trade_date"])][index]
                        )
                        for index, name in enumerate(("rsi14", "macd", "macd_signal"))
                    )
                )]
                if not changed:
                    continue
                connection.executemany(
                    "DELETE FROM feature_partition WHERE ticker=? AND trade_date=?",
                    [(row["ticker"], row["trade_date"]) for row in changed],
                )
                connection.executemany(
                    "INSERT INTO feature_partition VALUES (?,?,?,?,?,?)",
                    [[row["ticker"], row["trade_date"], row["rsi14"], row["macd"],
                      row["macd_signal"], row["ingested_at"]] for row in changed],
                )
                connection.execute(
                    "CREATE OR REPLACE TEMP TABLE feature_partition_sorted AS "
                    "SELECT * FROM feature_partition ORDER BY ticker,trade_date"
                )
                self._write_parquet(connection, "feature_partition_sorted", target)
                changed_count += len(changed)
            latest = max(str(row["trade_date"]) for row in normalized)
            connection.execute(f"""
                INSERT INTO {T_FEATURE_SETS} VALUES (?,?,?,?)
                ON CONFLICT(feature_version) DO UPDATE SET
                    root_path=excluded.root_path,
                    latest_trade_date=greatest({T_FEATURE_SETS}.latest_trade_date, excluded.latest_trade_date),
                    updated_at=excluded.updated_at
            """, [FEATURE_VERSION, str(self._feature_root), latest, ingested_at])
            return changed_count

    def delete_features_before(self, cutoff: str) -> int:
        self._ensure_bulk_migrated()
        if not self._feature_files():
            return 0
        with self._connect() as connection:
            deleted = 0
            for target in self._feature_files():
                connection.execute("DROP TABLE IF EXISTS retained_features")
                connection.execute(
                    "CREATE TEMP TABLE retained_features AS "
                    "SELECT * FROM read_parquet(?) WHERE trade_date >= ?",
                    [target.resolve().as_posix(), cutoff],
                )
                total = connection.execute(
                    "SELECT count(*) FROM read_parquet(?)", [target.resolve().as_posix()]
                ).fetchone()[0]
                kept = connection.execute("SELECT count(*) FROM retained_features").fetchone()[0]
                deleted += int(total - kept)
                if kept:
                    self._write_parquet(connection, "retained_features", target)
                else:
                    target.unlink(missing_ok=True)
            return deleted

    def latest_feature_as_of(self, ticker: str, *, trade_date: date, as_of_at: datetime) -> list[dict[str, Any]]:
        self._ensure_bulk_migrated()
        if not self._feature_files():
            return []
        with self._connect() as connection:
            connection.execute(
                """
                SELECT ticker, trade_date, rsi14, macd, macd_signal, ingested_at
                FROM read_parquet(?, union_by_name=true)
                WHERE ticker = ? AND trade_date <= ? AND ingested_at <= ?
                ORDER BY trade_date DESC
                LIMIT 1
                """,
                [self._parquet_pattern(self._feature_root), ticker, trade_date.isoformat(), as_of_at],
            )
            rows = self._rows(connection)
        for row in rows:
            row["trade_date"] = str(row["trade_date"])
            row["ingested_at"] = _iso(row["ingested_at"])
        return rows

    def latest_features_as_of_all(self, *, trade_date: date, as_of_at: datetime) -> dict[str, dict[str, Any]]:
        """`latest_feature_as_of`와 같은 조건으로 전 종목의 최신 행을 한 번에 읽는다(ticker → 행)."""
        self._ensure_bulk_migrated()
        if not self._feature_files():
            return {}
        with self._connect() as connection:
            connection.execute(
                """
                SELECT ticker, trade_date, rsi14, macd, macd_signal, ingested_at
                FROM (
                    SELECT *, row_number() OVER (PARTITION BY ticker ORDER BY trade_date DESC) AS rank
                    FROM read_parquet(?, union_by_name=true)
                    WHERE trade_date <= ? AND ingested_at <= ?
                ) ranked
                WHERE rank = 1
                """,
                [self._parquet_pattern(self._feature_root), trade_date.isoformat(), as_of_at],
            )
            rows = self._rows(connection)
        output: dict[str, dict[str, Any]] = {}
        for row in rows:
            row["trade_date"] = str(row["trade_date"])
            row["ingested_at"] = _iso(row["ingested_at"])
            output[str(row["ticker"])] = row
        return output

    # ── 전략 배분 ───────────────────────────────────────────────────────
    def allocation_strategy_ids(self, apply_date: date) -> set[str]:
        with self._connect() as connection:
            connection.execute(
                f"SELECT strategy_id FROM {T_STRATEGIES} WHERE apply_date = ?",
                [apply_date.isoformat()],
            )
            return {str(row[0]) for row in connection.fetchall()}

    def upsert_allocation(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "strategy_id": str(row["strategy_id"]),
            "decision_date": str(row["decision_date"]),
            "apply_date": str(row["apply_date"]),
            "mode": str(row["mode"]),
            "signals": json.dumps(row.get("signals") or {}, sort_keys=True, ensure_ascii=False),
        }
        run_id = f"{payload['strategy_id']}:{payload['apply_date']}"
        with self._connect() as connection:
            connection.execute(
                f"""
                INSERT INTO {T_STRATEGIES}
                    (run_id, strategy_id, decision_date, apply_date, mode, signals)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (strategy_id, apply_date) DO UPDATE SET
                    decision_date = excluded.decision_date,
                    mode = excluded.mode,
                    signals = excluded.signals
                """,
                [run_id, payload["strategy_id"], payload["decision_date"], payload["apply_date"], payload["mode"], payload["signals"]],
            )
            connection.execute(f"DELETE FROM {T_ALLOCATION_ROWS} WHERE run_id = ?", [run_id])
            connection.executemany(
                f"INSERT INTO {T_ALLOCATION_ROWS} VALUES (?, ?, ?)",
                [[run_id, symbol, float(weight)] for symbol, weight in row["weights"].items()],
            )
        return {**payload, "signals": _decode_json(payload["signals"]), "run_id": run_id, "weights": dict(row["weights"])}

    def mark_allocations_sent(self, apply_date: date, *, sent_at: str) -> int:
        """알림 상태는 Postgres 알림 원장(`notifications.notices`)이 소유한다."""
        del sent_at
        with self._connect() as connection:
            return int(connection.execute(
                f"SELECT count(*) FROM {T_STRATEGIES} WHERE apply_date = ?", [apply_date.isoformat()]
            ).fetchone()[0])

    def delete_allocations_before(self, cutoff_date: str) -> int:
        """자식 행 삭제와 부모 행 삭제를 별도 transaction으로 나눈다.

        DuckDB는 같은 transaction 안에서 자식을 지운 직후 그 삭제를 참조하는 부모를
        지우면 FK 색인이 아직 갱신되지 않아 "still referenced" 제약 오류를 낸다
        (DuckDB의 알려진 FK 제약 한계). 자식 삭제를 먼저 commit해야 부모 삭제가 통과한다.
        """
        with self._connect() as connection:
            before = connection.execute(
                f"SELECT count(*) FROM {T_STRATEGIES} WHERE apply_date < ?",
                [cutoff_date],
            ).fetchone()[0]
            connection.execute(
                f"DELETE FROM {T_ALLOCATION_ROWS} WHERE run_id IN "
                f"(SELECT run_id FROM {T_STRATEGIES} WHERE apply_date < ?)",
                [cutoff_date],
            )
        with self._connect() as connection:
            connection.execute(f"DELETE FROM {T_STRATEGIES} WHERE apply_date < ?", [cutoff_date])
        return int(before)

    def allocations(self, *, pending_only: bool = False) -> list[dict[str, Any]]:
        del pending_only
        with self._connect() as connection:
            connection.execute(
                f"""
                SELECT run_id, strategy_id, decision_date, apply_date, mode, signals
                FROM {T_STRATEGIES}
                ORDER BY apply_date, strategy_id
                """
            )
            rows = self._rows(connection)
            connection.execute(f"SELECT run_id, asset_symbol, weight FROM {T_ALLOCATION_ROWS} ORDER BY run_id, asset_symbol")
            weights = defaultdict(dict)
            for run_id, symbol, weight in connection.fetchall():
                weights[str(run_id)][str(symbol)] = float(weight)
        return [{**_decode_allocation(row), "weights": weights[str(row["run_id"])]} for row in rows]

    def previous_allocation(self, strategy_id: str, apply_date: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            connection.execute(
                f"""
                SELECT run_id FROM {T_STRATEGIES}
                WHERE strategy_id = ? AND apply_date < ?
                ORDER BY apply_date DESC LIMIT 1
                """,
                [strategy_id, apply_date],
            )
            row = connection.fetchone()
            if not row:
                return None
            run_id = str(row[0])
            rows = connection.execute(
                f"SELECT asset_symbol, weight FROM {T_ALLOCATION_ROWS} WHERE run_id = ?",
                [run_id],
            ).fetchall()
        return {str(symbol): float(weight) for symbol, weight in rows}

    def mark_allocation_sent(self, strategy_id: str, apply_date: str, *, sent_at: str) -> None:
        del strategy_id, apply_date, sent_at

    # ── 기타 Research artifact ─────────────────────────────────────────
    def _dataset_root(self, dataset: str) -> Path:
        if not _DATASET_NAME.fullmatch(str(dataset)):
            raise ValueError("invalid research dataset name")
        return self._parquet_root / "datasets" / str(dataset)

    def _dataset_files(self, dataset: str) -> list[Path]:
        return sorted(self._dataset_root(dataset).glob("year=*/*.parquet"))

    def upsert_records(self, dataset: str, rows: Iterable[dict[str, Any]], *, key: str, ignore_existing: bool = False) -> int:
        normalized = [dict(row) for row in rows]
        if not normalized:
            return 0
        if any(key not in row or not str(row[key]).strip() for row in normalized):
            raise ValueError("research record identity is required")
        if len({str(row[key]) for row in normalized}) != len(normalized):
            raise ValueError("duplicate research record identity in one write")
        root = self._dataset_root(dataset)
        with self._connect() as connection:
            connection.execute("DROP TABLE IF EXISTS incoming_records")
            connection.execute("""
                CREATE TEMP TABLE incoming_records (
                    record_key VARCHAR, ticker VARCHAR, as_of_at VARCHAR,
                    available_at VARCHAR, payload VARCHAR, partition_year VARCHAR
                )
            """)
            connection.executemany(
                "INSERT INTO incoming_records VALUES (?,?,?,?,?,?)",
                [
                    [
                        str(row[key]),
                        str(row.get("ticker") or "").upper() or None,
                        str(row.get("as_of_at")) if row.get("as_of_at") is not None else None,
                        str(row.get("available_at")) if row.get("available_at") is not None else None,
                        json.dumps(row, sort_keys=True, ensure_ascii=False),
                        _record_year(row),
                    ]
                    for row in normalized
                ],
            )
            # 최초 관측 경험은 같은 writer 트랜잭션 안에서 기존 키를 제외한다.
            if ignore_existing and self._dataset_files(dataset):
                connection.execute(
                    "DELETE FROM incoming_records WHERE record_key IN "
                    "(SELECT record_key FROM read_parquet(?, union_by_name=true))",
                    [self._parquet_pattern(root)],
                )
            inserted_count = int(connection.execute("SELECT count(*) FROM incoming_records").fetchone()[0])
            if inserted_count == 0:
                return 0
            touched = {str(row[0]) for row in connection.execute(
                "SELECT DISTINCT partition_year FROM incoming_records"
            ).fetchall()}
            files = self._dataset_files(dataset)
            if files:
                previous = connection.execute(
                    "SELECT DISTINCT year FROM read_parquet(?, hive_partitioning=true, union_by_name=true) "
                    "WHERE record_key IN (SELECT record_key FROM incoming_records)",
                    [self._parquet_pattern(root)],
                ).fetchall()
                touched.update(str(row[0]) for row in previous)
            for year in sorted(touched):
                target = root / f"year={year}" / "data.parquet"
                connection.execute("DROP TABLE IF EXISTS research_partition")
                connection.execute("""
                    CREATE TEMP TABLE research_partition (
                        record_key VARCHAR, ticker VARCHAR, as_of_at VARCHAR,
                        available_at VARCHAR, payload VARCHAR
                    )
                """)
                if target.is_file():
                    connection.execute(
                        "INSERT INTO research_partition SELECT record_key,ticker,as_of_at,available_at,payload "
                        "FROM read_parquet(?) WHERE record_key NOT IN "
                        "(SELECT record_key FROM incoming_records)",
                        [target.resolve().as_posix()],
                    )
                connection.execute(
                    "INSERT INTO research_partition SELECT record_key,ticker,as_of_at,available_at,payload "
                    "FROM incoming_records WHERE partition_year=?",
                    [year],
                )
                count = int(connection.execute("SELECT count(*) FROM research_partition").fetchone()[0])
                if count:
                    connection.execute(
                        "CREATE OR REPLACE TEMP TABLE research_partition_sorted AS "
                        "SELECT * FROM research_partition ORDER BY as_of_at,record_key"
                    )
                    self._write_parquet(connection, "research_partition_sorted", target)
                else:
                    target.unlink(missing_ok=True)
            files = self._dataset_files(dataset)
            total = int(connection.execute(
                "SELECT count(*) FROM read_parquet(?, union_by_name=true)",
                [self._parquet_pattern(root)],
            ).fetchone()[0]) if files else 0
            connection.execute(f"""
                INSERT INTO {T_DATASET_RUNS} VALUES (?,?,?,now())
                ON CONFLICT(dataset) DO UPDATE SET
                    root_path=excluded.root_path,row_count=excluded.row_count,
                    updated_at=excluded.updated_at
            """, [dataset, str(root), total])
        return inserted_count

    def records(
        self,
        dataset: str,
        *,
        ticker: str | None = None,
        start_as_of: str | None = None,
        end_as_of: str | None = None,
        as_of_values: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        root = self._dataset_root(dataset)
        self._ensure_bulk_migrated()
        if not self._dataset_files(dataset):
            return []
        predicates = ["true"]
        params: list[Any] = [self._parquet_pattern(root)]
        if ticker is not None:
            predicates.append("ticker = ?")
            params.append(str(ticker).upper())
        if start_as_of is not None:
            predicates.append("as_of_at >= ?")
            params.append(str(start_as_of))
        if end_as_of is not None:
            predicates.append("as_of_at <= ?")
            params.append(str(end_as_of))
        if as_of_values is not None:
            values = sorted({str(value) for value in as_of_values})
            if not values:
                return []
            predicates.append(f"as_of_at IN ({','.join('?' for _ in values)})")
            params.extend(values)
        statement = (
            f"SELECT payload FROM read_parquet(?, union_by_name=true) WHERE {' AND '.join(predicates)} "
            "ORDER BY as_of_at, record_key"
        )
        if limit is not None:
            statement += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as connection:
            rows = connection.execute(statement, params).fetchall()
        return [dict(_decode_json(row[0])) for row in rows]

    def records_with_payload_fields(
        self,
        dataset: str,
        payload_fields: Sequence[str],
        *,
        ticker: str | None = None,
        start_as_of: str | None = None,
        end_as_of: str | None = None,
        as_of_values: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """원장 payload를 전부 JSON으로 풀지 않고 필요한 scalar field만 읽는다."""
        fields = tuple(str(field) for field in payload_fields)
        if len(fields) != len(set(fields)) or any(
            not _PAYLOAD_FIELD_NAME.fullmatch(field) for field in fields
        ):
            raise ValueError("invalid or duplicate research payload field")
        root = self._dataset_root(dataset)
        self._ensure_bulk_migrated()
        if not self._dataset_files(dataset):
            return []
        predicates = ["true"]
        params: list[Any] = [self._parquet_pattern(root)]
        if ticker is not None:
            predicates.append("ticker = ?")
            params.append(str(ticker).upper())
        if start_as_of is not None:
            predicates.append("as_of_at >= ?")
            params.append(str(start_as_of))
        if end_as_of is not None:
            predicates.append("as_of_at <= ?")
            params.append(str(end_as_of))
        if as_of_values is not None:
            values = sorted({str(value) for value in as_of_values})
            if not values:
                return []
            predicates.append(f"as_of_at IN ({','.join('?' for _ in values)})")
            params.extend(values)
        columns = ["record_key", "ticker", "as_of_at", "available_at"]
        columns.extend(
            f"json_extract_string(payload, '$.{field}') AS {field}" for field in fields
        )
        statement = (
            f"SELECT {','.join(columns)} FROM read_parquet(?, union_by_name=true) "
            f"WHERE {' AND '.join(predicates)} ORDER BY as_of_at, record_key"
        )
        with self._connect() as connection:
            rows = connection.execute(statement, params).fetchall()
        names = ("record_key", "ticker", "as_of_at", "available_at", *fields)
        return [dict(zip(names, row, strict=True)) for row in rows]

    def record_keys(self, dataset: str) -> set[str]:
        """이미 보존한 identity만 읽어 대용량 JSON payload 재처리를 피한다."""
        root = self._dataset_root(dataset)
        self._ensure_bulk_migrated()
        if not self._dataset_files(dataset):
            return set()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT record_key FROM read_parquet(?, union_by_name=true)",
                [self._parquet_pattern(root)],
            ).fetchall()
        return {str(row[0]) for row in rows}

    def save_events(self, events: Sequence[Any]) -> None:
        """Research event는 production 원장이 아닌 local artifact에 보존한다."""
        if not events:
            return
        rows: list[dict[str, Any]] = []
        for event in events:
            payload = event.to_dict()
            rows.append({
                **payload,
                "record_key": hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest(),
            })
        self.upsert_records("events", rows, key="record_key")

    def save_event_features(self, snapshots: Sequence[Any]) -> None:
        if not snapshots:
            return
        rows = [
            {"record_key": f"event_features_{snapshot.input_hash[:24]}", **snapshot.to_dict()}
            for snapshot in snapshots
        ]
        self.upsert_records("event_feature_snapshots", rows, key="record_key")

    def save_training_samples(self, samples: Sequence[TrainingSample]) -> int:
        if not samples:
            return 0
        identities = [sample.sample_id for sample in samples]
        if len(identities) != len(set(identities)):
            raise ValueError("training sample batch contains duplicate identities")
        existing = self.record_keys("training_samples")
        rows = [sample.to_dict() for sample in samples if sample.sample_id not in existing]
        if not rows:
            return 0
        for row in rows:
            row["record_key"] = row["sample_id"]
        return self.upsert_records("training_samples", rows, key="record_key", ignore_existing=True)

    def training_sample_run_rows(self, *, start_as_of: str, end_as_of: str) -> list[dict[str, Any]]:
        return self.records("training_sample_runs", start_as_of=start_as_of, end_as_of=end_as_of)

    def training_sample_period_inputs(
        self,
        symbols: Sequence[str],
        *,
        start_as_of: str,
        end_as_of: str,
        feature_version: str,
        label_cutoff_at: str,
    ) -> dict[str, list[dict[str, Any]]]:
        """완료 기간 판정에 필요한 scalar만 읽어 feature/label JSON 복원을 피한다."""
        normalized = set(normalize_symbols(tuple(symbols)))
        start = parse_datetime(start_as_of)
        end = parse_datetime(end_as_of)
        cutoff = parse_datetime(label_cutoff_at)
        if end < start or cutoff < end:
            raise ValueError("invalid training sample metadata window")
        snapshots = self.records_with_payload_fields(
            "rl_feature_snapshots", ("feature_version", "input_hash"),
            start_as_of=start.isoformat(), end_as_of=end.isoformat(),
        )
        labels = self.records_with_payload_fields(
            "rl_training_labels", ("feature_version", "label_available_at", "label_id"),
            start_as_of=start.isoformat(), end_as_of=end.isoformat(),
        )
        return {
            "snapshots": [
                row for row in snapshots
                if row.get("feature_version") == feature_version
                and normalize_ticker(row.get("ticker")) in normalized
            ],
            "labels": [
                row for row in labels
                if row.get("feature_version") == feature_version
                and normalize_ticker(row.get("ticker")) in normalized
                and parse_datetime(str(row["label_available_at"])) <= cutoff
            ],
        }

    def rl_feature_snapshot_rows(
        self,
        symbols: tuple[str, ...],
        *,
        start_as_of: str,
        end_as_of: str,
        feature_version: str,
        as_of_values: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """미래 label 없이 point-in-time feature payload만 검증해 반환한다."""
        normalized = normalize_symbols(symbols)
        start = parse_datetime(start_as_of)
        end = parse_datetime(end_as_of)
        if end < start:
            raise ValueError("RL feature end_as_of must not precede start_as_of")
        if not str(feature_version).strip():
            raise ValueError("feature_version is required")
        rows = self.records(
            "rl_feature_snapshots",
            start_as_of=start.isoformat(),
            end_as_of=end.isoformat(),
            as_of_values=as_of_values,
        )
        rows = [
            row for row in rows
            if row.get("feature_version") == feature_version
            and normalize_ticker(str(row.get("ticker"))) in normalized
            and parse_datetime(str(row["available_at"])) <= end
        ]
        return [self._feature_snapshot(dict(row)).to_storage_row() for row in rows]

    def rl_training_label_rows(
        self,
        symbols: tuple[str, ...],
        *,
        start_as_of: str,
        end_as_of: str,
        feature_version: str,
        label_cutoff_at: str,
        as_of_values: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """학습 cutoff 전에 생성된 미래 label payload만 검증해 반환한다."""
        normalized = normalize_symbols(symbols)
        start = parse_datetime(start_as_of)
        end = parse_datetime(end_as_of)
        cutoff = parse_datetime(label_cutoff_at)
        if end < start:
            raise ValueError("RL label end_as_of must not precede start_as_of")
        if cutoff < end:
            raise ValueError("label_cutoff_at must not precede the feature window end")
        if not str(feature_version).strip():
            raise ValueError("feature_version is required")
        rows = self.records(
            "rl_training_labels",
            start_as_of=start.isoformat(),
            end_as_of=end.isoformat(),
            as_of_values=as_of_values,
        )
        rows = [
            row for row in rows
            if row.get("feature_version") == feature_version
            and normalize_ticker(str(row.get("ticker"))) in normalized
            and parse_datetime(str(row["label_available_at"])) <= cutoff
        ]
        return [self._training_label(dict(row)).to_storage_row() for row in rows]

    def save_training_sample_runs(self, rows: Sequence[dict[str, Any]]) -> int:
        if not rows:
            return 0
        return self.upsert_records("training_sample_runs", rows, key="record_key")

    def save_rl_feature_snapshots(self, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        snapshots = [self._feature_snapshot(dict(row)) for row in rows]
        identities = [(item.feature_version, item.as_of_at, item.ticker) for item in snapshots]
        if len(identities) != len(set(identities)):
            raise ValueError("RL feature batch contains duplicate snapshot identities")
        stored = [item.to_storage_row() for item in snapshots]
        for row in stored:
            row["record_key"] = f"{row['feature_version']}:{row['as_of_at']}:{row['ticker']}"
        self.upsert_records("rl_feature_snapshots", stored, key="record_key")

    def save_rl_training_labels(self, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        labels = [self._training_label(dict(row)) for row in rows]
        identities = [(item.feature_version, item.as_of_at, item.ticker) for item in labels]
        if len(identities) != len(set(identities)):
            raise ValueError("RL label batch contains duplicate label identities")
        stored = [item.to_storage_row() for item in labels]
        for row in stored:
            row["record_key"] = f"{row['feature_version']}:{row['as_of_at']}:{row['ticker']}"
        self.upsert_records("rl_training_labels", stored, key="record_key")

    def save_valuation_observations(self, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        identities = [
            (str(row["ticker"]), str(row["as_of_at"]), str(row["source_kind"]))
            for row in rows
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("valuation batch contains duplicate observation identities")
        stored = [dict(row) for row in rows]
        for row in stored:
            row["record_key"] = f"{row['ticker']}:{row['as_of_at']}:{row['source_kind']}"
        self.upsert_records("valuation_observations", stored, key="record_key")

    def save_decision_experiences(self, rows: Sequence[dict[str, Any]]) -> None:
        self.upsert_records("decision_experiences", rows, key="record_key", ignore_existing=True)

    def decision_experience_rows(
        self, *, as_of_at: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """관측 완료 시각 이전의 가상 판단 경험만 반환한다."""
        try:
            rows = self.records("decision_experiences")
        except FileNotFoundError:
            return []
        return [
            row for row in rows
            if as_of_at is None or parse_datetime(str(row["available_at"])) <= as_of_at
        ]

    def model_evaluation_rows(self, artifact_id: str) -> list[dict[str, Any]]:
        artifact_id = str(artifact_id).strip()
        if not artifact_id:
            raise ValueError("artifact_id is required")
        return [
            {**row, "artifact_id": artifact_id}
            for row in self.records("portfolio_evaluations")
            if str(row.get("model_artifact_id") or "") == artifact_id
        ]

    def model_evaluation_summary(self, artifact_id: str) -> EvaluationSummary:
        return aggregate_evaluations(self.model_evaluation_rows(artifact_id))

    def save_promotion(self, trading_repository: Any, row: dict[str, Any]) -> None:
        trading_repository.record_model_promotion(row)

    def approve_model_promotion(
        self,
        trading_repository: Any,
        decision: PromotionDecision,
        *,
        confirmation: str,
        model_artifact: dict[str, Any] | None,
        model_stage: str | None,
    ) -> dict[str, Any]:
        if decision.status != "approved" or decision.violations:
            raise ValueError("only a manually is_approved clean decision can be persisted")
        if model_artifact is None:
            raise RuntimeError("model promotion failed closed: artifact not found")
        if model_stage != decision.from_stage:
            raise RuntimeError("model promotion failed closed: artifact stage changed")
        expected = approval_confirmation(decision.artifact_id, decision.from_stage, decision.to_stage)
        if confirmation != expected:
            raise ValueError(f"confirmation must exactly match: {expected}")
        return trading_repository.approve_model_promotion(
            audit_row={
                "artifact_id": decision.artifact_id,
                "from_stage": decision.from_stage,
                "to_stage": decision.to_stage,
                "status": "approved",
                "evidence": decision.to_record()["evidence"],
                "approved_by": decision.approved_by,
                "approved_at": decision.approved_at,
                "confirmation_text": confirmation,
            },
            artifact_id=decision.artifact_id,
            from_stage=decision.from_stage,
            to_stage=decision.to_stage,
        )

    @staticmethod
    def _feature_snapshot(row: dict[str, Any]) -> FeatureSnapshot:
        snapshot = FeatureSnapshot(
            feature_version=str(row["feature_version"]),
            as_of_at=str(row["as_of_at"]),
            ticker=str(row["ticker"]),
            available_at=str(row["available_at"]),
            is_available=row["is_available"],
            features=dict(row["features"]),
            source_ids=tuple(row["source_ids"]),
            provenance=dict(row["provenance"]),
        )
        if str(row.get("input_hash") or "") != snapshot.input_hash:
            raise RuntimeError("stored RL feature input_hash does not match its provenance")
        return snapshot

    @staticmethod
    def _training_label(row: dict[str, Any]) -> ForwardReturnLabel:
        label = ForwardReturnLabel(
            feature_version=str(row["feature_version"]),
            as_of_at=str(row["as_of_at"]),
            ticker=str(row["ticker"]),
            forward_end_at=str(row["forward_end_at"]),
            label_available_at=str(row["label_available_at"]),
            forward_return=float(row["forward_return"]),
            benchmark_forward_return=float(row["benchmark_forward_return"]),
        )
        if str(row.get("label_id") or "") != label.label_id:
            raise RuntimeError("stored RL label_id does not match its payload")
        return label


def _feature_row(row: dict[str, Any], ingested_at: str) -> dict[str, Any]:
    def value(name: str) -> float | None:
        raw = row.get(name)
        return None if raw is None else float(raw)

    return {
        "ticker": str(row["ticker"]),
        "trade_date": str(row["trade_date"]),
        "rsi14": value("rsi14"),
        "macd": value("macd"),
        "macd_signal": value("macd_signal"),
        "ingested_at": ingested_at,
    }


def _record_year(row: dict[str, Any]) -> str:
    """시간 축이 없는 작은 artifact도 안전한 partition 이름으로 보낸다."""
    for key in ("as_of_at", "available_at", "trade_date", "apply_date", "date"):
        value = str(row.get(key) or "")
        if re.match(r"^[0-9]{4}-", value):
            return value[:4]
    return "undated"


def _same_number(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return abs(float(left) - float(right)) <= 1e-10 * max(1.0, abs(float(left)), abs(float(right)))


def _decode_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    return json.loads(str(value))


def _decode_allocation(row: dict[str, Any]) -> dict[str, Any]:
    value = dict(row)
    if "weights" in value:
        value["weights"] = _decode_json(value["weights"])
    value["signals"] = _decode_json(value["signals"])
    for key in ("decision_date", "apply_date"):
        if value.get(key) is not None:
            value[key] = str(value[key])
    return value


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


__all__ = [
    "DATABASE_NAME",
    "DEFAULT_RESEARCH_ROOT",
    "RESEARCH_DDL_DIR",
    "FEATURE_VERSION",
    "RESEARCH_ROOT_ENV",
    "ResearchStore",
    "T_STRATEGIES",
    "default_database_path",
]
