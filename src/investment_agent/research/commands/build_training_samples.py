"""확정된 feature/label을 **비용 반영 학습 표본**으로 바꿔 원장에 쌓는다.

이 entry가 채점과 학습 사이의 다리다. `rl_training_labels`의 forward_return은 비용이
없는 가격 수익률이라 그대로 학습하면 모델이 "많이 굴릴수록 좋다"를 배운다. 여기서
왕복 수수료와 슬리피지를 적용한 net label을 만들고, 두 값을 함께 보관해 나중에
"비용이 판단을 뒤집었는가"를 되짚을 수 있게 한다.
"""
from __future__ import annotations

import argparse
import hashlib
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from investment_agent.platform.cli.runtime import run_log_payload
from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import ContractError, canonical_json, parse_datetime
from investment_agent.research.evaluation.costs import TransactionCostModel
from investment_agent.research.features.layer import FEATURE_VERSION, impute_cross_section
from investment_agent.research.rl.contracts import FeatureSnapshot
from investment_agent.research.evaluation.shadow_fill import round_trip_cost_rate, simulate_shadow_trade
from investment_agent.research.datasets.contracts import TrainingSample
from investment_agent.research.datasets.universe import DataUniverseReader, UniverseRepository, members_over_window
from investment_agent.research.storage.repository import ResearchStore

log = get_logger(__name__)

WORKFLOW = "ai_investor_build_training_samples"
LABEL_DEFINITION = "net_excess_return"
TRAINING_SAMPLE_RUNS_DATASET = "training_sample_runs"
# 비용 비율이 규모와 무관하려면 최소 수수료가 0이어야 한다. 0보다 크면 실제 주문
# 금액을 알아야 하므로 shadow 표본으로는 계산할 수 없다.
_REFERENCE_PRICE = 100.0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.research.commands.build_training_samples")
    parser.add_argument("--lookback-days", type=int, default=365, help="표본을 만들 as_of 창")
    parser.add_argument("--as-of", help="타임존을 포함한 ISO-8601 기준 시각. 기본은 현재 UTC")
    parser.add_argument("--feature-version", default=FEATURE_VERSION)
    parser.add_argument(
        "--commission-rate", type=float, default=0.0005,
        help="체결 금액 대비 수수료율. 기본 0.05%%",
    )
    parser.add_argument(
        "--slippage-bps", type=float, default=5.0,
        help="한 방향 체결 슬리피지(bp). 기본 5bp",
    )
    parser.add_argument("--dry-run", action="store_true", help="계산만 하고 저장하지 않는다")
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


