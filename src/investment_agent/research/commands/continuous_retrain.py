"""원본 판단 경험으로 PPO 후보를 학습하고 동일 holdout에서 검증한다.

성숙 label이 없으면 skipped, dry-run 입력 검증은 ready, 실제 후보 학습은 trained다.
연구 게이트 통과는 채택 자격이며 활성 정책은 --adopt-candidate로만 변경한다.

RL은 Research Lab의 도구다. System Portfolio·실계좌 비중을 바꾸지 않고, 현재 비중 결정(결정론적 optimizer)보다
나은 정책이 있는지 같은 데이터·비용으로 비교할 후보만 만든다. 마지막 학습 뒤 새로 성숙한 비중첩 구간이
`min_new_periods`보다 적으면 학습하지 않는다 — 같은 데이터로 매일 다시 학습하면 우연히 좋은 후보만 늘어난다.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Callable

from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import canonical_json, parse_datetime
from investment_agent.research.rl.contracts import RLDataNotReadyError
from investment_agent.research.rl.continuous_learner import (
    ContinuousLearner,
    PromotionDecision,
)
from investment_agent.research.rl.environment import FeatureDataset, make_gym_environment
from investment_agent.research.rl.features import FeatureSpec, HistoricalTrainingSet, load_training_set
from investment_agent.research.rl.pipeline import split_dataset, nonoverlapping_dataset
from investment_agent.research.rl.bundle import load_policy_bundle, save_policy_bundle
from investment_agent.research.features.layer import FEATURE_COLUMNS
from investment_agent.research.datasets.universe import DataUniverseReader
from investment_agent.research.storage.repository import ResearchStore
from investment_agent.platform.storage_paths import rl_policy_dir

log = get_logger(__name__)

_POLICY_DIR = rl_policy_dir()
_ACTIVE_POLICY_NAME = "active_policy.json"
# 마지막으로 후보를 학습한 데이터 구간. 새 성숙 구간이 쌓였는지 판단하는 기준이다.
_LAST_TRAINING_NAME = "last_training.json"
DEFAULT_MIN_NEW_PERIODS = 2

# 원장 label은 미래 구간이 끝나야 확정된다. 그 지연만큼 feature 창을 앞당겨야
# "label이 아직 없는 최신 구간"이 통째로 버려지지 않는다.
DEFAULT_LOOKBACK_DAYS = 365
DEFAULT_LABEL_LAG_DAYS = 30
DEFAULT_HOLDOUT_FRACTION = 0.3
# PPO action 축이 종목 수만큼 커진다. 원장이 얕은 동안에는 축을 좁게 유지한다.
DEFAULT_MAX_SYMBOLS = 30


def default_spec() -> FeatureSpec:
    """FeatureLayer가 실제로 적재하는 컬럼과 버전을 그대로 쓴다."""
    return FeatureSpec(names=FEATURE_COLUMNS)


def _train_with_stable_baselines(dataset: FeatureDataset, *, timesteps: int) -> Any:
    """기본 학습 경로. 무거운 의존성이라 호출 시점에 들여온다."""
    from investment_agent.research.rl.trainer import FinRLTrainer

    trainer = FinRLTrainer(make_gym_environment(dataset))
    log.info("training PPO policy on %d point-in-time periods", len(dataset.as_of_values))
    return trainer.train("ppo", total_timesteps=timesteps, seed=42)


def _last_trained_period(directory: Path) -> str | None:
    path = directory / _LAST_TRAINING_NAME
    if not path.exists():
        return None
    try:
        return str(json.loads(path.read_text(encoding="utf-8"))["latest_period"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _record_training(directory: Path, *, latest_period: str, periods: int, as_of: datetime) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / "last_training.pending.json"
    temporary.write_text(canonical_json({"latest_period": latest_period, "periods": periods,
                                         "trained_at": as_of.isoformat()}) + "\n", encoding="utf-8")
    temporary.replace(directory / _LAST_TRAINING_NAME)


def _training_set(
    repository: Any,
    *,
    store: Any,
    as_of: datetime,
    spec: FeatureSpec,
    lookback_days: int,
    label_lag_days: int,
    max_symbols: int,
) -> HistoricalTrainingSet:
    if hasattr(store, "decision_experience_rows"):
        from investment_agent.research.rl.decision_dataset import decision_training_set
        return decision_training_set(store.decision_experience_rows(as_of_at=as_of),
                                     as_of_at=as_of, max_symbols=max_symbols)
    end = as_of - timedelta(days=label_lag_days)
    start = end - timedelta(days=lookback_days)
    tracked = [str(value).upper() for value in repository.current_tracked_tickers()]
    if not tracked:
        raise RuntimeError("no tracked ticker is available for RL training")
    if len(tracked) > max_symbols:
        # 이름순으로 자르면 A~C로 시작하는 종목군만 남아 섹터·규모가 치우치고, 성과로 고르면 생존 편향이 들어간다.
        # 어느 쪽으로도 조용히 자르지 않고 상한을 올리게 한다(운영 경로는 판단 경험 수 기준 `decision_training_set`).
        raise RuntimeError(f"tracked universe ({len(tracked)}) exceeds max_symbols ({max_symbols})")
    symbols = tuple(sorted(tracked))
    return load_training_set(
        repository,
        store=store,
        symbols=symbols,
        start_as_of=start.isoformat(),
        end_as_of=end.isoformat(),
        label_cutoff_at=as_of.isoformat(),
        spec=spec,
    )


def run_continuous_retrain(
    *,
    as_of_at: str | None = None,
    timesteps: int = 1024,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    label_lag_days: int = DEFAULT_LABEL_LAG_DAYS,
    max_symbols: int = DEFAULT_MAX_SYMBOLS,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
    min_evaluation_periods: int = 20,
    min_sharpe_improvement: float = 0.02,
    min_dsr_probability: float = 0.90,
    min_new_periods: int = DEFAULT_MIN_NEW_PERIODS,
    dry_run: bool = False,
    repository: Any | None = None,
    store: Any | None = None,
    spec: FeatureSpec | None = None,
    train_policy: Callable[..., Any] | None = None,
    policy_dir: Path | None = None,
) -> PromotionDecision:
    """원장 표본으로 PPO를 학습하고 held-out 구간 성적으로만 승격을 판정한다."""
    as_of = parse_datetime(as_of_at or datetime.now(timezone.utc))
    directory = policy_dir or _POLICY_DIR
    active_path = directory / _ACTIVE_POLICY_NAME
    selected_spec = spec or default_spec()
    trainer = train_policy or _train_with_stable_baselines
    log.info(
        "continuous_retrain start: as_of_at=%s timesteps=%d holdout=%.2f",
        as_of.isoformat(), timesteps, holdout_fraction,
    )

    if repository is None:
        repository = DataUniverseReader()
    selected_store = store if store is not None else ResearchStore(read_only=True)

    champion_score = None
    training_set = _training_set(
        repository,
        store=selected_store,
        as_of=as_of,
        spec=selected_spec,
        lookback_days=lookback_days,
        label_lag_days=label_lag_days,
        max_symbols=max_symbols,
    )
    dataset = nonoverlapping_dataset(training_set.dataset, training_set.forward_end_values)
    if len(dataset.as_of_values) < 2:
        raise RLDataNotReadyError("need at least two nonoverlapping decision periods")
    last_trained = _last_trained_period(directory)
    if last_trained is not None:
        fresh = [value for value in dataset.as_of_values if parse_datetime(value) > parse_datetime(last_trained)]
        if len(fresh) < min_new_periods:
            raise RLDataNotReadyError(
                f"only {len(fresh)} new matured periods since the last training (need {min_new_periods})"
            )
    train_dataset, holdout_dataset = split_dataset(dataset, holdout_fraction=holdout_fraction)
    log.info(
        "training window: symbols=%d train_periods=%d holdout_periods=%d data_hash=%s",
        len(training_set.dataset.symbols),
        len(train_dataset.as_of_values),
        len(holdout_dataset.as_of_values),
        training_set.data_hash[:12],
    )

    if min_evaluation_periods < 3:
        raise ValueError("minimum evaluation periods must be at least 3")
    if len(holdout_dataset.as_of_values) < min_evaluation_periods:
        raise RLDataNotReadyError(f"need {min_evaluation_periods} nonoverlapping holdout periods")
    if dry_run:
        return PromotionDecision(False, None, None, 0.0, "학습 입력 준비 완료", status="ready")
    champion = load_policy_bundle(active_path) if active_path.exists() else None
    if champion is not None and (champion.symbols, champion.feature_names) != (holdout_dataset.symbols, holdout_dataset.feature_names):
        raise ValueError("champion axes differ; explicit new research lineage required")
    model = trainer(train_dataset, timesteps=timesteps)
    learner = ContinuousLearner(
        min_sharpe_improvement=min_sharpe_improvement,
        min_dsr_probability=min_dsr_probability,
    )
    challenger_score = learner.evaluate_model(model, holdout_dataset)
    log.info(
        "holdout evaluation: periods=%d sharpe=%.4f excess=%.4f mdd=%.4f dsr_probability=%.4f",
        challenger_score.periods_evaluated,
        challenger_score.sharpe_ratio,
        challenger_score.excess_return,
        challenger_score.max_drawdown,
        challenger_score.dsr_probability,
    )

    if champion is not None:
        champion_score = learner.evaluate_model(champion, holdout_dataset)
    decision = learner.judge_promotion(challenger_score, champion_score)
    log.info("promotion decision: is_promoted=%s reason=%s", decision.is_promoted, decision.reason)

    candidate_path = save_policy_bundle(model, directory, dataset=train_dataset,
        score=asdict(challenger_score), training={
            "symbols": list(train_dataset.symbols),
            "train_periods": len(train_dataset.as_of_values),
            "holdout_periods": len(holdout_dataset.as_of_values),
            "holdout_start": holdout_dataset.as_of_values[0],
            "holdout_end": holdout_dataset.as_of_values[-1],
            "data_hash": training_set.data_hash,
            "membership_hash": training_set.membership_hash,
            "as_of_at": as_of.isoformat(),
            "eligible_for_adoption": decision.is_promoted,
            "learning_objective": "counterfactual_market_policy",
        })
    _record_training(directory, latest_period=str(dataset.as_of_values[-1]),
                     periods=len(dataset.as_of_values), as_of=as_of)
    return replace(decision, candidate_path=str(candidate_path))


def adopt_candidate(candidate_path: Path, *, policy_dir: Path | None = None) -> Path:
    """검증된 후보를 명시적 CLI 요청으로만 채택한다. 실행 플래그는 건드리지 않는다."""
    model = load_policy_bundle(candidate_path)
    if model.metadata["training"].get("eligible_for_adoption") is not True:
        raise ValueError("candidate did not pass the research gate")
    directory = policy_dir or _POLICY_DIR
    directory.mkdir(parents=True, exist_ok=True)
    import shutil
    binary_name = model.metadata["model_binary"]
    source = candidate_path.parent / binary_name
    target = directory / binary_name
    if source.resolve() != target.resolve():
        if target.exists() and target.read_bytes() != source.read_bytes():
            raise ValueError("immutable model collision")
        shutil.copyfile(source, target)
    active = directory / _ACTIVE_POLICY_NAME
    temporary = directory / "active_policy.pending.json"
    temporary.write_text(canonical_json(model.metadata) + "\n", encoding="utf-8")
    temporary.replace(active)
    return active


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.research.commands.continuous_retrain")
    parser.add_argument("--as-of", help="타임존을 포함한 ISO-8601 기준 시각")
    parser.add_argument("--timesteps", type=int, default=1024, help="PPO 학습 타임스텝 수")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--label-lag-days", type=int, default=DEFAULT_LABEL_LAG_DAYS)
    parser.add_argument("--max-symbols", type=int, default=DEFAULT_MAX_SYMBOLS)
    parser.add_argument("--holdout-fraction", type=float, default=DEFAULT_HOLDOUT_FRACTION)
    parser.add_argument("--min-sharpe-improvement", type=float, default=0.02)
    parser.add_argument(
        "--min-dsr-probability",
        "--min-dsr-pvalue",
        dest="min_dsr_probability",
        type=float,
        default=0.90,
    )
    parser.add_argument("--adopt-candidate", type=Path, help="검증된 후보를 명시적으로 채택한다")
    parser.add_argument("--result-path", type=Path, help="하네스에 실제 학습 상태를 전달할 파일")
    parser.add_argument("--dry-run", action="store_true", help="승격 결과를 파일에 쓰지 않는다")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """종료 코드는 "무엇이 잘못됐나"만 말한다.

    승격하지 않은 것도, 원장이 아직 안 익은 것도 정상 결과다. 그걸 1로 내보내면
    하네스가 `failed`로 적고 `#로컬-실패`가 무해한 오류로 덮인다 — 그러면 진짜
    오류가 그 안에 묻힌다. 누수·모양 불일치 같은 실제 안전 위반만 위로 올린다.
    """
    args = _parse_args(argv)
    if args.adopt_candidate is not None:
        if args.dry_run:
            raise ValueError("adoption and dry-run cannot be combined")
        adopt_candidate(args.adopt_candidate)
        return 0
    try:
        decision = run_continuous_retrain(
            as_of_at=args.as_of,
            timesteps=args.timesteps,
            lookback_days=args.lookback_days,
            label_lag_days=args.label_lag_days,
            max_symbols=args.max_symbols,
            holdout_fraction=args.holdout_fraction,
            min_sharpe_improvement=args.min_sharpe_improvement,
            min_dsr_probability=args.min_dsr_probability,
            dry_run=args.dry_run,
        )
    except RLDataNotReadyError as exc:
        log.info("continuous_retrain skipped: %s", exc)
        if args.result_path:
            args.result_path.write_text(canonical_json({'status':'pending', 'reason':str(exc)}), encoding='utf-8')
        return 0
    if args.result_path:
        args.result_path.write_text(canonical_json({'status':decision.status, 'reason':decision.reason,
            'candidate_path':decision.candidate_path, 'eligible_for_adoption':decision.is_promoted}), encoding='utf-8')
    log.info(
        "continuous_retrain done: status=%s is_promoted=%s reason=%s",
        decision.status, decision.is_promoted, decision.reason,
    )
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
