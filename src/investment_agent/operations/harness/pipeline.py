"""투자 판단·승인·계좌 감시 job의 표준 상태머신."""
from __future__ import annotations

from pathlib import Path
from datetime import datetime
from typing import Any, Callable

from investment_agent.operations.harness.contracts import (
    JobDefinition,
    StageContext,
    StageDefinition,
    StageHandler,
    StageOutcome,
)
from investment_agent.platform.logging import get_logger, log_fields

log = get_logger(__name__)


def my_portfolio_follow_job(
    *,
    select_target: StageHandler,
    follow: StageHandler,
    execution_intent: StageHandler,
    approval_request: StageHandler,
    approval_worker: StageHandler,
    notify_trades: StageHandler,
    job_id: str = "my_portfolio_follow",
    interval_seconds: float = 24 * 60 * 60,
    stale_after_seconds: float = 8 * 60 * 60,
    kill_switch_env: str | None = None,
) -> JobDefinition:
    """My Portfolio가 현재 System 목표를 따라갈지 한 번 묻고, 승인되면 실행한다.

    System 목표는 이 job 밖(`system_portfolio`)에서 이미 정해졌다. 여기서는 목표와 실제 계좌의 차이만
    다룬다. ``trading_sensitive`` 단계는 ``approval_workflow`` 모드와 꺼진 전역 kill switch를 모두
    요구한다. Discord Gateway는 이 job 안에서 기다리지 않고 별도 장기 서비스가 interaction을 원장에
    기록한다.
    """
    return JobDefinition(
        job_id=job_id,
        interval_seconds=interval_seconds,
        stale_after_seconds=stale_after_seconds,
        kill_switch_env=kill_switch_env,
        stages=(
            StageDefinition(
                "select_target",
                select_target,
                trading_sensitive=True,
                max_attempts=2,
                retry_delay_seconds=60,
            ),
            StageDefinition(
                "follow",
                follow,
                trading_sensitive=True,
                max_attempts=2,
                retry_delay_seconds=60,
            ),
            StageDefinition(
                "execution_intent",
                execution_intent,
                trading_sensitive=True,
                max_attempts=2,
                retry_delay_seconds=30,
            ),
            StageDefinition(
                "approval_request",
                approval_request,
                trading_sensitive=True,
                max_attempts=1,
            ),
            StageDefinition(
                "approval_worker",
                approval_worker,
                trading_sensitive=True,
                max_attempts=3,
                retry_delay_seconds=30,
            ),
            # 체결 보고. 주문을 내지 않으므로 trading_sensitive가 아니고, 실패해도
            # 이미 나간 주문을 되돌리지 않는다 — 보고 실패로 잡을 뿐이다.
            StageDefinition(
                "notify_trades",
                notify_trades,
                approval_workflow_only=False,
                max_attempts=2,
                retry_delay_seconds=60,
            ),
        ),
    )


def scheduled_analysis_job(
    *,
    analysis: StageHandler,
    notify_investment: StageHandler,
    interval_seconds: float = 24 * 60 * 60,
    stale_after_seconds: float = 8 * 60 * 60,
) -> JobDefinition:
    """kill switch와 무관하게 최신 TradingAgents signal batch를 만든다."""
    return JobDefinition(
        job_id="investment_analysis",
        interval_seconds=interval_seconds,
        stale_after_seconds=stale_after_seconds,
        stages=(
            StageDefinition(
                "analysis",
                analysis,
                max_attempts=2,
                retry_delay_seconds=5 * 60,
            ),
            # 판단 직후 종합·후보 보고서를 보낸다. 발송 실패가 분석 결과를 가리지
            # 않도록 stage 안에서 잡는다(관례 8). 안전망은 Actions cron이다.
            StageDefinition(
                "notify_investment",
                notify_investment,
                max_attempts=2,
                retry_delay_seconds=5 * 60,
            ),
        ),
    )


def earnings_watch_job(
    *,
    watch: StageHandler,
    interval_seconds: float = 60,
    stale_after_seconds: float = 15 * 60,
) -> JobDefinition:
    """발표 세션 창 안에서 관심종목 8-K를 실시간으로 훑는다.

    노트북이 켜져 있을 때의 1차 경로다. 1분 주기로 깨어나되, 수집 창이 닫혀 있으면
    stage 안에서 대상 0건으로 즉시 끝나므로 SEC를 때리지 않는다.

    GitHub Actions의 `fundamentals_earnings_watch`가 같은 진입점을 세션 종료 후에
    한 번 더 돌린다. 둘이 겹쳐도 발송 직전 `notifications.outbox` 선점이 하나만 통과시킨다.
    거래 kill switch와는 무관하다 — 주문이 아니라 공시 수집이다.
    """
    return JobDefinition(
        job_id="earnings_watch",
        interval_seconds=interval_seconds,
        stale_after_seconds=stale_after_seconds,
        stages=(
            StageDefinition(
                "watch",
                watch,
                max_attempts=2,
                retry_delay_seconds=60,
            ),
        ),
    )

