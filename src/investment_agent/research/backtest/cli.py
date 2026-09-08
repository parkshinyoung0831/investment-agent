"""완전한 오프라인 JSON 입력을 결정론적 백테스트 artifact로 변환한다."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from investment_agent.research.backtest import (
    BacktestConfig,
    BacktestRequest,
    CorporateAction,
    MarketBar,
    TransactionCostModel,
    UniverseSnapshot,
    WeightPoint,
    run_backtest,
)
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)
_SCHEMA_VERSION = "ai-backtest-v1"


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def load_backtest_input(path: Path) -> tuple[BacktestRequest, TransactionCostModel]:
    value = _mapping(json.loads(path.read_text(encoding="utf-8")), "backtest input")
    if value.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {_SCHEMA_VERSION}")
    request = _mapping(value.get("request"), "request")
    config = BacktestConfig(**dict(_mapping(request.get("config", {}), "request.config")))
    parsed = BacktestRequest(
        sessions=tuple(request.get("sessions") or ()),
        bars=tuple(MarketBar(**dict(_mapping(row, "bar"))) for row in request.get("bars") or ()),
        weight_points=tuple(
            WeightPoint(**dict(_mapping(row, "weight_point")))
            for row in request.get("weight_points") or ()
        ),
        universe_snapshots=tuple(
            UniverseSnapshot(**dict(_mapping(row, "universe_snapshot")))
            for row in request.get("universe_snapshots") or ()
        ),
        corporate_actions=tuple(
            CorporateAction(**dict(_mapping(row, "corporate_action")))
            for row in request.get("corporate_actions") or ()
        ),
        config=config,
    )
    costs = TransactionCostModel(
        **dict(_mapping(value.get("transaction_costs", {}), "transaction_costs"))
    )
    return parsed, costs


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.research.backtest.cli")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    request, costs = load_backtest_input(args.input)
    result = run_backtest(request, costs=costs)
    output = args.output or Path("artifacts/ai_investor/backtests") / f"{result.artifact_hash}.json"
    _atomic_json(output, {
        "schema_version": _SCHEMA_VERSION,
        "result": result.to_dict(),
    })
    log.info(
        "backtest completed artifact_hash=%s research_only=%s output=%s",
        result.artifact_hash, result.research_only, output,
    )
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())

