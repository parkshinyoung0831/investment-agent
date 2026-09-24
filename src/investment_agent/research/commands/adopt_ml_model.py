"""학습된 ML artifact를 판단 경로가 읽는 채택 모델로 올린다.

`ml_serving`은 `active_ml_model.json`이 있으면 그 모델을 TradingAgents 의견과 합친다.
그 파일을 손으로 복사하면 검증 없이 아무 artifact나 판단에 들어가므로, 채택은 이 명령(수동)이나
`ml_challengers`(주간 자동)가 같은 `check_adoptable`로만 한다. 판정은 **OOS 날짜별 단면 IC** 기준이다 — RMSE가 좋아도 종목 순위를 못
맞히면 포트폴리오에는 쓸모가 없다.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist
from typing import Any, Mapping

from investment_agent.forecasting import SIGNAL_HORIZON_DAYS
from investment_agent.platform.logging import get_logger
from investment_agent.research.ml_inference import MIN_IC_T_STAT, load_model
from investment_agent.research.ml_serving import default_active_model_path
from investment_agent.platform.serialization import ContractError

log = get_logger(__name__)

# 평균 IC를 믿기 위한 최소 OOS 날짜 수. 한 달 남짓이면 우연히 좋은 구간 하나로 통과한다.
MIN_OOS_DATES = 20


@dataclass(frozen=True)
class AdoptionCheck:
    is_adoptable: bool
    reasons: tuple[str, ...]


def required_t_stat(comparisons: int = 1) -> float:
    """후보를 `comparisons`개 견줘 최고를 고르면 t 문턱도 그만큼 올린다(Bonferroni, 단측 2.0 문턱 기준).

    후보 네 개를 같은 OOS 창에서 비교해 가장 좋은 것을 추천하면 우연히 좋은 하나가 t≥2를 넘는다.
    """
    if comparisons <= 1:
        return MIN_IC_T_STAT
    base_tail = 1.0 - NormalDist().cdf(MIN_IC_T_STAT)
    return max(MIN_IC_T_STAT, NormalDist().inv_cdf(1.0 - base_tail / comparisons))


def check_adoptable(payload: Mapping[str, Any], *, comparisons: int = 1) -> AdoptionCheck:
    reasons: list[str] = []
    try:
        model = load_model(payload)
    except ContractError as exc:
        return AdoptionCheck(False, (f"artifact is not reloadable: {exc}",))
    alpha = payload.get("out_of_sample_alpha")
    if not isinstance(alpha, Mapping):
        return AdoptionCheck(False, ("artifact has no out_of_sample_alpha; retrain with the current trainer",))
    if not model.has_dependence_aware_oos:
        reasons.append("OOS IC requires horizon-matched HAC inference; re-evaluate before explicit adoption")
    mean_ic = float(alpha.get("mean_ic") or 0.0)
    t_stat = float(alpha.get("ic_t_stat") or 0.0)
    dates = int(alpha.get("date_count") or 0)
    if not math.isfinite(mean_ic) or mean_ic <= 0.0:
        reasons.append(f"OOS mean IC must be positive (got {mean_ic:.4f})")
    threshold = required_t_stat(comparisons)
    if not math.isfinite(t_stat) or t_stat < threshold:
        reasons.append(f"OOS IC t-stat must be >= {threshold:.2f} across {comparisons} compared candidate(s) (got {t_stat:.2f})")
    if dates < MIN_OOS_DATES:
        reasons.append(f"OOS must span >= {MIN_OOS_DATES} dates (got {dates})")
    spread = float(alpha.get("mean_quantile_spread") or 0.0)
    if not math.isfinite(spread) or spread <= 0.0:
        reasons.append("top-minus-bottom quantile spread must be positive")
    if model.confidence <= 0.0:
        reasons.append("model confidence resolves to zero")
    if not model.predicts_excess_return:
        reasons.append(f"model must be trained on a benchmark excess-return label (got {model.label_definition or 'unknown'})")
    if model.horizon_days != SIGNAL_HORIZON_DAYS:
        reasons.append(f"model horizon must be {SIGNAL_HORIZON_DAYS}d to be fused (got {model.horizon_days}d)")
    return AdoptionCheck(not reasons, tuple(reasons))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.research.commands.adopt_ml_model")
    parser.add_argument("--artifact", type=Path, required=True, help="train_baseline이 저장한 artifact JSON")
    parser.add_argument("--output", type=Path, default=None, help="채택 경로. 기본은 판단 경로가 읽는 위치")
    parser.add_argument("--dry-run", action="store_true", help="판정만 하고 파일을 쓰지 않는다")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    payload = json.loads(args.artifact.read_text(encoding="utf-8"))
    check = check_adoptable(payload)
    artifact_id = str((payload.get("artifact") or {}).get("artifact_id") or "unknown")
    if not check.is_adoptable:
        log.error("ML artifact not adoptable artifact=%s reasons=%s", artifact_id, list(check.reasons))
        return 1
    if args.dry_run:
        log.info("ML artifact adoptable (dry-run) artifact=%s", artifact_id)
        return 0
    target = args.output or default_active_model_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    temporary.replace(target)
    log.info("ML artifact adopted artifact=%s path=%s", artifact_id, target)
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