def econ_release_watch_job(
    *,
    watch_releases: StageHandler,
    interval_seconds: float = 60,
    stale_after_seconds: float = 15 * 60,
) -> JobDefinition:
    """경제지표 발표 직후의 첫 actual을 잡아 속보로 보낸다.

    Actions의 `econ_calendar_watch`는 15분마다 돌도록 짰지만 GitHub schedule이 수 시간 늦게 도는 것이 실측이라
    한 달에 17번만 돌았다(12:30 UTC 발표 속보가 4시간 뒤에 나갔다). 노트북이 켜져 있을 때의 1차 경로이며,
    발표 시간대 밖에는 stage가 바로 끝난다. Actions는 안전망으로 남고 중복은 알림 원장이 막는다.
    주문이 아니라 데이터 수집이라 거래 kill switch·모드와 무관하다.
    """
    return JobDefinition(
        job_id="econ_release_watch",
        interval_seconds=interval_seconds,
        stale_after_seconds=stale_after_seconds,
        stages=(StageDefinition("watch", watch_releases, max_attempts=2, retry_delay_seconds=60),),
    )


def feature_store_job(
    *,
    build_valuations: StageHandler,
    build_features: StageHandler,
    build_labels: StageHandler,
    build_training_samples: StageHandler,
    evaluate_decisions: StageHandler,
    build_events: StageHandler,
    interval_seconds: float = 24 * 60 * 60,
    stale_after_seconds: float = 30 * 60 * 60,
) -> JobDefinition:
    """서류철·ML/RL의 원천이 되는 PIT 관측값을 매일 적재한다.

    주문이 아니라 데이터 생산이라 거래 kill switch와 무관하다. 순서가 계약이다 —
    밸류에이션이 먼저 쌓여야 feature가 그것을 읽을 수 있고(Phase 3), label은
    feature가 있어야 FK가 성립한다. 하루라도 거르면 그날의 PIT 관측값은 되살릴 수
    없다 — 원천이 시점 이력을 남기지 않는다.
    """
    return JobDefinition(
        job_id="feature_store",
        interval_seconds=interval_seconds,
        stale_after_seconds=stale_after_seconds,
        stages=(
            StageDefinition(
                "build_valuations",
                build_valuations,
                approval_workflow_only=False,
                max_attempts=2,
                retry_delay_seconds=10 * 60,
            ),
            StageDefinition(
                "build_features",
                build_features,
                approval_workflow_only=False,
                max_attempts=2,
                retry_delay_seconds=10 * 60,
            ),
            StageDefinition(
                "build_labels",
                build_labels,
                approval_workflow_only=False,
                max_attempts=2,
                retry_delay_seconds=10 * 60,
            ),
            StageDefinition(
                "build_training_samples",
                build_training_samples,
                approval_workflow_only=False,
                max_attempts=2,
                retry_delay_seconds=10 * 60,
            ),
            # 성숙한 과거 판단을 채점한다. 이 단계가 빠지면 decision_evaluations가
            # 비어 CaseMemory가 항상 "평가된 과거 사례 없음"을 넘긴다 — 즉 에이전트가
            # 자기 성적을 한 번도 못 본다. 같은 horizon은 다시 쓰지 않아 재실행이 안전하다.
            StageDefinition(
                "evaluate_decisions",
                evaluate_decisions,
                approval_workflow_only=False,
                max_attempts=2,
                retry_delay_seconds=10 * 60,
            ),
            # 맨 뒤다. 원천이 90일치 로컬 DuckDB라 실패해도 나중에 다시 만들 수 있고,
            # 앞 단계의 PIT 관측값은 그날을 놓치면 되살릴 수 없다.
            StageDefinition(
                "build_events",
                build_events,
                approval_workflow_only=False,
                max_attempts=2,
                retry_delay_seconds=10 * 60,
            ),
        ),
    )


def account_risk_snapshot_job(
    *,
    snapshot: StageHandler,
    interval_seconds: float = 5 * 60,
    stale_after_seconds: float = 10 * 60,
) -> JobDefinition:
    """실주문과 무관하게 계좌 손익·drawdown 기준점을 주기적으로 보존한다."""
    return JobDefinition(
        job_id="account_risk_snapshot",
        interval_seconds=interval_seconds,
        stale_after_seconds=stale_after_seconds,
        stages=(
            StageDefinition(
                "capture",
                snapshot,
                approval_workflow_only=False,
                max_attempts=2,
                retry_delay_seconds=30,
            ),
        ),
    )


