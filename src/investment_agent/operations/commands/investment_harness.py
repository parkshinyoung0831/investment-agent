"""항상 켜진 로컬 장비용 투자 분석 운영 하네스.

인자 없이 실행하면 상태 파일이나 외부 서비스에 손대지 않고 계획만 출력한다.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from investment_agent.platform.serialization import canonical_json
from investment_agent.platform.logging import configure_logging, get_logger
from investment_agent.operations.harness.contracts import HarnessMode
from investment_agent.operations.harness.health import inspect_health
from investment_agent.operations.harness.kill_switches import default_job_kill_env
from investment_agent.operations.harness.lock import ProcessFileLock
from investment_agent.operations.harness.maintenance import (
    MAINTENANCE_HOLD_EXIT_CODE,
    read_maintenance_hold,
)
from investment_agent.operations.harness.pipeline import (
    account_risk_snapshot_job,
    continuous_learning_job,
    decision_experience_job,
    earnings_watch_job,
    econ_release_watch_job,
    event_reanalysis_job,
    feature_store_job,
    intelligence_job,
    investment_reporting_job,
    ml_challengers_job,
    my_portfolio_follow_job,
    scheduled_analysis_job,
    local_mirror_job,
    system_portfolio_job,
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
    # 보유 후보 판단은 28일간 유효하고 하루 모델 예산은 약 20종목이다. 30분마다 깨워도 할 일이 없고,
    # 깨울 때마다 후보 선정이 500종목 재무를 읽는다. 실패한 회차를 같은 날 다시 시도할 여유만 둔다.
    analysis_interval_seconds: float = 3 * 60 * 60,
    investment_interval_seconds: float = 60,
    risk_snapshot_interval_seconds: float = 5 * 60,
    reconciliation_interval_seconds: float = 60,
    reconciliation_interval_provider: Callable[[datetime], float] | None = None,
    earnings_watch_interval_seconds: float = 60,
    econ_release_watch_interval_seconds: float = 60,
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
    # 경제지표 발표 속보. Actions cron이 수 시간 늦게 도는 것이 실측이라 노트북이 켜져 있을 때의 1차 경로다.
    if hasattr(selected, "watch_releases"):
        registry.register(econ_release_watch_job(
            watch_releases=selected.watch_releases,
            interval_seconds=econ_release_watch_interval_seconds,
        ))
    # Supabase 원본의 로컬 사본. 판단·연구가 종목마다 원격 표를 읽지 않게 한다.
    if hasattr(selected, "sync_local_mirror"):
        registry.register(local_mirror_job(sync_local_mirror=selected.sync_local_mirror))
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
    registry.register(system_portfolio_job(run_system_portfolio=selected.run_system_portfolio))
    registry.register(my_portfolio_follow_job(
        select_target=selected.select_target,
        follow=selected.follow,
        execution_intent=selected.execution_intent,
        approval_request=selected.approval_request,
        approval_worker=selected.approval_worker,
        notify_trades=selected.notify_trades,
        interval_seconds=investment_interval_seconds,
    ))
    registry.register(toss_reconciliation_job(
        reconcile=selected.reconcile,
        interval_seconds=reconciliation_interval_seconds,
        interval_provider=reconciliation_interval_provider,
    ))
    if hasattr(selected, "continuous_learning"):
        if hasattr(selected, "build_decision_experiences"):
            registry.register(decision_experience_job(build_decision_experiences=selected.build_decision_experiences))
        # 학습 자체는 새 성숙 구간이 쌓였을 때만 한다(`continuous_retrain`). 주 1회 확인이면 충분하다.
        registry.register(continuous_learning_job(retrain=selected.continuous_learning))
    if hasattr(selected, "update_performance") and hasattr(selected, "notify_reports"):
        registry.register(investment_reporting_job(update_performance=selected.update_performance, notify_reports=selected.notify_reports))
    if hasattr(selected, "reanalyze_events"):
        registry.register(event_reanalysis_job(reanalyze=selected.reanalyze_events))
    if hasattr(selected, "run_ml_challengers"):
        registry.register(ml_challengers_job(train_challengers=selected.run_ml_challengers))
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
    parser.add_argument("--analysis-interval-seconds", type=float, default=3 * 60 * 60)
    parser.add_argument("--investment-interval-seconds", type=float, default=60.0)
    parser.add_argument("--risk-snapshot-interval-seconds", type=float, default=5 * 60)
    parser.add_argument("--reconciliation-interval-seconds", type=float, default=60)
    parser.add_argument("--earnings-watch-interval-seconds", type=float, default=60)
    parser.add_argument("--econ-release-watch-interval-seconds", type=float, default=60)
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
    # 적응형 주기는 시작 시각 한 번이 아니라 판정 때마다 계산한다 — 밤에 띄운 하네스가 다음 날 장중에도
    # 300초로, 장중에 띄운 하네스가 밤새 60초로 도는 것을 막는다.
    reconciliation_interval_provider = (
        (lambda now: get_us_market_phase(now).suggested_interval_seconds)
        if args.adaptive_schedule else None
    )
    reconciliation_interval = args.reconciliation_interval_seconds
    phase_info = get_us_market_phase()  # 시작 로그용 현재 국면. 주기 결정에는 쓰지 않는다
    
    registry = build_registry(
        analysis_interval_seconds=args.analysis_interval_seconds,
        investment_interval_seconds=args.investment_interval_seconds,
        risk_snapshot_interval_seconds=args.risk_snapshot_interval_seconds,
        reconciliation_interval_seconds=reconciliation_interval,
        reconciliation_interval_provider=reconciliation_interval_provider,
        earnings_watch_interval_seconds=args.earnings_watch_interval_seconds,
        econ_release_watch_interval_seconds=args.econ_release_watch_interval_seconds,
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

    # 정비 보류는 **기동 경로**에서 막아야 한다. 전에는 `harness_switch`와
    # `start_harness_service`만 sentinel을 읽어서, 등록된 Windows Task·launchd 서비스가
    # 로그온·재부팅 때 이 모듈을 직접 불러 그대로 떴다 — 명령이 출력하는 "하네스는
    # 기동하지 않습니다"가 사실이 아니었다(감사 OP2-04). 코드를 고치는 중에 편집 중인
    # 모듈이 subprocess로 실행되는 것도 여기서 막힌다.
    hold = read_maintenance_hold(state_dir)
    if hold is not None:
        _emit({
            "refused": "maintenance_hold",
            "reason": hold.get("reason"),
            "held_at": hold.get("held_at"),
            "hold_id": hold.get("hold_id"),
            "state_dir": str(state_dir),
            "hint": "harness_switch --maintenance off 로 해제한 뒤 다시 기동한다",
        })
        # 서비스가 1분마다 재시작을 시도하므로(RestartOnFailure Count=999) 실패가 아니라
        # "의도된 거부"로 구분되는 코드를 쓴다.
        return MAINTENANCE_HOLD_EXIT_CODE

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
