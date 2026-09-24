"""쌓인 feature·label로 ML 후보 모델을 주기적으로 다시 학습하고 champion과 비교한다.

    python -m investment_agent.research.commands.ml_challengers

## 채택과 해제는 자동이다

사람이 결정하는 자리는 실계좌를 따라갈지(Discord 승인) 하나다. 모델 교체는 이 명령이 기준으로 한다.

- **채택**: 채택 조건(`check_adoptable` — 비교한 후보 수만큼 올린 HAC t 문턱, OOS 20일 이상 등)을 통과하고
  champion보다 ICIR이 높은 후보를 `active_ml_model.json`에 올린다.
- **해제**: 매주 champion을 이번 OOS 창으로 다시 채점해 순위 능력을 **분명히 잃었으면**(평균 IC ≤ 0 또는
  t < `RETIRE_T_STAT`) 내린다. 채택 문턱보다 낮게 두어, 경계에 걸친 모델이 매주 붙었다 떨어지지 않게 한다.

채택·해제는 운영 채널로 알린다. 우연히 좋았던 학습 하나가 돈을 움직이지 않게 막는 것은 사람이 아니라 문턱이다.

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
# champion 해제 문턱. 채택(단일 비교 2.0, 후보 4개면 2.53)보다 낮은 이력 현상(hysteresis)이다.
RETIRE_T_STAT = 1.0
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
    recheck = champion_recheck(dataset, champion) if champion is not None else None
    # champion이 순위 능력을 잃었으면 그 옛 ICIR은 비교 기준이 아니다. 채택 조건만 넘으면 바로 교체한다.
    champion_is_stale = recheck is not None and recheck.get("status") in {"lost_edge", "unscorable"}
    pool = [row for row in rows if (row.get("is_adoptable") if champion_is_stale else row.get("beats_champion"))]
    best = max(pool, key=lambda row: row["icir"], default=None)
    adoption = _apply_adoption(
        best=next((doc for doc in documents if best and doc["artifact"]["artifact_id"] == best["artifact_id"]), None),
        champion=champion, recheck=recheck, active_path=champion_path, retired_dir=target_dir / "retired",
    )
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
        "champion_recheck": recheck,
        "adoption": adoption,
    }
    _write_summary(target_dir, summary)
    return summary


def champion_recheck(dataset: ResearchDataset, champion: Mapping[str, Any], *,
                     embargo_periods: int = 1) -> dict[str, Any]:
    """champion을 이번 데이터의 OOS 창(후보와 같은 split)으로 다시 채점한다."""
    from investment_agent.research.evaluation.alpha import cross_sectional_alpha_metrics
    from investment_agent.research.ml_inference import load_model
    from investment_agent.research.training.baseline import label_horizon_days, observation_spacing_days

    try:
        model = load_model(champion)
    except ContractError as exc:
        return {"status": "unscorable", "reason": f"champion not reloadable: {exc}"}
    index = {name: position for position, name in enumerate(dataset.feature_names)}
    missing = [name for name in model.feature_names if name not in index]
    if missing:
        return {"status": "unscorable", "reason": f"features no longer produced: {missing[:5]}"}
    _train, _validation, test = purged_row_splits(dataset, train_ratio=0.60, validation_ratio=0.20,
                                                  embargo_periods=embargo_periods)
    rows = list(range(test[0], test[1])) if isinstance(test, tuple) and len(test) == 2 and all(
        isinstance(value, int) for value in test) else list(test)
    matrix = dataset.features[rows][:, [index[name] for name in model.feature_names]]
    dates = [dataset.rows[row].as_of_at for row in rows]
    try:
        score = cross_sectional_alpha_metrics(
            dates, [float(dataset.targets[row]) for row in rows], [float(value) for value in model.predict(matrix)],
            horizon_days=label_horizon_days(dataset.manifest.label_definition),
            sample_spacing_days=observation_spacing_days(dates),
        ).to_dict()
    except ValueError as exc:
        return {"status": "unscorable", "reason": str(exc)}
    mean_ic, t_stat = float(score.get("mean_ic") or 0.0), float(score.get("ic_t_stat") or 0.0)
    lost = mean_ic <= 0.0 or t_stat < RETIRE_T_STAT
    return {"status": "lost_edge" if lost else "holds", "mean_ic": mean_ic, "ic_t_stat": t_stat,
            "date_count": score.get("date_count")}


def _apply_adoption(*, best: Mapping[str, Any] | None, champion: Mapping[str, Any] | None,
                    recheck: Mapping[str, Any] | None, active_path: Path, retired_dir: Path) -> dict[str, Any]:
    """채택 조건을 넘은 더 나은 후보는 올리고, 순위 능력을 잃은 champion은 내린다."""
    from investment_agent.platform.cli.runtime import notify_ops

    champion_id = ((champion or {}).get("artifact") or {}).get("artifact_id")
    if best is not None:
        artifact_id = best["artifact"]["artifact_id"]
        _write_atomically(active_path, best)
        alpha = best.get("out_of_sample_alpha") or {}
        notify_ops(f"ML 모델 자동 채택: {best['artifact'].get('algorithm') or ''} {artifact_id} "
                   f"(OOS IC {float(alpha.get('mean_ic') or 0):.4f}, t {float(alpha.get('ic_t_stat') or 0):.2f})"
                   + (f" — 이전 {champion_id} 교체" if champion_id else ""), logger=log)
        log.info("ML model adopted automatically artifact=%s replaced=%s", artifact_id, champion_id)
        return {"action": "adopted", "artifact_id": artifact_id, "replaced": champion_id}
    if champion is not None and recheck is not None and recheck.get("status") in {"lost_edge", "unscorable"}:
        retired_dir.mkdir(parents=True, exist_ok=True)
        active_path.replace(retired_dir / f"{champion_id or 'champion'}.json")
        notify_ops(f"ML 모델 자동 해제: {champion_id} — {recheck.get('status')} "
                   f"{recheck.get('reason') or ''}(IC {recheck.get('mean_ic')}, t {recheck.get('ic_t_stat')})", logger=log)
        log.info("ML model retired automatically artifact=%s recheck=%s", champion_id, dict(recheck))
        return {"action": "retired", "artifact_id": champion_id, "recheck": dict(recheck)}
    return {"action": "kept" if champion is not None else "none", "artifact_id": champion_id}


def _write_atomically(target: Path, document: Mapping[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(dict(document), ensure_ascii=False, sort_keys=True, indent=2, default=str),
                         encoding="utf-8")
    temporary.replace(target)


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
