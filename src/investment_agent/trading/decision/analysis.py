"""ALPHA 분석: 선정된 종목을 TradingAgents로 분석해 논지(기대초과수익·확신·근거)를 신호 배치로 남긴다.

비중을 정하지 않는다. System Portfolio가 이 논지를 factor 기대수익의 검증·소폭 조정으로 읽는다
(`trading.decision.alpha`). 수치 ML 예측은 여기서 섞지 않는다 — ALPHA가 factor와 따로 합친다.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import time
from datetime import datetime, timedelta, timezone

from investment_agent.platform.storage_paths import ai_investor_artifact_dir
from investment_agent.platform.env import env_int
from investment_agent.forecasting import SIGNAL_HORIZON_DAYS
from investment_agent.trading.decision.agents.engine import (
    TradingAgentsDecisionEngine,
)
from investment_agent.trading.decision.agents.runner import TradingAgentsRunner
from investment_agent.trading.decision.llm.runtime import (
    TradingAgentsRuntimeError,
    verify_tradingagents_runtime,
)
from investment_agent.trading.decision.llm.social_source import enabled_social_vendors
from investment_agent.trading.decision.candidate_ranker import validate_live_candidate_as_of
from investment_agent.research.adapters.trading import ContextBuilder
from investment_agent.trading.contracts import parse_datetime
from investment_agent.platform.serialization import canonical_json
from investment_agent.trading.supabase_repository import SupabaseRepository
from investment_agent.trading.evidence.artifacts import archive_case_evidence
from investment_agent.trading.decision.llm.client import OpenAICompatibleClient
from investment_agent.trading.decision.memory import CaseMemory
from investment_agent.trading.decision.model_pool import (
    DEFAULT_POOL,
    ModelPoolError,
    apply_candidate,
    remaining_ticker_budget,
    select_model_for_ticker,
)
from investment_agent.platform.serialization import stable_id
from investment_agent.trading.portfolio.signal_book import SignalBatch, SignalRecord
from investment_agent.trading.decision.universe import NoCandidatesDue, select_tracked_tickers
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

AGENT_POLICY_KEY = "tradingagents-supabase"
AGENT_POLICY_VERSION = 1


def _case_key(ticker: str, as_of_at: datetime) -> str:
    raw = (
        f"{ticker}__{as_of_at.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}__"
        f"{SIGNAL_HORIZON_DAYS}d__"
        f"{AGENT_POLICY_KEY}-v{AGENT_POLICY_VERSION}"
    )
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", raw)


def _model_pool_ledger_path() -> Path:
    configured = os.environ.get("AI_INVESTOR_MODEL_POOL_LEDGER_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return ai_investor_artifact_dir() / "metadata" / "llm-model-usage.sqlite3"


def _attempt_case(bundle, memory_text: str, runner: TradingAgentsRunner):
    """`apply_candidate`가 이미 활성화된 상태에서 실제 TradingAgents 호출 한 건을 한다."""
    client = OpenAICompatibleClient.from_env()
    engine = TradingAgentsDecisionEngine(client, runner)
    return engine.run(bundle, memory_text=memory_text)


def _select_and_run(
    bundle,
    *,
    memory_text: str,
    pool,
    ledger_path,
    runner,
    attempt=_attempt_case,
):
    """풀에서 남은 후보를 하나씩 예약·시도해 이 종목의 분석을 완주한다.

    한 후보가 실패하면(예약 자체가 없거나 호출 도중 429/404 등) 다음 후보로 같은
    종목을 다시 시도한다. 예약은 시도 즉시 소진되므로 같은 후보를 두 번 고르지
    않는다. 후보가 하나도 없거나 전부 실패하면 그 종목은 실패로 남긴다 —
    조용히 다른 데이터로 대체하지 않는다.
    """
    last_exc: Exception | None = None
    tried: set[str] = set()
    while True:
        candidate = select_model_for_ticker(
            pool, ledger_path=ledger_path, exclude=frozenset(tried),
        )
        if candidate is None:
            if last_exc is not None:
                raise last_exc
            raise ModelPoolError(
                "no LLM model pool candidate has budget or a configured API key"
            )
        tried.add(candidate.name)
        try:
            with apply_candidate(candidate):
                result = attempt(bundle, memory_text, runner)
            return result, candidate
        except Exception as exc:  # noqa: BLE001 - 다음 후보로 넘어가려면 여기서 잡는다
            last_exc = exc
            log.warning(
                "model pool candidate failed ticker=%s candidate=%s: %s",
                getattr(bundle, "ticker", "?"), candidate.name, type(exc).__name__,
            )


def failure_model(candidate) -> tuple[str, str]:
    """실패한 사례에 남길 (provider, model). 모델이 답한 뒤(제안 검증·저장)에 실패했다면 그 모델이다.

    풀에서 후보를 하나도 못 얻었거나 전부 실패했을 때만 모델이 없어 `exhausted`로 적는다.
    """
    if candidate is None:
        return "model_pool", "exhausted"
    return candidate.provider, candidate.name


def verify_runtime(pool, *, verify=verify_tradingagents_runtime) -> str:
    """키가 설정된 후보마다 실행 환경을 확인하고, 통과한 첫 후보 이름을 돌려준다. 예산은 쓰지 않는다."""
    failures: list[str] = []
    for candidate in pool:
        if not os.environ.get(candidate.api_key_env, "").strip():
            continue
        try:
            with apply_candidate(candidate):
                verify()
            return candidate.name
        except TradingAgentsRuntimeError as exc:
            failures.append(f"{candidate.name}: {exc}")
    raise TradingAgentsRuntimeError("; ".join(failures) or "no LLM model pool candidate has a configured API key")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.trading.decision.analysis")
    parser.add_argument("--ticker", action="append")
    parser.add_argument("--limit", type=int, default=env_int("AI_INVESTOR_DAILY_LIMIT", 5))
    parser.add_argument("--as-of")
    parser.add_argument("--dry-run", action="store_true")
    # 이 시간이 지나면 새 종목을 시작하지 않는다. 하네스가 자기 timeout보다 짧게 넘겨, 강제 종료로
    # 회차 전체(이미 끝낸 종목의 신호까지)를 잃지 않게 한다.
    parser.add_argument("--max-runtime-seconds", type=float)
    return parser.parse_args(argv)


def analysis_limit(requested: int, *, remaining_budget: int) -> int:
    """고를 종목 수 = 요청 한도와 오늘 남은 모델 예산 중 작은 쪽."""
    return max(0, min(int(requested), int(remaining_budget)))


def should_start_next(*, elapsed_seconds: float, longest_case_seconds: float, max_runtime_seconds: float | None) -> bool:
    """가장 오래 걸린 종목만큼 한 번 더 걸려도 시간 안에 끝날 때만 다음 종목을 시작한다."""
    if max_runtime_seconds is None:
        return True
    return elapsed_seconds + longest_case_seconds <= max_runtime_seconds


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.limit < 1 or args.limit > 500:
        raise SystemExit("--limit must be between 1 and 500")
    if os.environ.get("AI_INVESTOR_MODE", "shadow").lower() != "shadow":
        raise RuntimeError("portfolio Shadow entry only permits AI_INVESTOR_MODE=shadow")

    as_of = validate_live_candidate_as_of(
        parse_datetime(args.as_of) if args.as_of else datetime.now(timezone.utc)
    )
    repository = SupabaseRepository()
    limit = args.limit
    if not args.dry_run and not args.ticker:
        limit = analysis_limit(args.limit, remaining_budget=remaining_ticker_budget(
            DEFAULT_POOL, ledger_path=_model_pool_ledger_path(),
        ))
        if limit < 1:
            log.info("analysis skipped: no LLM model budget left today (requested=%d)", args.limit)
            return 0
    try:
        universe = select_tracked_tickers(
            repository,
            args.ticker,
            limit=limit,
            as_of_at=as_of,
        )
    except NoCandidatesDue:
        # 보유 후보의 판단이 모두 아직 유효하다. 배치를 만들지 않으면 하네스가 '할 일 없음'으로 넘긴다.
        log.info("analysis skipped: no candidates are due for analysis as_of=%s", as_of.isoformat())
        return 0
    tickers = list(universe.selected)
    signal_ttl_hours = env_int("AI_INVESTOR_SIGNAL_TTL_HOURS", 24)
    if signal_ttl_hours < 1 or signal_ttl_hours > 72:
        raise RuntimeError("AI_INVESTOR_SIGNAL_TTL_HOURS must be between 1 and 72")
    builder = ContextBuilder(repository)
    bundles = [builder.build(ticker, as_of) for ticker in tickers]
    if args.dry_run:
        for bundle in bundles:
            log.info(
                "portfolio shadow context ticker=%s evidence=%d missing=%d warnings=%d",
                bundle.ticker, len(bundle.evidence), len(bundle.missing_data), len(bundle.warnings),
            )
        return 0

    runner = TradingAgentsRunner()
    pool = DEFAULT_POOL
    # 환경이 깨졌으면 종목마다 같은 실패를 원장에 쌓지 않고 회차를 시작하지 않는다.
    verify_runtime(pool)
    ledger_path = _model_pool_ledger_path()
    repository.save_policy({
        "policy_key": AGENT_POLICY_KEY,
        "policy_version": AGENT_POLICY_VERSION,
        "stage": "shadow",
        # 종목마다 실제로 어떤 모델이 완주시켰는지는 ticker_decisions.model_name에
        # 남는다 — 여기는 그 회차 전체가 어떤 풀로 돌았는지를 남긴다.
        "model_provider": "model_pool",
        "model_name": "rotating",
        "prompt_version": runner.version,
        "config": {
            "engine": TradingAgentsDecisionEngine.name,
            "engine_version": runner.version,
            "model_pool": [candidate.name for candidate in pool],
            "structured_data_vendor": "supabase_as_of_only",
            "external_news_vendor": os.environ.get(
                "AI_INVESTOR_TRADINGAGENTS_NEWS_VENDOR", "yfinance"
            ),
            "external_social_vendors": sorted(enabled_social_vendors()),
            "external_live_only": True,
            "silent_internet_fallback": False,
            "external_raw_storage": (
                "opt_in_local_artifact" if os.environ.get(
                    "AI_INVESTOR_SAVE_EXTERNAL_RAW", "false"
                ).lower() == "true" else "memory_only"
            ),
            "signal_ttl_hours": signal_ttl_hours,
        },
    })

    artifact_payload = {
        "algorithm": "llm",
        "engine": TradingAgentsDecisionEngine.name,
        "engine_version": runner.version,
        "policy_key": AGENT_POLICY_KEY,
        "policy_version": AGENT_POLICY_VERSION,
        "model_provider": "model_pool",
        "model_name": "rotating",
        "feature_version": "supabase-evidence-bundle-v1",
        "code_commit": os.environ.get("GITHUB_SHA"),
    }
    artifact_sha = hashlib.sha256(
        canonical_json(artifact_payload).encode("utf-8")
    ).hexdigest()
    model_artifact_id = stable_id("artifact", artifact_payload)
    repository.save_model_artifact({
        "artifact_id": model_artifact_id,
        "algorithm": "llm",
        "feature_version": "supabase-evidence-bundle-v1",
        "train_start": None,
        "train_end": None,
        "seed": None,
        "artifact_uri": (
            f"db://trading/policies/{AGENT_POLICY_KEY}/{AGENT_POLICY_VERSION}"
        ),
        "sha256": artifact_sha,
        "params": artifact_payload,
        "code_commit": os.environ.get("GITHUB_SHA"),
    })

    run_identity = {
        "as_of_at": as_of.isoformat(),
        "tickers": tickers,
        "engine": TradingAgentsDecisionEngine.name,
        "engine_version": runner.version,
    }
    run_id = stable_id("run", run_identity)
    repository.save_decision_run({
        "run_id": run_id,
        "as_of_at": as_of.isoformat(),
        "stage": "shadow",
        "status": "running",
        "candidate_tickers": tickers,
        "account_snapshot_id": None,
        "code_commit": os.environ.get("GITHUB_SHA"),
        "failure_reason": None,
    })
    memory = CaseMemory(repository)
    proposals = []
    successful_case_keys: list[str] = []
    failures: list[str] = []
    failed_tickers: list[str] = []
    attempted: list[str] = []
    started = time.monotonic()
    longest_case = 0.0
    for bundle in bundles:
        if not should_start_next(elapsed_seconds=time.monotonic() - started, longest_case_seconds=longest_case,
                                 max_runtime_seconds=args.max_runtime_seconds):
            # 시작하지 않은 종목은 실패가 아니다. 배치의 요청 종목에서 빼 다음 회차 후보로 남긴다.
            log.warning("analysis time budget reached; %d tickers left for the next run",
                        len(bundles) - len(attempted))
            break
        attempted.append(bundle.ticker)
        case_started = time.monotonic()
        case_key = _case_key(bundle.ticker, as_of)
        base = {
            "case_key": case_key,
            "run_id": run_id,
            "ticker": bundle.ticker,
            "as_of_at": bundle.as_of_at,
            "horizon_days": SIGNAL_HORIZON_DAYS,
            "policy_key": AGENT_POLICY_KEY,
            "policy_version": AGENT_POLICY_VERSION,
            "source_kind": "live_shadow",
        }
        candidate = None
        try:
            result, candidate = _select_and_run(
                bundle,
                memory_text=memory.render(bundle.ticker, as_of_at=as_of),
                pool=pool,
                ledger_path=ledger_path,
                runner=runner,
            )
            proposal = result.proposal
            proposals.append(proposal)
            successful_case_keys.append(case_key)
            evidence_bundle = {
                **bundle.to_dict(),
                "external_evidence": list(result.external_evidence),
            }
            context_hash = hashlib.sha256(
                canonical_json(evidence_bundle).encode("utf-8")
            ).hexdigest()
            previous = memory.previous_view(bundle.ticker, as_of_at=as_of)
            final_decision = {
                **proposal.to_dict(),
                "action": proposal.signal,
                "engine": result.engine,
                "engine_version": result.engine_version,
                # 판단 사이의 연속성 추적. 방향이 뒤집힌 판단을 사후에 찾아 근거를 검토할 수 있게 한다.
                "previous_case_key": previous["case_key"] if previous else None,
                "previous_signal": previous["signal"] if previous else None,
            }
            archived = archive_case_evidence(
                case_key=case_key,
                evidence_bundle=evidence_bundle,
                role_analyses=result.role_outputs,
                code_commit=os.environ.get("GITHUB_SHA"),
            )
            repository.save_case({
                **base,
                "model_provider": candidate.provider,
                "model_name": candidate.name,
                "status": "abstained" if proposal.signal in {"avoid", "watch"} else "completed",
                "context_hash": context_hash,
                "evidence_bundle": archived.evidence_bundle,
                "role_analyses": archived.role_analyses,
                "final_decision": final_decision,
                "failure_reason": None,
            })
            if archived.artifact_error:
                log.warning(
                    "decision evidence artifact unavailable ticker=%s case_key=%s: %s",
                    bundle.ticker, case_key, archived.artifact_error,
                )
            longest_case = max(longest_case, time.monotonic() - case_started)
        except ModelPoolError as exc:
            # 예산이 바닥나 시작도 못 한 종목은 실패가 아니다. 요청에서 빼 배치를 불완전하게 만들지 않고
            # 다음 회차 후보로 남긴다(같은 날 사건 재분석이 예산을 먼저 쓰면 생긴다).
            attempted.pop()
            log.warning("analysis paused: model budget ran out before %s; remaining tickers stay pending", bundle.ticker)
            break
        except Exception as exc:  # noqa: BLE001 - 한 종목 실패 뒤에도 나머지를 평가한다.
            failures.append(f"{bundle.ticker}:{type(exc).__name__}")
            failed_tickers.append(bundle.ticker)
            external_evidence = tuple(getattr(exc, "external_evidence", ()) or ())
            failed_evidence_bundle = {
                **bundle.to_dict(),
                "external_evidence": list(external_evidence),
            }
            failed_provider, failed_model = failure_model(candidate)
            archived = archive_case_evidence(
                case_key=case_key,
                evidence_bundle=failed_evidence_bundle,
                role_analyses={},
                code_commit=os.environ.get("GITHUB_SHA"),
            )
            repository.save_case({
                **base,
                "model_provider": failed_provider,
                "model_name": failed_model,
                "status": "failed",
                "context_hash": hashlib.sha256(
                    canonical_json(failed_evidence_bundle).encode("utf-8")
                ).hexdigest(),
                "evidence_bundle": archived.evidence_bundle,
                "role_analyses": archived.role_analyses,
                "final_decision": None,
                "failure_reason": f"{type(exc).__name__}: {exc}"[:2000],
            })
            if archived.artifact_error:
                log.warning(
                    "failed decision evidence artifact unavailable ticker=%s case_key=%s: %s",
                    bundle.ticker, case_key, archived.artifact_error,
                )
            log.exception("TradingAgents case failed ticker=%s run_id=%s", bundle.ticker, run_id)
            longest_case = max(longest_case, time.monotonic() - case_started)

    if not attempted:
        repository.finish_decision_run(run_id, status="failed", failure_reason="model budget ran out before any ticker")
        return 0
    completed_at = datetime.now(timezone.utc)
    batch = SignalBatch(
        batch_id=stable_id("signal_batch", {"run_id": run_id, "as_of_at": as_of.isoformat()}),
        as_of_at=as_of.isoformat(),
        completed_at=completed_at.isoformat(),
        # 실제로 시작한 종목만 요청으로 남긴다. 시간·예산으로 시작하지 않은 종목을 넣으면 배치가
        # 영원히 불완전해져 실행 가능한 신호가 생기지 않는다.
        requested_symbols=tuple(attempted),
        successful_symbols=tuple(proposal.ticker for proposal in proposals),
        failed_symbols=tuple(failed_tickers),
        model_artifact_id=model_artifact_id,
    )
    ticker_signals = tuple(
        SignalRecord(
            batch_id=batch.batch_id,
            proposal=proposal,
            recorded_at=completed_at.isoformat(),
            expires_at=(completed_at + timedelta(hours=signal_ttl_hours)).isoformat(),
            case_key=case_key,
        )
        for proposal, case_key in zip(proposals, successful_case_keys, strict=True)
    )
    repository.save_signal_batch(run_id=run_id, batch=batch, records=ticker_signals)

    if not proposals:
        reason = "all TradingAgents cases failed: " + ", ".join(failures)
        repository.finish_decision_run(run_id, status="failed", failure_reason=reason[:2000])
        return 1

    repository.finish_decision_run(
        run_id,
        status="partial" if failures else "completed",
    )
    log.info(
        "thesis analysis done run_id=%s proposals=%d failures=%d",
        run_id, len(proposals), len(failures),
    )
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
