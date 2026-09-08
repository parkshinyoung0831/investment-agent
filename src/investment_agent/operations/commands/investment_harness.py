"""항상 켜진 로컬 장비용 투자 분석 운영 하네스.

인자 없이 실행하면 상태 파일이나 외부 서비스에 손대지 않고 계획만 출력한다.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from investment_agent.platform.serialization import canonical_json
from investment_agent.platform.logging import configure_logging, get_logger
from investment_agent.operations.harness.contracts import HarnessMode
from investment_agent.operations.harness.health import inspect_health
from investment_agent.operations.harness.kill_switches import default_job_kill_env
from investment_agent.operations.harness.lock import ProcessFileLock
from investment_agent.operations.harness.pipeline import (
    account_risk_snapshot_job,
    autonomous_investment_job,
    continuous_learning_job,
    earnings_watch_job,
    feature_store_job,
    intelligence_job,
    scheduled_analysis_job,
    toss_reconciliation_job,
)
from investment_agent.operations.harness.reporting import DiscordOpsAlert, HarnessReporter
from investment_agent.operations.harness.runtime import HarnessScheduler, JobRegistry
from investment_agent.operations.harness.service import HarnessService
from investment_agent.operations.harness.state import JsonStateStore
from investment_agent.operations.harness_adapters import ProductionInvestmentAdapters

log = get_logger(__name__)
from investment_agent.operations.paths import REPOSITORY_ROOT as _ROOT
from investment_agent.operations.paths import HARNESS_STATE_DIR as _DEFAULT_STATE_DIR


def build_registry(
    *,
    analysis_interval_seconds: float = 24 * 60 * 60,
    investment_interval_seconds: float = 60,
    risk_snapshot_interval_seconds: float = 5 * 60,
    reconciliation_interval_seconds: float = 60,
    earnings_watch_interval_seconds: float = 60,
    feature_store_interval_seconds: float = 24 * 60 * 60,
    intelligence_interval_seconds: float = 24 * 60 * 60,
    adapters: ProductionInvestmentAdapters | None = None,
    interval_seconds: float | None = None,
) -> JobRegistry:
    selected = adapters or ProductionInvestmentAdapters.from_env(
        repository_root=_ROOT,
    )
    if interval_seconds is not None:
        analysis_interval_seconds = interval_seconds
        investment_interval_seconds = interval_seconds
    registry = JobRegistry()
    registry.register(account_risk_snapshot_job(
        snapshot=selected.risk_snapshot,
        interval_seconds=risk_snapshot_interval_seconds,
    ))
    registry.register(scheduled_analysis_job(
        analysis=selected.analysis,
        notify_investment=selected.notify_investment,
        interval_seconds=analysis_interval_seconds,
    ))
    # 공시 수집이라 거래 kill switch·모드와 무관하게 항상 돈다. 노트북이 켜져 있을
    # 때의 1차 경로이고, Actions의 fundamentals_earnings_watch가 안전망이다.
    registry.register(earnings_watch_job(
        watch=selected.watch,
        interval_seconds=earnings_watch_interval_seconds,
    ))
    # 학습 dataset의 원천이라 거래 kill switch·모드와 무관하게 항상 돈다. 하루 거른
    # 날의 PIT snapshot은 원천에 시점 이력이 없어 나중에 되살릴 수 없다.
    registry.register(feature_store_job(
        build_valuations=selected.build_valuations,
        build_features=selected.build_features,
        build_labels=selected.build_labels,
        build_training_samples=selected.build_training_samples,
        evaluate_decisions=selected.evaluate_decisions,
        build_events=selected.build_events,
        interval_seconds=feature_store_interval_seconds,
    ))
    registry.register(autonomous_investment_job(
        select_signal=selected.select_signal,
        portfolio=selected.portfolio,
        execution_intent=selected.execution_intent,
        approval_request=selected.approval_request,
        approval_worker=selected.approval_worker,
        notify_trades=selected.notify_trades,
        interval_seconds=investment_interval_seconds,
    ))
    registry.register(toss_reconciliation_job(
        reconcile=selected.reconcile,
        interval_seconds=reconciliation_interval_seconds,
    ))
    if hasattr(selected, "continuous_learning"):
        registry.register(continuous_learning_job(
            retrain=selected.continuous_learning,
            interval_seconds=feature_store_interval_seconds,
        ))
    # 뉴스·소셜 수집과 90일 보존 정리. 주문이 아니라 데이터 수집이라 거래 kill
    # switch·모드와 무관하게 항상 돈다.
    registry.register(intelligence_job(
        interval_seconds=intelligence_interval_seconds,
        collect_news=getattr(selected, "collect_news", None),
        collect_social=getattr(selected, "collect_social", None),
        prune=getattr(selected, "prune_intelligence", None),
    ))
    return registry


def _emit(payload: dict) -> None:
    data = (canonical_json(payload) + "\n").encode("utf-8")
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        sys.stdout.write(data.decode("utf-8"))
    else:
        stream.write(data)
        stream.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="로컬 투자 분석 운영 하네스")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--run-once", action="store_true", help="한 tick 실행 후 정상 종료")
    action.add_argument("--serve", action="store_true", help="heartbeat loop를 계속 실행")
    action.add_argument("--health", action="store_true", help="checkpoint의 stale 상태만 조회")
    parser.add_argument("--state-dir", default=str(_DEFAULT_STATE_DIR))
    parser.add_argument("--mode", choices=[item.value for item in HarnessMode],
                        default=HarnessMode.ANALYSIS_ONLY.value)
    parser.add_argument("--interval-seconds", type=float, default=None)
    parser.add_argument("--analysis-interval-seconds", type=float, default=24 * 60 * 60)
    parser.add_argument("--investment-interval-seconds", type=float, default=60.0)
    parser.add_argument("--risk-snapshot-interval-seconds", type=float, default=5 * 60)
    parser.add_argument("--reconciliation-interval-seconds", type=float, default=60)
    parser.add_argument("--earnings-watch-interval-seconds", type=float, default=60)
    parser.add_argument("--feature-store-interval-seconds", type=float, default=24 * 60 * 60)
    parser.add_argument("--intelligence-interval-seconds", type=float, default=24 * 60 * 60)
    parser.add_argument("--poll-seconds", type=float, default=15.0)
    parser.add_argument("--adaptive-schedule", action="store_true",
                        help="미국 정규장 시간표(NY Time)에 맞춰 실행 간격을 가변적으로 자동 조절")
    parser.add_argument("--alert-ops", action="store_true",
                        help="health 이상을 로컬 운영 webhook(#로컬-실패)으로 알림")
    args = parser.parse_args(argv)

    configure_logging()
    state_dir = Path(args.state_dir).expanduser().resolve()
    store = JsonStateStore(state_dir / "state.json")
    
    from investment_agent.operations.harness.market_schedule import get_us_market_phase
    phase_info = get_us_market_phase()
    reconciliation_interval = (
        phase_info.suggested_interval_seconds
        if args.adaptive_schedule else args.reconciliation_interval_seconds
    )
    
    registry = build_registry(
        analysis_interval_seconds=args.analysis_interval_seconds,
        investment_interval_seconds=args.investment_interval_seconds,
        risk_snapshot_interval_seconds=args.risk_snapshot_interval_seconds,
        reconciliation_interval_seconds=reconciliation_interval,
        earnings_watch_interval_seconds=args.earnings_watch_interval_seconds,
        feature_store_interval_seconds=args.feature_store_interval_seconds,
        intelligence_interval_seconds=args.intelligence_interval_seconds,
        interval_seconds=args.interval_seconds,
    )
    if args.health:
        report = inspect_health(
            store=store,
            registry=registry,
            now=datetime.now(timezone.utc),
        )
        _emit(report.to_dict())
        if args.alert_ops and not report.healthy:
            HarnessReporter(logger=log, alerts=DiscordOpsAlert(log)).error(
                "harness_unhealthy", health=report.to_dict()
            )
        return 0 if report.healthy else 1
    if not args.run_once and not args.serve:
        _emit({
            "dry_run": True,
            "mode": args.mode,
            "market_phase": phase_info.phase.value,
            "market_description": phase_info.description,
            "adaptive_schedule": args.adaptive_schedule,
            "state_path": str(store.path),
            "lock_path": str((state_dir / "harness.lock").resolve()),
            "jobs": [
                {
                    "job_id": item.job_id,
                    "stages": [stage.stage_id for stage in item.stages],
                    "interval_seconds": item.interval_seconds,
                    "kill_switch_env": item.kill_switch_env or default_job_kill_env(item.job_id),
                }
                for item in registry.definitions()
            ],
            "trading_kill_switch_default": "on",
            "external_calls": False,
            "configured_pipeline": True,
            "discord_gateway_service": "separate",
        })
        return 0

    reporter = HarnessReporter(logger=log, alerts=DiscordOpsAlert(log))
    scheduler = HarnessScheduler(
        registry=registry,
        store=store,
        mode=HarnessMode(args.mode),
        environ=os.environ,
        reporter=reporter,
    )
    service = HarnessService(
        scheduler=scheduler,
        lock=ProcessFileLock(state_dir / "harness.lock"),
        poll_seconds=args.poll_seconds,
        reporter=reporter,
    )
    return service.run_forever() if args.serve else service.run_once()


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
