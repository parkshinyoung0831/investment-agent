"""자율 강화학습 재학습 및 챔피언-챌린저 승격 CLI 진입점.

하네스 스케줄러(continuous_learning_job) 또는 수동 호출로 실행된다. 학습 표본은
`rl_feature_snapshots`·`rl_training_labels`와 역사 membership 원장에서만 온다 —
원장이 비면 대체 표본을 만들지 않고 멈춘다. 합성 표본으로 학습한 정책은 성적표만
그럴듯하고 시장에 대해 아무것도 모른다. 다만 "아직 안 익었다"(forward 구간이 안 닫혀
label이 없다)와 "데이터가 틀렸다"는 다르다 — 전자는 skip(0), 후자만 실패로 올린다.

채점은 학습에 쓰지 않은 뒤쪽 구간(holdout)에서만 한다. 학습 구간에서 채점하면
어떤 정책도 통과하므로 승격 게이트가 아무것도 거르지 못한다.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import canonical_json, parse_datetime
from investment_agent.research.rl.contracts import RLDataNotReadyError
from investment_agent.research.rl.continuous_learner import (
    ContinuousLearner,
    PolicyEvaluationScore,
    PromotionDecision,
)
from investment_agent.research.rl.environment import FeatureDataset, make_gym_environment
from investment_agent.research.rl.features import FeatureSpec, HistoricalTrainingSet, load_training_set
from investment_agent.research.rl.pipeline import split_dataset
from investment_agent.research.features.layer import FEATURE_COLUMNS, FEATURE_VERSION
from investment_agent.platform.storage_paths import repository_root

log = get_logger(__name__)

_ROOT = repository_root()
_POLICY_DIR = _ROOT / "artifacts" / "trading" / "rl_policies"
_ACTIVE_POLICY_NAME = "active_policy.json"
_MODEL_ZIP_NAME = "champion.zip"

# 원장 label은 미래 구간이 끝나야 확정된다. 그 지연만큼 feature 창을 앞당겨야
# "label이 아직 없는 최신 구간"이 통째로 버려지지 않는다.
DEFAULT_LOOKBACK_DAYS = 365
DEFAULT_LABEL_LAG_DAYS = 30
DEFAULT_HOLDOUT_FRACTION = 0.3
# PPO action 축이 종목 수만큼 커진다. 원장이 얕은 동안에는 축을 좁게 유지한다.
DEFAULT_MAX_SYMBOLS = 30


def default_spec() -> FeatureSpec:
    """FeatureLayer가 실제로 적재하는 컬럼과 버전을 그대로 쓴다."""
    return FeatureSpec(version=FEATURE_VERSION, names=FEATURE_COLUMNS)


def _train_with_stable_baselines(dataset: FeatureDataset, *, timesteps: int) -> Any:
    """기본 학습 경로. 무거운 의존성이라 호출 시점에 들여온다."""
    from investment_agent.research.rl.trainer import FinRLTrainer

    trainer = FinRLTrainer(make_gym_environment(dataset))
    log.info("training PPO policy on %d point-in-time periods", len(dataset.as_of_values))
    return trainer.train("ppo", total_timesteps=timesteps, seed=42)


def _load_champion_score(path: Path) -> PolicyEvaluationScore | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        score = payload.get("score", {})
        return PolicyEvaluationScore(
            sharpe_ratio=float(score.get("sharpe_ratio", 0.0)),
            total_reward=float(score.get("total_reward", 0.0)),
            excess_return=float(score.get("excess_return", 0.0)),
            max_drawdown=float(score.get("max_drawdown", 0.0)),
            turnover=float(score.get("turnover", 0.0)),
            dsr_probability=float(score.get("dsr_probability", 0.0)),
            is_statistically_significant=bool(score.get("is_statistically_significant", False)),
            periods_evaluated=int(score.get("periods_evaluated", 0)),
        )
    except (OSError, ValueError, TypeError) as exc:
        log.warning("failed to load prior active policy: %s", exc)
        return None


def _training_set(
    repository: Any,
    *,
    as_of: datetime,
    spec: FeatureSpec,
    lookback_days: int,
    label_lag_days: int,
    max_symbols: int,
) -> HistoricalTrainingSet:
    end = as_of - timedelta(days=label_lag_days)
    start = end - timedelta(days=lookback_days)
    tracked = [str(value).upper() for value in repository.current_tracked_tickers()]
    if not tracked:
        raise RuntimeError("no tracked ticker is available for RL training")
    # 수익률과 무관한 기준(사전순)으로 자른다. 성과로 고르면 생존 편향이 학습에 들어간다.
    symbols = tuple(sorted(tracked)[:max_symbols])
    return load_training_set(
        repository,
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
    min_sharpe_improvement: float = 0.02,
    min_dsr_probability: float = 0.90,
    dry_run: bool = False,
    repository: Any | None = None,
    spec: FeatureSpec | None = None,
    train_policy: Callable[..., Any] | None = None,
    policy_dir: Path | None = None,
) -> PromotionDecision:
    """원장 표본으로 PPO를 학습하고 held-out 구간 성적으로만 승격을 판정한다."""
    as_of = parse_datetime(as_of_at or datetime.now(timezone.utc))
    directory = policy_dir or _POLICY_DIR
    active_path = directory / _ACTIVE_POLICY_NAME
    model_path = directory / _MODEL_ZIP_NAME
    selected_spec = spec or default_spec()
    trainer = train_policy or _train_with_stable_baselines
    log.info(
        "continuous_retrain start: as_of_at=%s timesteps=%d holdout=%.2f",
        as_of.isoformat(), timesteps, holdout_fraction,
    )

    if repository is None:
        from investment_agent.trading.supabase_repository import SupabaseRepository

        repository = SupabaseRepository()

    champion_score = _load_champion_score(active_path)
    training_set = _training_set(
        repository,
        as_of=as_of,
        spec=selected_spec,
        lookback_days=lookback_days,
        label_lag_days=label_lag_days,
        max_symbols=max_symbols,
    )
    train_dataset, holdout_dataset = split_dataset(
        training_set.dataset, holdout_fraction=holdout_fraction
    )
    log.info(
        "training window: symbols=%d train_periods=%d holdout_periods=%d data_hash=%s",
        len(training_set.dataset.symbols),
        len(train_dataset.as_of_values),
        len(holdout_dataset.as_of_values),
        training_set.data_hash[:12],
    )

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

    decision = learner.judge_promotion(challenger_score, champion_score)
    log.info("promotion decision: is_promoted=%s reason=%s", decision.is_promoted, decision.reason)

    if decision.is_promoted and not dry_run:
        directory.mkdir(parents=True, exist_ok=True)
        model.save(str(model_path))
        payload = {
            "policy_version": f"ppo-live-{as_of.date().isoformat()}",
            "promoted_at": as_of.isoformat(),
            "model_binary": _MODEL_ZIP_NAME,
            "score": {
                "sharpe_ratio": challenger_score.sharpe_ratio,
                "total_reward": challenger_score.total_reward,
                "excess_return": challenger_score.excess_return,
                "max_drawdown": challenger_score.max_drawdown,
                "turnover": challenger_score.turnover,
                "dsr_probability": challenger_score.dsr_probability,
                "is_statistically_significant": challenger_score.is_statistically_significant,
                "periods_evaluated": challenger_score.periods_evaluated,
            },
            # 어떤 표본으로 학습했는지 없으면 이 점수를 재현할 수 없다.
            "training": {
                "symbols": list(training_set.dataset.symbols),
                "feature_version": training_set.dataset.feature_version,
                "train_periods": len(train_dataset.as_of_values),
                "holdout_periods": len(holdout_dataset.as_of_values),
                "data_hash": training_set.data_hash,
                "membership_hash": training_set.membership_hash,
            },
            "reason": decision.reason,
        }
        active_path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
        log.info("active policy metadata updated at %s", active_path)

    return decision


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
    parser.add_argument("--dry-run", action="store_true", help="승격 결과를 파일에 쓰지 않는다")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """종료 코드는 "무엇이 잘못됐나"만 말한다.

    승격하지 않은 것도, 원장이 아직 안 익은 것도 정상 결과다. 그걸 1로 내보내면
    하네스가 `failed`로 적고 `#로컬-실패`가 무해한 오류로 덮인다 — 그러면 진짜
    오류가 그 안에 묻힌다. 누수·모양 불일치 같은 실제 안전 위반만 위로 올린다.
    """
    args = _parse_args(argv)
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
        return 0
    log.info(
        "continuous_retrain done: is_promoted=%s reason=%s",
        decision.is_promoted, decision.reason,
    )
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