def toss_reconciliation_job(
    *,
    reconcile: StageHandler,
    interval_seconds: float = 60,
    stale_after_seconds: float = 5 * 60,
    interval_provider: Callable[[datetime], float] | None = None,
) -> JobDefinition:
    """kill switch와 무관하게 이미 보낸 주문의 상태만 다시 읽는다."""
    return JobDefinition(
        job_id="toss_reconciliation",
        interval_seconds=interval_seconds,
        stale_after_seconds=stale_after_seconds,
        interval_provider=interval_provider,
        stages=(
            StageDefinition(
                "reconcile",
                reconcile,
                approval_workflow_only=False,
                max_attempts=1,
            ),
        ),
    )


def continuous_learning_job(
    *,
    retrain: StageHandler,
    job_id: str = "continuous_learning",
    interval_seconds: float = 7 * 24 * 60 * 60,
    stale_after_seconds: float = 8 * 24 * 60 * 60,
) -> JobDefinition:
    """RL 연구 후보를 만든다. 새 성숙 구간이 모자라면 학습하지 않고, 채택은 사람이 별도로 한다."""
    return JobDefinition(
        job_id=job_id,
        interval_seconds=interval_seconds,
        stale_after_seconds=stale_after_seconds,
        stages=(
            StageDefinition(
                "retrain",
                retrain,
                approval_workflow_only=False,
                max_attempts=2,
                retry_delay_seconds=30 * 60,
            ),
        ),
    )


def investment_reporting_job(*, update_performance: StageHandler, notify_reports: StageHandler) -> JobDefinition:
    """분석과 주문 실패에도 성과·늦은 체결·누락 알림을 독립적으로 갱신한다."""
    return JobDefinition(job_id="investment_reporting", interval_seconds=300, stale_after_seconds=1800,
        stages=(StageDefinition("update_performance", update_performance, approval_workflow_only=False, max_attempts=2),
                StageDefinition("notify_reports", notify_reports, approval_workflow_only=False, max_attempts=2)))


def local_mirror_job(*, sync_local_mirror: StageHandler, interval_seconds: float = 2 * 60 * 60) -> JobDefinition:
    """Supabase 원본 창고 → 로컬 계산용 사본 증분 동기화. 주문이 아니라 데이터 복사라 거래 kill switch와 무관하다.

    사본이 오래되면 판단 경로가 스스로 Supabase로 돌아가므로, 실패해도 판단은 멈추지 않고 느려질 뿐이다.
    """
    return JobDefinition(job_id="local_mirror", interval_seconds=interval_seconds, stale_after_seconds=30 * 60 * 60,
        stages=(StageDefinition("sync_local_mirror", sync_local_mirror, approval_workflow_only=False,
                                max_attempts=2, retry_delay_seconds=10 * 60),))


def system_portfolio_job(*, run_system_portfolio: StageHandler, interval_seconds: float = 60 * 60) -> JobDefinition:
    """System Portfolio 평가·목표 갱신. 주문을 내지 않으므로 거래 kill switch·모드와 무관하다.

    승인 흐름 밖에서 돌아야 시스템 자신의 판단 성과가 사람의 승인·거절과 섞이지 않는다. 한 시간 주기면
    장 마감 뒤 확정 종가와 밤사이 feature 횡단면을 몇 시간 안에 반영한다.
    """
    return JobDefinition(job_id="system_portfolio", interval_seconds=interval_seconds, stale_after_seconds=6 * 60 * 60,
        stages=(StageDefinition("run_system_portfolio", run_system_portfolio, approval_workflow_only=False,
                                max_attempts=2, retry_delay_seconds=5 * 60),))


def event_reanalysis_job(*, reanalyze: StageHandler, interval_seconds: float = 10 * 60) -> JobDefinition:
    """보유 종목의 새 공시·사건을 정기 분석 주기보다 먼저 다시 본다. 주문은 내지 않는다."""
    return JobDefinition(job_id="event_reanalysis", interval_seconds=interval_seconds, stale_after_seconds=2 * 60 * 60,
        stages=(StageDefinition("reanalyze", reanalyze, approval_workflow_only=False, max_attempts=1),))


def ml_challengers_job(*, train_challengers: StageHandler, interval_seconds: float = 7 * 24 * 60 * 60) -> JobDefinition:
    """ML 후보를 주 1회 다시 학습·비교해 기록한다. 채택은 하지 않으므로 거래 kill switch와 무관하다."""
    return JobDefinition(job_id="ml_challengers", interval_seconds=interval_seconds,
        stale_after_seconds=interval_seconds + 24 * 60 * 60,
        stages=(StageDefinition("train_challengers", train_challengers, approval_workflow_only=False,
                                max_attempts=2, retry_delay_seconds=30 * 60),))


