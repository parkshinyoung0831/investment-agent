"""원본 판단의 당시 신호와 독립적인 비용 반영 가상 성과를 연결한다."""
from __future__ import annotations

import copy
import hashlib
import math
from datetime import datetime, timedelta

from investment_agent.forecasting import SIGNAL_HORIZON_DAYS
from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import parse_datetime, canonical_json
from investment_agent.research.storage.repository import ResearchStore
from investment_agent.research.evaluation.returns import total_return

log = get_logger(__name__)
DATASET_VERSION = "decision_experience_v1"
ACTIONS = ("open", "increase", "hold", "reduce", "exit", "watch", "avoid")


def build_experience(repository, case: dict, *, as_of_at: datetime, horizon_days: int = SIGNAL_HORIZON_DAYS,
                     round_trip_cost_bps: float = 20.0) -> dict | None:
    """다음 날 이후 종가 진입과 완전히 지난 거래일만 사용한다.

    보유 비중을 추측하지 않는 단위 노출 실험이다. open/increase는 1 단위 매수,
    hold는 기존 1 단위 유지, 그 외는 현금이다. reduce의 실제 잔여 비중은 알 수
    없으므로 전량 현금이라는 가정을 명시한다. 원본 target_weight는 실행하지 않는다.
    """
    if horizon_days < 1 or not math.isfinite(round_trip_cost_bps) or round_trip_cost_bps < 0:
        raise ValueError("invalid experience horizon or cost")
    decision_at = parse_datetime(case["as_of_at"])
    recorded_at = parse_datetime(case.get("created_at") or case["as_of_at"])
    if max(decision_at, recorded_at) > as_of_at:
        return None
    original = copy.deepcopy(case.get("final_decision") or {})
    action = str(original.get("signal", original.get("action", "watch")))
    if action not in ACTIONS:
        return None
    scalars = {}
    for key in ("confidence", "probability_up", "expected_excess_return"):
        value = original.get(key)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            return None
        scalars[key] = float(value)
    if not all(0 <= scalars[key] <= 1 for key in ("confidence", "probability_up")):
        return None
    start = max(decision_at, recorded_at).date() + timedelta(days=1)
    paths = []
    for ticker in (str(case["ticker"]), "SPY"):
        rows = repository.price_path(ticker, start, horizon_days + 20)
        paths.append({str(row["trade_date"]): row for row in rows
                      if start <= datetime.fromisoformat(str(row["trade_date"])).date() < as_of_at.date()})
    dates = sorted(set(paths[0]) & set(paths[1]))
    if len(dates) <= horizon_days:
        return None
    asset = total_return([paths[0][key] for key in dates], horizon_days)
    benchmark = total_return([paths[1][key] for key in dates], horizon_days)
    if not math.isfinite(asset) or not math.isfinite(benchmark):
        return None
    exposure = float(action in ("open", "increase", "hold"))
    cost = round_trip_cost_bps / 10000 if action in ("open", "increase") else 0.0
    features = {f"decision_{key}": value for key, value in scalars.items()}
    features.update({f"decision_action_{name}": float(action == name) for name in ACTIONS})
    identity = {"version": DATASET_VERSION, "case_key": str(case["case_key"]),
                "horizon_days": horizon_days, "round_trip_cost_bps": round_trip_cost_bps}
    return {
        "record_key": hashlib.sha256(canonical_json(identity).encode()).hexdigest(),
        "case_key": str(case["case_key"]), "ticker": str(case["ticker"]),
        "as_of_at": decision_at.isoformat(), "decision_available_at": recorded_at.isoformat(),
        "available_at": as_of_at.isoformat(), "horizon_days": horizon_days,
        "start_trade_date": dates[0], "end_trade_date": dates[horizon_days],
        "action": action, **scalars, "features": features,
        "asset_return": asset, "benchmark_return": benchmark, "excess_return": asset-benchmark,
        "net_reward": exposure*asset-cost, "transaction_cost": cost,
        "original_decision": original,
        "provenance": {**identity, "source_kind": case.get("source_kind"),
                       "context_hash": case.get("context_hash"), "run_id": case.get("run_id"),
                       "feature_source": "original_decision", "feature_version": "decision_v1",
                       "decision_sha256": hashlib.sha256(canonical_json(original).encode()).hexdigest(),
                       "reward_kind": "hypothetical_unit_exposure_not_account_pnl",
                       "entry_rule": "next_day_or_later_close_after_decision_available",
                       "flat_actions": ["avoid", "watch", "reduce", "exit"],
                       "overlap_policy": "retain_audit_rows_purge_intervals_before_training"},
    }


def run(
    repository, *, as_of_at: datetime, limit: int = 200, dry_run: bool = False,
    store: ResearchStore | None = None,
) -> int:
    """이미 관측한 경험은 덮어쓰지 않고 신규 성숙 판단만 추가한다."""
    selected_store = store if store is not None else ResearchStore()
    existing = {row["case_key"] for row in selected_store.decision_experience_rows()
                if row.get("provenance", {}).get("version") == DATASET_VERSION}
    saved = 0
    for case in repository.decision_cases_for_experiences():
        if str(case["case_key"]) in existing:
            continue
        row = build_experience(repository, case, as_of_at=as_of_at)
        if row is None:
            continue
        if not dry_run:
            selected_store.save_decision_experiences([row])
        saved += 1
        if saved >= limit:
            break
    return saved
