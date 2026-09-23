"""운영 System 원장의 목표를 5·20·60·120거래일 실현 수익으로 채점해 어느 단계가 틀렸는지 남긴다.

    python -m investment_agent.operations.commands.system_diagnosis

읽기 전용이다. System 원장(`system_targets`의 `stage_trace`)과 가격, 판단 채점 원장만 읽는다. 결과는
`artifacts/research/stage_diagnosis/`에 시각별 파일과 `latest.json`으로 쓴다 — System 단계 진단과
TradingAgents 판단 성적표(논지 적중·확률 보정·기대수익 순위)가 한 파일에 있다. 판정은 기록일 뿐 정책을
바꾸지 않는다 — 규칙을 고치는 것은 사람이 결과를 보고 코드 리뷰로 한다.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import canonical_json

log = get_logger(__name__)

# 한 번에 채점할 목표 수. 주간 재조정이면 약 10년이다.
_TARGET_LIMIT = 520


def default_output_dir() -> Path:
    from investment_agent.platform.storage_paths import repository_root
    return repository_root() / "artifacts" / "research" / "stage_diagnosis"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.operations.commands.system_diagnosis")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    from investment_agent.trading.performance.decision_scorecard import decision_scorecard
    from investment_agent.trading.performance.stage_diagnosis import DIAGNOSIS_HORIZONS, PricePaths, diagnose
    from investment_agent.trading.repository import TradingRepository
    from investment_agent.trading.supabase_repository import SupabaseRepository
    from investment_agent.trading.system.store import SystemPortfolioStore

    targets = SystemPortfolioStore().targets(limit=_TARGET_LIMIT)
    repository = SupabaseRepository()
    now = datetime.now(timezone.utc)
    oldest = min((target.decided_at for target in targets), default=None)
    days = (now - datetime.fromisoformat(oldest.replace("Z", "+00:00"))).days if oldest else 0
    limit = days + max(DIAGNOSIS_HORIZONS) + 30
    # 판단 뒤의 실현 가격으로 채점한다 — 사후 평가라 판단 시각 이후 가격을 읽는 것이 맞다.
    prices = PricePaths(lambda symbol: repository.market_prices(symbol, now, limit=limit))
    report = {
        "generated_at": now.isoformat(),
        **diagnose([(target.decided_at[:10], target.detail.get("stage_trace")) for target in targets], prices),
    }
    ledger = TradingRepository()
    report["decision_scorecard"] = decision_scorecard(ledger.decision_cases(), ledger.evaluation_rows())
    directory = args.output_dir or default_output_dir()
    directory.mkdir(parents=True, exist_ok=True)
    payload = canonical_json(report)
    (directory / f"stage_diagnosis_{now:%Y%m%dT%H%M%SZ}.json").write_text(payload, encoding="utf-8")
    (directory / "latest.json").write_text(payload, encoding="utf-8")
    log.info("system stage diagnosis done %s", canonical_json({
        "traced_targets": report["traced_targets"],
        "untraced_targets": report["untraced_targets"],
        "scored_decisions": report["decision_scorecard"]["scored"],
        "largest_drag": {horizon: row.get("largest_drag") for horizon, row in report["horizons"].items()},
    }))
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
