"""쌓인 feature·label로 ML 후보 모델을 주기적으로 다시 학습하고 champion과 비교한다.

    python -m investment_agent.research.commands.ml_challengers

## 자동으로 하는 것과 하지 않는 것

학습·검증·비교·기록은 자동이다. **채택은 하지 않는다.** 후보는 `candidates/`에 artifact로 남고
요약(`latest_summary.json`)이 "채택 조건을 통과했는가, champion보다 나은가"를 적는다. 판단 경로가
읽는 `active_ml_model.json`을 바꾸는 것은 `adopt_ml_model` 명령 — 사람의 행위다. 자동 재학습이
검증 없이 실전 신호를 바꾸면, 우연히 좋았던 한 번의 학습이 곧바로 돈을 움직인다.

## 비교 기준

순위 능력의 안정성인 OOS 날짜별 IC의 ICIR(평균 IC / IC 표준편차)이다. 평균 IC만 보면 몇 날의 큰
적중이 나머지를 가린다. 후보는 먼저 채택 조건(`check_adoptable`)을 통과해야 비교 대상이 된다.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import ContractError, canonical_json, parse_datetime
from investment_agent.research.commands.adopt_ml_model import check_adoptable
from investment_agent.research.commands.export_dataset import export_dataset
from investment_agent.research.commands.train_baseline import artifact_document
from investment_agent.research.datasets import ResearchDataset, load_dataset_json
from investment_agent.research.ml_serving import default_active_model_path
from investment_agent.research.rl.contracts import RLSafetyError
from investment_agent.research.training.baseline import train_baseline_dataset
from investment_agent.research.training.walk_forward import purged_row_splits

log = get_logger(__name__)

MODEL_KINDS = ("naive", "ridge", "lightgbm", "xgboost")
# 학습 표본은 주 1회 간격이고 60/20/20으로 나눈다. 2년이면 OOS가 19주라 채택 기준(20일·HAC t)을
# 구조적으로 넘지 못하고, 넘더라도 한 국면의 운이다. 5년이면 OOS가 약 50주다.
DEFAULT_LOOKBACK_DAYS = 1826
_PARAMETERS: Mapping[str, Mapping[str, Any]] = {
    "ridge": {"alpha": 1e-3},
    # 표본이 수만 행 수준이라 얕은 트리·강한 규제로 과적합을 누른다. 튜닝은 challenger 비교가 한다.
    "lightgbm": {"n_estimators": 200, "learning_rate": 0.03, "num_leaves": 15, "min_child_samples": 50,
                 "subsample": 0.8, "subsample_freq": 1, "colsample_bytree": 0.8},
    "xgboost": {"n_estimators": 200, "learning_rate": 0.03, "max_depth": 3, "min_child_weight": 50,
                "subsample": 0.8, "colsample_bytree": 0.8},
}


def default_candidate_dir() -> Path:
    return default_active_model_path().parent / "candidates"


def _icir(payload: Mapping[str, Any] | None) -> float | None:
    alpha = (payload or {}).get("out_of_sample_alpha")
    if not isinstance(alpha, Mapping) or alpha.get("icir") is None:
        return None
    return float(alpha["icir"])


def _load_champion(path: Path) -> Mapping[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("active ML model could not be read for comparison: %s", path)
        return None


def evaluate_candidates(
    dataset: ResearchDataset,
    *,
    kinds: tuple[str, ...] = MODEL_KINDS,
    champion: Mapping[str, Any] | None = None,
    embargo_periods: int = 1,
    train: Callable[..., Any] = train_baseline_dataset,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """모델 종류마다 같은 purged split으로 학습하고 채택 조건·champion 대비를 판정한다."""
    train_split, validation_split, test_split = purged_row_splits(
        dataset, train_ratio=0.60, validation_ratio=0.20, embargo_periods=embargo_periods,
    )
    champion_icir = _icir(champion)
    documents: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for kind in kinds:
        try:
            result = train(
                dataset, model_kind=kind, train_split=train_split, validation_split=validation_split,
                test_split=test_split, parameters=dict(_PARAMETERS.get(kind, {})),
            )
        except RuntimeError as exc:  # 선택 의존성이 없는 환경은 그 종류만 건너뛴다
            rows.append({"model_kind": kind, "status": "unavailable", "reason": str(exc)})
            continue
        document = artifact_document(result, dataset)
        check = check_adoptable(document, comparisons=len(kinds))
        icir = _icir(document)
        beats = bool(check.is_adoptable and icir is not None and (champion_icir is None or icir > champion_icir))
        documents.append(document)
        rows.append({
            "model_kind": kind,
            "status": "trained",
            "artifact_id": document["artifact"]["artifact_id"],
            "is_adoptable": check.is_adoptable,
            "reasons": list(check.reasons),
            "icir": icir,
            "mean_ic": (document.get("out_of_sample_alpha") or {}).get("mean_ic"),
            "beats_champion": beats,
            "constant_features": list(getattr(result, "constant_features", ()) or ()),
        })
    return documents, rows


def run_ml_challengers(
    *,
    now: datetime,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    candidate_dir: Path | None = None,
    active_model_path: Path | None = None,
    export: Callable[..., Any] = export_dataset,
) -> dict[str, Any]:
    target_dir = candidate_dir or default_candidate_dir()
    champion_path = active_model_path or default_active_model_path()
    start = (now - timedelta(days=lookback_days)).isoformat()
    with tempfile.TemporaryDirectory() as scratch:
        dataset_path = Path(scratch) / "dataset.json"
        try:
            export(start_as_of=start, end_as_of=now.isoformat(), label_cutoff_at=now.isoformat(),
                   output=dataset_path)
            dataset = load_dataset_json(dataset_path)
        except (ContractError, ValueError) as exc:
            summary = {"generated_at": now.isoformat(), "status": "insufficient_data", "reason": str(exc)}
            _write_summary(target_dir, summary)
            return summary
    champion = _load_champion(champion_path)
    try:
        documents, rows = evaluate_candidates(dataset, champion=champion)
    except RLSafetyError as exc:
        # label 구간 purge 뒤 검증 창이 남지 않을 만큼 이력이 짧다. 실패가 아니라 아직 이르다는 뜻이다.
        summary = {"generated_at": now.isoformat(), "status": "insufficient_data", "reason": str(exc)}
        _write_summary(target_dir, summary)
        return summary
    target_dir.mkdir(parents=True, exist_ok=True)
    for document in documents:
        path = target_dir / f"{document['artifact']['artifact_id']}.json"
        if not path.exists():
            path.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2, default=str),
                            encoding="utf-8")
    best = max((row for row in rows if row.get("beats_champion")), key=lambda row: row["icir"], default=None)
    summary = {
        "generated_at": now.isoformat(),
        "status": "evaluated",
        "dataset_hash": dataset.dataset_hash,
        "rows": len(dataset.rows),
        "champion_artifact_id": ((champion or {}).get("artifact") or {}).get("artifact_id"),
        "champion_icir": _icir(champion),
        "candidates": rows,
        # 학습 구간에서 변하지 않은 열. split이 같아 종류마다 같으므로 첫 학습 결과의 것을 올린다.
        "constant_features": next((row["constant_features"] for row in rows if row.get("status") == "trained"), []),
        "recommended_artifact_id": best["artifact_id"] if best else None,
        "adoption": "manual: python -m investment_agent.research.commands.adopt_ml_model --artifact <candidate>",
    }
    _write_summary(target_dir, summary)
    return summary


def _write_summary(directory: Path, summary: Mapping[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "latest_summary.json").write_text(
        json.dumps(dict(summary), ensure_ascii=False, sort_keys=True, indent=2, default=str), encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.research.commands.ml_challengers")
    parser.add_argument("--as-of")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    args = parser.parse_args(argv)
    now = parse_datetime(args.as_of) if args.as_of else datetime.now(timezone.utc)
    summary = run_ml_challengers(now=now, lookback_days=args.lookback_days)
    log.info("ml challengers %s", canonical_json(summary))
    return 0


__all__ = ["MODEL_KINDS", "evaluate_candidates", "main", "run_ml_challengers"]


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