def _period_signature(
    *,
    feature_version: str,
    cost_model: TransactionCostModel,
    rows: list[Mapping[str, Any]],
    labels_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
) -> str:
    """한 기준일 표본의 재계산 필요 여부를 결정하는 안정된 입력 서명이다."""
    inputs = []
    for row in sorted(rows, key=lambda item: str(item["ticker"])):
        key = (str(row["as_of_at"]), str(row["ticker"]))
        label = labels_by_key[key]
        input_hash = row.get("input_hash")
        if not input_hash:
            input_hash = hashlib.sha256(canonical_json({
                "features": row["features"],
                "source_ids": row["source_ids"],
                "provenance": row["provenance"],
            }).encode("utf-8")).hexdigest()
        inputs.append({
            "ticker": key[1],
            "feature_input_hash": str(input_hash),
            "label_id": str(label.get("label_id") or ""),
        })
    payload = {
        "feature_version": feature_version,
        "label_definition": LABEL_DEFINITION,
        "cost_model": cost_model.to_dict(),
        "inputs": inputs,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def build_training_samples(
    *,
    as_of_at: datetime,
    lookback_days: int = 365,
    feature_version: str = FEATURE_VERSION,
    cost_model: TransactionCostModel | None = None,
    dry_run: bool = False,
    repository: UniverseRepository | None = None,
    store: ResearchStore | None = None,
) -> dict[str, object]:
    """label이 확정된 (종목, 시점)마다 비용 반영 학습 표본을 하나씩 만든다."""
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    selected = repository or DataUniverseReader()
    model = cost_model or TransactionCostModel()
    if model.minimum_commission > 0.0:
        raise ContractError(
            "shadow 표본은 주문 금액을 모르므로 minimum_commission이 0일 때만 만들 수 있다"
        )
    window_start = (as_of_at - timedelta(days=lookback_days)).isoformat()
    window_end = as_of_at.isoformat()
    phase = time.monotonic()
    symbols = members_over_window(
        selected,
        start=(as_of_at - timedelta(days=lookback_days)).date(),
        end=as_of_at.date(),
    )
    if not symbols:
        raise RuntimeError("no tracked ticker is available for training samples")

    selected_store = store if store is not None else ResearchStore(read_only=True)
    lightweight_inputs = None
    if hasattr(selected_store, "training_sample_period_inputs"):
        lightweight_inputs = selected_store.training_sample_period_inputs(
            symbols, start_as_of=window_start, end_as_of=window_end,
            feature_version=feature_version, label_cutoff_at=window_end,
        )
        snapshot_rows = lightweight_inputs["snapshots"]
        label_rows = lightweight_inputs["labels"]
    else:
        snapshot_rows = selected_store.rl_feature_snapshot_rows(
            symbols, start_as_of=window_start, end_as_of=window_end,
            feature_version=feature_version,
        )
        label_rows = selected_store.rl_training_label_rows(
            symbols, start_as_of=window_start, end_as_of=window_end,
            feature_version=feature_version, label_cutoff_at=window_end,
        )
    run_rows = selected_store.training_sample_run_rows(
        start_as_of=window_start, end_as_of=window_end,
    )
    if not label_rows:
        # 적재 첫 며칠은 horizon이 아직 안 지나 label이 0건이다. 이건 오류가 아니라
        # "아직 할 일이 없음"이므로 job을 실패시키지 않는다 — 실패로 두면 5거래일 동안
        # 매일 경보가 뜨고, 그 사이 정상 적재된 feature까지 문제로 보인다.
        log.info(
            "no confirmed forward label yet; nothing to sample window=%s..%s",
            window_start, window_end,
        )
        return run_log_payload(
            workflow=WORKFLOW,
            status="success",
            rows_upserted=0,
            tickers_processed=0,
            duration_sec=round(time.monotonic() - started, 3),
            started_at=started_at,
            detail={
                "feature_version": feature_version,
                "label_definition": LABEL_DEFINITION,
                "window": [window_start, window_end],
                "samples": 0,
                "periods": 0,
                "reason": "no_confirmed_label_yet",
                "dry_run": dry_run,
                "timings_sec": {"load": round(time.monotonic() - phase, 3), "compute": 0.0, "write": 0.0},
            },
        )
    phase = time.monotonic()
    signature_labels_by_key = {
        (str(row["as_of_at"]), str(row["ticker"])): row for row in label_rows
    }
    existing_runs = {
        str(row["as_of_at"]): row for row in run_rows
        if row.get("feature_version") == feature_version
        and row.get("label_definition") == LABEL_DEFINITION
    }
    candidates_by_as_of: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in snapshot_rows:
        key = (str(row["as_of_at"]), str(row["ticker"]))
        if key in signature_labels_by_key:
            candidates_by_as_of[key[0]].append(row)

    # 결측 대체는 반드시 같은 시점 안에서만 한다 — 다른 날 값을 끌어오면 미래 정보다.
    by_as_of: dict[str, list[FeatureSnapshot]] = defaultdict(list)
    pending_source_rows: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    pending_run_rows: list[dict[str, Any]] = []
    already_sampled = 0
    for as_of_key, rows in candidates_by_as_of.items():
        signature = _period_signature(
            feature_version=feature_version,
            cost_model=model,
            rows=rows,
            labels_by_key=signature_labels_by_key,
        )
        if existing_runs.get(as_of_key, {}).get("signature") == signature:
            already_sampled += len(rows)
            continue
        if lightweight_inputs:
            pending_source_rows[as_of_key].extend(rows)
        else:
            by_as_of[as_of_key].extend(_snapshot(row) for row in rows)
        pending_run_rows.append({
            "record_key": f"{feature_version}:{LABEL_DEFINITION}:{as_of_key}",
            "as_of_at": as_of_key,
            "feature_version": feature_version,
            "label_definition": LABEL_DEFINITION,
            "signature": signature,
            "sample_count": len(rows),
        })

    if lightweight_inputs and pending_source_rows:
        pending_dates = tuple(pending_source_rows)
        full_snapshot_rows = selected_store.rl_feature_snapshot_rows(
            symbols, start_as_of=window_start, end_as_of=window_end,
            feature_version=feature_version, as_of_values=pending_dates,
        )
        full_label_rows = selected_store.rl_training_label_rows(
            symbols, start_as_of=window_start, end_as_of=window_end,
            feature_version=feature_version, label_cutoff_at=window_end,
            as_of_values=pending_dates,
        )
        labels_by_key = {
            (str(row["as_of_at"]), str(row["ticker"])): row for row in full_label_rows
        }
        snapshots_by_key = {
            (str(row["as_of_at"]), str(row["ticker"])): row for row in full_snapshot_rows
        }
        hydrated: dict[str, list[FeatureSnapshot]] = defaultdict(list)
        for as_of_key, metadata_rows in pending_source_rows.items():
            for metadata in metadata_rows:
                key = (str(metadata["as_of_at"]), str(metadata["ticker"]))
                if key not in snapshots_by_key or key not in labels_by_key:
                    raise RuntimeError("training sample source changed while metadata was being read")
                hydrated[as_of_key].append(_snapshot(snapshots_by_key[key]))
        by_as_of = hydrated
    else:
        labels_by_key = signature_labels_by_key
    load_sec = time.monotonic() - phase
    phase = time.monotonic()

    samples: list[TrainingSample] = []
    flipped = 0
    gross_sum = net_sum = 0.0
    for as_of_key in sorted(by_as_of, key=parse_datetime):
        snapshots = sorted(by_as_of[as_of_key], key=lambda item: item.ticker)
        for snapshot, features in zip(snapshots, impute_cross_section(snapshots)):
            label = labels_by_key[(snapshot.as_of_at, snapshot.ticker)]
            forward_return = float(label["forward_return"])
            result = simulate_shadow_trade(
                ticker=snapshot.ticker,
                entry_at=snapshot.as_of_at,
                exit_at=str(label["forward_end_at"]),
                entry_price=_REFERENCE_PRICE,
                exit_price=_REFERENCE_PRICE * (1.0 + forward_return),
                benchmark_return=float(label["benchmark_forward_return"]),
                cost_model=model,
            )
            # 비용이 초과수익의 부호를 바꾼 표본. 많으면 그 horizon이 비용을 못 이긴다.
            if (result.gross_excess_return > 0) != (result.net_excess_return > 0):
                flipped += 1
            gross_sum += result.gross_excess_return
            net_sum += result.net_excess_return
            samples.append(TrainingSample(
                sample_id="",
                ticker=snapshot.ticker,
                as_of_at=snapshot.as_of_at,
                label_available_at=str(label["label_available_at"]),
                feature_version=feature_version,
                label_definition=LABEL_DEFINITION,
                features=features,
                labels=result.to_labels(),
                provenance={
                    "source": "shadow_simulation",
                    "snapshot_id": snapshot.snapshot_id,
                    "label_id": str(label.get("label_id") or ""),
                    "cost_model": model.to_dict(),
                    "definition_hash": snapshot.provenance.get("definition_hash"),
                },
                outcome_id=result.outcome.outcome_id,
            ))
    compute_sec = time.monotonic() - phase

    phase = time.monotonic()
    saved = 0
    if not dry_run and samples:
        writable_store = store if store is not None else ResearchStore()
        inserted = writable_store.save_training_samples(samples)
        saved = len(samples) if inserted is None else int(inserted)
        if pending_run_rows:
            writable_store.save_training_sample_runs(pending_run_rows)
    write_sec = time.monotonic() - phase

    count = len(samples) or 1
    payload = run_log_payload(
        workflow=WORKFLOW,
        status="success",
        rows_upserted=saved,
        tickers_processed=len({sample.ticker for sample in samples}),
        duration_sec=round(time.monotonic() - started, 3),
        started_at=started_at,
        detail={
            "feature_version": feature_version,
            "label_definition": LABEL_DEFINITION,
            "window": [window_start, window_end],
            "samples": len(samples),
            "periods": len(by_as_of),
            "already_sampled": already_sampled,
            "round_trip_cost_rate": round(round_trip_cost_rate(model), 6),
            "mean_gross_excess": round(gross_sum / count, 6),
            "mean_net_excess": round(net_sum / count, 6),
            "sign_flipped_by_cost": flipped,
            "dry_run": dry_run,
            "timings_sec": {"load": round(load_sec, 3), "compute": round(compute_sec, 3),
                            "write": round(write_sec, 3)},
        },
    )
    log.info("training samples %s", payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.lookback_days < 1:
        raise SystemExit("--lookback-days must be positive")
    as_of_at = parse_datetime(args.as_of) if args.as_of else datetime.now(timezone.utc)
    build_training_samples(
        as_of_at=as_of_at,
        lookback_days=args.lookback_days,
        feature_version=args.feature_version,
        cost_model=TransactionCostModel(
            commission_rate=args.commission_rate,
            slippage_bps=args.slippage_bps,
        ),
        dry_run=args.dry_run,
    )
    return 0


__all__ = [
    "LABEL_DEFINITION", "TRAINING_SAMPLE_RUNS_DATASET", "WORKFLOW",
    "build_training_samples", "main",
]


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
