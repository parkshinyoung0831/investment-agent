"""feature 버전 컬럼을 없앤 뒤 로컬 저장소를 새 모양으로 맞춘다 — 기본은 dry-run(읽기만).

`feature_version`·`source_version`(밸류에이션) 컬럼은 코드에서 사라졌다. 옛 모양으로 남은 로컬 저장소는
그대로 두면 새 코드와 어긋난다(`model_versions`의 NOT NULL 컬럼에 값을 못 넣고, 옛 정의로 만든 값이 새 값과
같은 키로 섞인다). 이 스크립트가 하는 일:

1. 판단 원장 `runtime.sqlite3`의 `model_versions.feature_version` 컬럼을 지운다. 다른 행은 건드리지 않는다.
2. 기술지표 Parquet 폴더 `features/technical_v1`을 `features/technical`로 옮기고 DuckDB catalog의
   `feature_sets`·`datasets` 표를 버린다(다음 적재가 새 선언으로 다시 만든다). 값은 그대로다 — RSI·MACD는
   정의가 바뀌지 않았다.
3. 옛 정의로 만든 파생 dataset 폴더를 지운다. feature snapshot·label·학습 표본·사건 feature·밸류에이션
   관측·과거 재현 실행 기록이다. 고친 코드가 다시 만든다.
4. 옛 feature로 학습한 ML 후보 모델(`artifacts/trading/ml_models`)을 지운다. 새 정의로 다시 학습한다.

실행:
    python scripts/reset_feature_version_stores.py           # 대상만 센다
    python scripts/reset_feature_version_stores.py --apply   # 실제로 바꾼다

백업은 만들지 않는다 — 지운 것은 전부 고친 코드가 다시 만드는 파생 데이터다. 하네스가 도는 중에는
실행하지 않는다(정비 보류 상태에서 실행). 한 번 쓰고 나면 이 파일은 지워도 된다.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import stat
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from investment_agent.platform.storage_paths import (  # noqa: E402
    repository_artifact_root,
    research_database_path,
    runtime_database_path,
)

# 옛 feature 정의로 만든 파생 dataset. `events`는 원문 사건이라 정의와 무관해 남긴다.
DERIVED_DATASETS = (
    "rl_feature_snapshots",
    "rl_training_labels",
    "training_samples",
    "training_sample_runs",
    "event_feature_snapshots",
    "valuation_observations",
    "historical_replay_runs",
)
OLD_FEATURE_DIR = "technical_v1"
NEW_FEATURE_DIR = "technical"


def _force_remove(function, path, _error) -> None:
    """Windows는 읽기 전용 속성이 붙은 빈 폴더를 rmdir하지 못한다 — 속성을 풀고 한 번 더 지운다."""
    os.chmod(path, stat.S_IWRITE)
    function(path)


def _size_mb(path: Path) -> float:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) / 1_000_000


def plan_runtime(apply: bool) -> None:
    path = runtime_database_path()
    if not path.is_file():
        print(f"[runtime] {path} 없음 — 건너뜀")
        return
    with closing(sqlite3.connect(path)) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(model_versions)")]
        if "feature_version" not in columns:
            print("[runtime] model_versions에 feature_version 컬럼이 이미 없다")
            return
        rows = connection.execute("SELECT count(*) FROM model_versions").fetchone()[0]
        print(f"[runtime] model_versions.feature_version 컬럼 삭제 대상 (행 {rows}개는 그대로 남는다)")
        if apply:
            connection.execute("ALTER TABLE model_versions DROP COLUMN feature_version")
            connection.commit()
            print("[runtime] 컬럼을 지웠다")


def plan_research(apply: bool) -> None:
    root = research_database_path().parent / "parquet"
    old_dir = root / "features" / OLD_FEATURE_DIR
    new_dir = root / "features" / NEW_FEATURE_DIR
    if old_dir.is_dir():
        if new_dir.exists():
            raise SystemExit(f"{new_dir}이 이미 있다 — 옛 폴더와 합치지 않는다. 확인 뒤 다시 실행")
        print(f"[research] {old_dir.name} → {new_dir.name} 이름 변경 ({_size_mb(old_dir):.1f} MB, 값은 그대로)")
        if apply:
            old_dir.rename(new_dir)
    else:
        print(f"[research] {old_dir.name} 폴더 없음")

    datasets = root / "datasets"
    targets = [datasets / name for name in DERIVED_DATASETS if (datasets / name).is_dir()]
    for target in targets:
        print(f"[research] 삭제 대상 dataset {target.name} ({_size_mb(target):.1f} MB)")
        if apply:
            shutil.rmtree(target, onexc=_force_remove)

    database = research_database_path()
    if not database.is_file():
        print(f"[research] {database} 없음 — catalog 건너뜀")
        return
    import duckdb

    with duckdb.connect(str(database), read_only=not apply) as connection:
        tables = {row[0] for row in connection.execute("SELECT table_name FROM information_schema.tables").fetchall()}
        # `datasets`는 연구 lineage 표(experiments → models → backtests)가 참조해서 혼자 못 버린다. 넷이 모두
        # 비어 있을 때만 참조하는 쪽부터 함께 버린다 — 행이 있으면 lineage를 잃지 않도록 멈춘다.
        lineage = ("backtests", "models", "experiments", "datasets")
        for table in ("feature_sets", *lineage):
            if table in tables:
                count = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                if table in lineage and count:
                    raise SystemExit(f"{table}에 행 {count}개가 있다 — lineage를 지우지 않는다. 확인 뒤 다시 실행")
                print(f"[research] catalog 표 {table} 삭제 대상 (행 {count}개, 다음 적재가 새 선언으로 다시 만든다)")
                if apply:
                    connection.execute(f"DROP TABLE {table}")
        if "dataset_runs" in tables and DERIVED_DATASETS:
            marks = ",".join("?" for _ in DERIVED_DATASETS)
            count = connection.execute(
                f"SELECT count(*) FROM dataset_runs WHERE dataset IN ({marks})", list(DERIVED_DATASETS),
            ).fetchone()[0]
            print(f"[research] dataset_runs에서 지울 행 {count}개")
            if apply:
                connection.execute(f"DELETE FROM dataset_runs WHERE dataset IN ({marks})", list(DERIVED_DATASETS))


def plan_models(apply: bool) -> None:
    models = repository_artifact_root() / "trading" / "ml_models"
    if not models.is_dir():
        print("[models] ml_models 폴더 없음")
        return
    files = sum(1 for item in models.rglob("*") if item.is_file())
    print(f"[models] {models} 삭제 대상 (파일 {files}개, {_size_mb(models):.1f} MB) — 새 feature 정의로 다시 학습")
    if apply:
        shutil.rmtree(models, onexc=_force_remove)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="실제로 바꾼다. 없으면 대상만 센다")
    args = parser.parse_args(argv)
    print("== 적용 ==" if args.apply else "== dry-run: 아무것도 바꾸지 않는다 ==")
    plan_runtime(args.apply)
    plan_research(args.apply)
    plan_models(args.apply)
    if not args.apply:
        print("\n적용하려면 --apply를 붙여 다시 실행한다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
