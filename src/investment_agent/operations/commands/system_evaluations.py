"""최신 System artifact의 승격 증거를 만든다 — 운영 정책의 재현과 운영 NAV를 평가 원장에 쓴다.

    python -m investment_agent.operations.commands.system_evaluations
    python -m investment_agent.operations.commands.system_evaluations --skip-replay   # 운영 NAV만 갱신

수동 승격 게이트는 artifact별 `portfolio_evaluations`만 읽는다. 이 명령이 그 행을 만든다. 승격 자체는 하지
않는다 — `promote_model`로 사람이 한다. 재현은 판단 원장·실계좌에 닿지 않는다.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone

from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import canonical_json

log = get_logger(__name__)

# 재현 시작일. 주간 feature 스냅샷이 이날부터 있다.
REPLAY_START = date(2021, 9, 10)


def _paper_since(ledger, artifact_id: str) -> str | None:
    """artifact가 paper로 승인된 날. 그 뒤의 운영 NAV가 paper 증거다."""
    approved = [row for row in ledger.model_promotions(artifact_id)
                if row.get("status") == "approved" and row.get("to_stage") == "paper" and row.get("approved_at")]
    return min((str(row["approved_at"])[:10] for row in approved), default=None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.operations.commands.system_evaluations")
    parser.add_argument("--skip-replay", action="store_true", help="재현을 건너뛰고 운영 NAV 증거만 갱신한다")
    parser.add_argument("--replay-end", type=date.fromisoformat, default=None,
                        help="재현 종료일. 기본은 가격이 확정된 직전 달 말")
    args = parser.parse_args(argv)

    from investment_agent.research.adapters.trading import open_research_store
    from investment_agent.research.system_validation.ablation import default_variants, run_ablation, unexplained_nav_days
    from investment_agent.research.system_validation.evaluations import (
        artifact_window,
        forward_evaluation_rows,
        replay_evaluation_rows,
    )
    from investment_agent.trading.repository import TradingRepository
    from investment_agent.trading.supabase_repository import SupabaseRepository
    from investment_agent.trading.system.accounting import DailyMark
    from investment_agent.trading.system.store import SystemPortfolioStore
    from investment_agent.trading.system.target import SYSTEM_TARGET_VERSION

    store = SystemPortfolioStore()
    latest = store.latest_target(approved_only=True)
    if latest is None:
        log.info("system evaluations skipped: no approved System target yet")
        return 0
    artifact_id = latest.model_artifact_id
    rows = []

    # 운영 NAV: 이 artifact의 목표가 처음 적용된 날부터. 다른 artifact의 목표가 적용된 구간은 이 증거가 아니다.
    artifact_of = {target.target_id: target.model_artifact_id for target in store.targets(limit=520)}
    window = artifact_window([mark.__dict__ for mark in store.history()], artifact_of, artifact_id)
    if window:
        marks = [DailyMark(**mark) for mark in window]
        rows += forward_evaluation_rows(
            artifact_id=artifact_id, history=window,
            paper_since=_paper_since(TradingRepository(), artifact_id),
            nav_unexplained_days=len(unexplained_nav_days(marks)),
        )

    # 재현은 지금 코드의 정책으로 돈다. artifact가 다른 정책 버전으로 만들어졌다면 그 artifact의 증거가 아니다.
    params = (TradingRepository().model_version(artifact_id) or {}).get("params") or {}
    artifact_policy = params.get("system_version")
    if not args.skip_replay and artifact_policy != SYSTEM_TARGET_VERSION:
        log.warning("replay evidence skipped: artifact policy %s differs from code policy %s",
                    artifact_policy, SYSTEM_TARGET_VERSION)
    elif not args.skip_replay:
        today = datetime.now(timezone.utc).date()
        end = args.replay_end or (today.replace(day=1) - timedelta(days=1))
        champion = next(variant for variant in default_variants() if variant.name == "factor_only")
        report = run_ablation(SupabaseRepository(), start=REPLAY_START, end=end, variants=[champion])
        result = report["variants"][0]
        if result.get("history"):
            rows += replay_evaluation_rows(
                artifact_id=artifact_id, history=result["history"],
                nav_unexplained_days=len(result["coverage"].get("nav_unexplained_days") or ()),
                survivorship_missing_share=result["coverage"].get("survivorship_missing_share"),
                ml_lookahead_refused=result.get("status") == "refused",
                policy_version=SYSTEM_TARGET_VERSION,
            )

    written = open_research_store().save_portfolio_evaluations(rows)
    log.info("system evaluations written %s", canonical_json({
        "artifact_id": artifact_id, "rows": written,
        "kinds": sorted({row["evaluation_kind"] for row in rows}),
    }))
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
