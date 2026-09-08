"""저장된 feature snapshot과 forward label을 학습용 dataset JSON으로 내보낸다.

`build_features`/`build_labels`가 쌓은 원장과 `train_baseline` 사이를 잇는 유일한
경로다. 원장은 결측을 `None`으로 보존하므로 여기서 시점별 중앙값으로 대체하고,
`<name>__is_missing` 지표를 그대로 남겨 모델이 대체값을 구별할 수 있게 한다.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from investment_agent.operations.runtime import run_log_payload
from investment_agent.platform.logging import get_logger
from investment_agent.trading.contracts import ContractError, parse_datetime
from investment_agent.trading.supabase_repository import SupabaseRepository
from investment_agent.research.features.layer import (
    FEATURE_COLUMNS,
    FEATURE_VERSION,
    HORIZONS,
    impute_cross_section,
)
from investment_agent.research.rl.contracts import FeatureSnapshot
from investment_agent.research.datasets import build_research_dataset

log = get_logger(__name__)

WORKFLOW = "ai_investor_export_dataset"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.research.commands.export_dataset")
    parser.add_argument("--output", type=Path, required=True, help="저장할 dataset JSON 경로")
    parser.add_argument("--start", help="feature as_of 시작(ISO-8601). 기본 --lookback-days 사용")
    parser.add_argument("--end", help="feature as_of 종료(ISO-8601). 기본 현재 UTC")
    parser.add_argument("--lookback-days", type=int, default=1095, help="--start 미지정 시 조회 창")
    parser.add_argument(
        "--label-cutoff",
        help="이 시각까지 확정된 label만 사용한다. 기본 --end와 동일",
    )
    parser.add_argument(
        "--horizon", type=int, default=5, choices=HORIZONS,
        help="label_definition에 기록할 horizon. 원장에 저장된 구간과 일치해야 한다",
    )
    parser.add_argument("--feature-version", default=FEATURE_VERSION)
    parser.add_argument("--dry-run", action="store_true", help="계산만 하고 파일을 쓰지 않는다")
    return parser.parse_args(argv)


def _snapshot(row: Mapping[str, Any]) -> FeatureSnapshot:
    return FeatureSnapshot(
        feature_version=str(row["feature_version"]),
        as_of_at=str(row["as_of_at"]),
        ticker=str(row["ticker"]),
        available_at=str(row["available_at"]),
        is_available=bool(row["is_available"]),
        features=dict(row["features"]),
        source_ids=tuple(row["source_ids"]),
        provenance=dict(row["provenance"]),
    )


def export_dataset(
    *,
    start_as_of: str,
    end_as_of: str,
    label_cutoff_at: str,
    horizon_days: int = 5,
    feature_version: str = FEATURE_VERSION,
    output: Path | None = None,
    repository: SupabaseRepository | None = None,
) -> dict[str, Any]:
    """원장을 읽어 label이 확정된 행만 학습 dataset으로 결합한다."""
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    selected = repository or SupabaseRepository()
    symbols = tuple(selected.current_tracked_tickers())
    if not symbols:
        raise RuntimeError("no tracked ticker is available for dataset export")

    snapshot_rows = selected.rl_feature_snapshot_rows(
        symbols, start_as_of=start_as_of, end_as_of=end_as_of, feature_version=feature_version,
    )
    label_rows = selected.rl_training_label_rows(
        symbols, start_as_of=start_as_of, end_as_of=end_as_of,
        feature_version=feature_version, label_cutoff_at=label_cutoff_at,
    )
    if not snapshot_rows:
        raise ContractError("no feature snapshot is stored for the requested window")
    if not label_rows:
        raise ContractError(
            "no forward label is confirmed before the cutoff; run build_labels first"
        )

    labeled = {(str(row["as_of_at"]), str(row["ticker"])) for row in label_rows}
    by_as_of: dict[str, list[FeatureSnapshot]] = defaultdict(list)
    for row in snapshot_rows:
        key = (str(row["as_of_at"]), str(row["ticker"]))
        if key not in labeled:
            # label이 아직 확정되지 않은 시점은 학습에 쓸 수 없다.
            continue
        by_as_of[str(row["as_of_at"])].append(_snapshot(row))

    if not by_as_of:
        raise ContractError("no feature snapshot has a confirmed label in this window")

    # 대체는 반드시 같은 시점 안에서만 한다 — 다른 날 값을 끌어오면 미래 정보가 섞인다.
    feature_payload: list[dict[str, Any]] = []
    for as_of_at in sorted(by_as_of, key=parse_datetime):
        snapshots = sorted(by_as_of[as_of_at], key=lambda item: item.ticker)
        for snapshot, values in zip(snapshots, impute_cross_section(snapshots)):
            feature_payload.append({
                "ticker": snapshot.ticker,
                "as_of_at": snapshot.as_of_at,
                "available_at": snapshot.available_at,
                "feature_version": snapshot.feature_version,
                "features": values,
                "source_ids": list(snapshot.source_ids),
                "provenance": dict(snapshot.provenance),
            })

    definition = f"forward_return_{horizon_days}d"
    kept = {(row["as_of_at"], row["ticker"]) for row in feature_payload}
    label_payload = [
        {
            "ticker": str(row["ticker"]),
            "as_of_at": str(row["as_of_at"]),
            "forward_end_at": str(row["forward_end_at"]),
            "label_available_at": str(row["label_available_at"]),
            "feature_version": str(row["feature_version"]),
            "label_definition": definition,
            "label": float(row["forward_return"]),
            "benchmark_label": float(row["benchmark_forward_return"]),
        }
        for row in label_rows
        if (str(row["as_of_at"]), str(row["ticker"])) in kept
    ]

    dataset = build_research_dataset(
        feature_payload,
        label_payload,
        feature_version=feature_version,
        label_definition=definition,
        label_cutoff_at=label_cutoff_at,
        feature_names=list(FEATURE_COLUMNS),
    )
    document = {
        "feature_version": feature_version,
        "label_definition": definition,
        "label_cutoff_at": label_cutoff_at,
        "feature_names": list(FEATURE_COLUMNS),
        "feature_rows": feature_payload,
        "label_rows": label_payload,
    }
    # train/validation/test_period은 일부러 쓰지 않는다. 실제 학습 구간은
    # train_baseline이 purged_row_splits로 다시 정하므로, 여기서 추정 구간을 박아두면
    # manifest와 artifact가 서로 다른 기간을 주장하게 된다.
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )

    periods = sorted({row["as_of_at"] for row in feature_payload})
    payload = run_log_payload(
        workflow=WORKFLOW,
        status="success",
        rows_upserted=0,
        tickers_processed=len({row["ticker"] for row in feature_payload}),
        duration_sec=round(time.monotonic() - started, 3),
        started_at=started_at,
        detail={
            "feature_version": feature_version,
            "label_definition": definition,
            "dataset_hash": dataset.dataset_hash,
            "rows": len(dataset.rows),
            "features": len(dataset.feature_names),
            "periods": len(periods),
            "window": [start_as_of, end_as_of],
            "label_cutoff_at": label_cutoff_at,
            "output": str(output) if output else None,
        },
    )
    log.info("dataset export %s", payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.lookback_days < 1:
        raise SystemExit("--lookback-days must be positive")
    end = parse_datetime(args.end) if args.end else datetime.now(timezone.utc)
    start = parse_datetime(args.start) if args.start else end - timedelta(days=args.lookback_days)
    if start >= end:
        raise SystemExit("--start must precede --end")
    cutoff = parse_datetime(args.label_cutoff) if args.label_cutoff else end
    export_dataset(
        start_as_of=start.isoformat(),
        end_as_of=end.isoformat(),
        label_cutoff_at=cutoff.isoformat(),
        horizon_days=args.horizon,
        feature_version=args.feature_version,
        output=None if args.dry_run else args.output,
    )
    return 0


__all__ = ["WORKFLOW", "export_dataset", "main"]


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
