"""학습된 ML artifact를 판단 경로가 읽는 채택 모델로 올린다.

`ml_serving`은 `active_ml_model.json`이 있으면 그 모델을 TradingAgents 의견과 합친다.
그 파일을 손으로 복사하면 검증 없이 아무 artifact나 판단에 들어가므로, 이 명령만이
채택 경로다. 판정은 **OOS 날짜별 단면 IC** 기준이다 — RMSE가 좋아도 종목 순위를 못
맞히면 포트폴리오에는 쓸모가 없다.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from investment_agent.platform.logging import get_logger
from investment_agent.research.ml_inference import MIN_IC_T_STAT, load_model
from investment_agent.research.ml_serving import default_active_model_path
from investment_agent.trading.contracts import ContractError

log = get_logger(__name__)

# 평균 IC를 믿기 위한 최소 OOS 날짜 수. 한 달 남짓이면 우연히 좋은 구간 하나로 통과한다.
MIN_OOS_DATES = 20


@dataclass(frozen=True)
class AdoptionCheck:
    is_adoptable: bool
    reasons: tuple[str, ...]


def check_adoptable(payload: Mapping[str, Any]) -> AdoptionCheck:
    reasons: list[str] = []
    try:
        model = load_model(payload)
    except ContractError as exc:
        return AdoptionCheck(False, (f"artifact is not reloadable: {exc}",))
    alpha = payload.get("out_of_sample_alpha")
    if not isinstance(alpha, Mapping):
        return AdoptionCheck(False, ("artifact has no out_of_sample_alpha; retrain with the current trainer",))
    mean_ic = float(alpha.get("mean_ic") or 0.0)
    t_stat = float(alpha.get("ic_t_stat") or 0.0)
    dates = int(alpha.get("date_count") or 0)
    if not math.isfinite(mean_ic) or mean_ic <= 0.0:
        reasons.append(f"OOS mean IC must be positive (got {mean_ic:.4f})")
    if not math.isfinite(t_stat) or t_stat < MIN_IC_T_STAT:
        reasons.append(f"OOS IC t-stat must be >= {MIN_IC_T_STAT} (got {t_stat:.2f})")
    if dates < MIN_OOS_DATES:
        reasons.append(f"OOS must span >= {MIN_OOS_DATES} dates (got {dates})")
    if float(alpha.get("mean_quantile_spread") or 0.0) <= 0.0:
        reasons.append("top-minus-bottom quantile spread must be positive")
    if model.confidence <= 0.0:
        reasons.append("model confidence resolves to zero")
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
