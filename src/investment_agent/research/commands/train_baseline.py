"""선형 Ridge 정책을 Walk-Forward 교차 검증으로 학습하고 평가 아티팩트를 저장한다."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from investment_agent.platform.logging import get_logger
from investment_agent.research.datasets import ResearchDataset, load_dataset_json
from investment_agent.research.training.baseline import train_baseline_dataset
from investment_agent.research.training.walk_forward import purged_row_splits

log = get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.research.commands.train_baseline")
    parser.add_argument("--dataset", type=Path, help="Feature/label dataset JSON for actual training")
    parser.add_argument(
        "--model",
        choices=("naive", "ridge", "lightgbm", "xgboost"),
        default="ridge",
        help="Numeric expected-return baseline",
    )
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed")
    parser.add_argument("--ridge-alpha", type=float, default=1e-3, help="Ridge L2 regularization strength")
    parser.add_argument("--output-dir", type=str, default="artifacts/models", help="Directory to save policy files")
    parser.add_argument(
        "--embargo-periods", type=int, default=1,
        help="train/validation 사이에 비워 둘 시점 수. label 구간 purge와 별개의 여유",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate dataset and splits without saving")
    return parser.parse_args(argv)


def _default_splits(
    dataset: ResearchDataset,
    *,
    embargo_periods: int = 1,
) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    """시점 경계로 60/20/20을 나누고 label이 겹치는 시점을 purge한다.

    행 번호로 자르면 같은 날짜의 종목이 train과 validation으로 쪼개지고, horizon
    길이만큼 train label이 validation 구간에서 확정된다. 둘 다 누수다.
    """
    return purged_row_splits(
        dataset,
        train_ratio=0.60,
        validation_ratio=0.20,
        embargo_periods=embargo_periods,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    log.info(
        "Starting numeric baseline training model=%s seed=%d alpha=%f",
        args.model,
        args.seed,
        args.ridge_alpha,
    )
    if args.dataset is None:
        if args.dry_run:
            log.info("Dry-run completed: no dataset supplied; no artifact was written")
            return 0
        log.error("--dataset is required for non-dry-run baseline training")
        return 2

    dataset = load_dataset_json(args.dataset)
    train_split, validation_split, test_split = _default_splits(
        dataset, embargo_periods=args.embargo_periods,
    )
    log.info(
        "Dataset validated rows=%d feature_version=%s hash=%s splits=%s/%s/%s",
        len(dataset.rows),
        dataset.manifest.feature_version,
        dataset.dataset_hash,
        train_split,
        validation_split,
        test_split,
    )
    if args.dry_run:
        log.info("Dry-run completed: PIT cutoff and non-overlapping splits validated")
        return 0

    result = train_baseline_dataset(
        dataset,
        model_kind=args.model,
        train_split=train_split,
        validation_split=validation_split,
        test_split=test_split,
        parameters={"alpha": args.ridge_alpha} if args.model == "ridge" else {},
        random_seed=args.seed,
    )
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_state = getattr(result.model, "state", lambda: {})()
    artifact_payload = {
        "artifact": result.artifact.to_record(),
        "model_state": model_state,
        "dataset_manifest": dataset.manifest.to_dict(),
        "feature_names": list(dataset.feature_names),
        "splits": {
            "train": list(result.train_indexes),
            "validation": list(result.validation_indexes),
            "test": list(result.test_indexes),
        },
    }
    output_path = out_dir / f"{result.artifact.artifact_id}.json"
    output_path.write_text(
        json.dumps(artifact_payload, ensure_ascii=False, sort_keys=True, indent=2, default=str),
        encoding="utf-8",
    )
    log.info("Baseline artifact saved: %s", output_path)
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