def decision_experience_job(*, build_decision_experiences: StageHandler) -> JobDefinition:
    """feature 수집 장애와 무관하게 이미 저장된 판단의 경험을 완성한다."""
    return JobDefinition(job_id="decision_experience", interval_seconds=86400, stale_after_seconds=108000,
        stages=(StageDefinition("build_decision_experiences", build_decision_experiences,
                                approval_workflow_only=False, max_attempts=2),))


def _collect_news(database_path: Path | None = None) -> dict[str, Any]:
    from investment_agent.intelligence.repository import IntelligenceRepository
    from investment_agent.intelligence.application import collect_news as news_service
    from investment_agent.intelligence.infrastructure.sources.news.yfinance import fetch_ticker_news

    run = news_service.collect_news(
        repository=IntelligenceRepository(database_path),
        fetch=fetch_ticker_news,
        tickers=news_service.watchlist_tickers(),
    )
    return {"status": run.status, "stored": run.stored_count}


def _collect_social(database_path: Path | None = None) -> dict[str, Any]:
    from investment_agent.intelligence.repository import IntelligenceRepository
    from investment_agent.intelligence.application import collect_social as social_service
    from investment_agent.intelligence.domain.catalog import SUBREDDITS
    from investment_agent.intelligence.infrastructure.sources.social.reddit import fetch_new_posts

    run = social_service.collect_social(
        repository=IntelligenceRepository(database_path),
        fetch=fetch_new_posts,
        channels=list(SUBREDDITS),
        tracked=social_service.tracked_tickers(),
    )
    return {"status": run.status, "stored": run.stored_count}


def _prune_intelligence(database_path: Path | None = None) -> dict[str, Any]:
    from investment_agent.intelligence.repository import IntelligenceRepository
    from investment_agent.intelligence.application.retention import prune

    result = prune(IntelligenceRepository(database_path))
    return {"total": result.total, "news": result.news, "social": result.social}


def _intelligence_stage(
    step: Any,
    *,
    step_name: str,
    database_path: Path | None,
) -> StageHandler:
    """단계 하나를 감싸 실패해도 다음 단계로 넘어가게 한다.

    handler가 예외를 올리면 harness는 이 단계를 재시도하며 job 전체를 멈춰
    세운다 — 소셜 provider가 죽었다고 그날 뉴스 수집·정리까지 대기 상태가 되면
    안 된다. 그래서 여기서 잡아 `skipped`로 다음 단계 진행을 허용한다.
    """

    def handler(context: StageContext) -> StageOutcome:
        try:
            result = step(database_path)
        except Exception as error:
            log.warning(
                "intelligence job step failed",
                extra=log_fields(step=step_name, error_type=type(error).__name__),
            )
            return StageOutcome.skipped({"error_type": type(error).__name__})
        return StageOutcome.succeeded(result)

    return handler


def intelligence_job(
    *,
    database_path: Path | None = None,
    interval_seconds: float = 24 * 60 * 60,
    stale_after_seconds: float = 60 * 60,
    collect_news: Any | None = None,
    collect_social: Any | None = None,
    prune: Any | None = None,
) -> JobDefinition:
    """뉴스·소셜을 수집하고 보존 정리를 적용한다.

    세 단계가 서로를 가리지 않게 각각 stage로 나눈다. 소셜 자격증명이 없거나
    provider가 죽었다고 그날 뉴스 수집 결과까지 묻히면, 무엇이 멈췄는지 알 수
    없게 된다. 주문이 아니라 데이터 수집이라 거래 kill switch·모드와 무관하게
    항상 돈다.

    수집 함수를 바깥에서 받는 이유는 다른 job과 같다 — 이 job만 provider를 직접
    들고 있어서, adapters를 통째로 가짜로 넘긴 호출에도 진짜 provider가 섞여
    들어갔다. 그 호출은 실패해도 `skipped`로 삼켜지므로 드러나지 않는다.
    """
    steps = (
        ("news", collect_news or _collect_news),
        ("social", collect_social or _collect_social),
        ("retention", prune or _prune_intelligence),
    )
    return JobDefinition(
        job_id="intelligence",
        interval_seconds=interval_seconds,
        stale_after_seconds=stale_after_seconds,
        stages=tuple(
            StageDefinition(
                name,
                _intelligence_stage(step, step_name=name, database_path=database_path),
                approval_workflow_only=False,
                max_attempts=1,
            )
            for name, step in steps
        ),
    )
