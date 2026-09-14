"""TradingAgents 종목 분석을 공통 목표 비중과 Risk Gate까지 Shadow 실행한다."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
from datetime import datetime, timedelta, timezone

from investment_agent.trading.decision.constants import DEFAULT_HORIZON_DAYS
from investment_agent.trading.decision.llm.agents.tradingagents_adapter import (
    TradingAgentsDecisionEngine,
    TradingAgentsRunner,
)
from investment_agent.trading.decision.llm.agents.social_source import enabled_social_vendors
from investment_agent.trading.decision.candidate_ranker import validate_live_candidate_as_of
from investment_agent.trading.evidence.context import ContextBuilder
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
    select_model_for_ticker,
)
from investment_agent.trading.portfolio.contracts import CASH_SYMBOL
from investment_agent.platform.serialization import stable_id
from investment_agent.trading.portfolio.optimizer import OptimizerPolicy
from investment_agent.trading.portfolio.proposals import from_optimized_security_proposals
from investment_agent.trading.risk.gate import DeterministicRiskGate, PortfolioRiskPolicy
from investment_agent.trading.portfolio.signal_book import SignalBatch, SignalRecord
from investment_agent.research.rl.serving import (
    default_active_policy_path,
    blend_proposals,
    compute_rl_blend,
)
from investment_agent.research.ml_serving import compute_ml_fusion, default_active_model_path
from investment_agent.trading.decision.signal_blender import SignalBlender
from investment_agent.trading.decision.universe import select_tracked_tickers
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

AGENT_POLICY_KEY = "tradingagents-supabase"
AGENT_POLICY_VERSION = 1


def _effective_proposals(repository, proposals, *, as_of: datetime, model_artifact_id: str):
    """원본 case를 유지하고 실제 신호에 사용한 정책 조합을 별도 승격 대상으로 만든다."""
    outcome = compute_rl_blend(repository, as_of_at=as_of, policy_path=default_active_policy_path(),
                               proposals=proposals, current_weights={CASH_SYMBOL: 1.0})
    effective, outcome = blend_proposals(proposals, blender=SignalBlender(base_rl_weight=0.25, max_rl_weight=0.50),
                                        dsr_probability=outcome.dsr_probability, outcome=outcome)
    log.info("RL signal comparison: %s", outcome.log_payload())
    if not outcome.applied:
        return effective, model_artifact_id
    if not outcome.policy_artifact_id:
        raise RuntimeError("applied RL policy requires immutable artifact identity")
    identity = {"llm_artifact_id": model_artifact_id, "rl_artifact_id": outcome.policy_artifact_id,
                "base_rl_weight": .25, "max_rl_weight": .50, "blender_version": 1}
    artifact_id = stable_id("artifact", identity)
    repository.save_model_artifact({
        "artifact_id": artifact_id, "algorithm": "rule", "feature_version": "llm-ppo-blend-v1",
        "train_start": None, "train_end": None, "seed": None,
        "artifact_uri": str(default_active_policy_path()),
        "sha256": hashlib.sha256(canonical_json(identity).encode()).hexdigest(),
        "params": identity, "code_commit": os.environ.get("GITHUB_SHA"),
    })
    return effective, artifact_id


def _ml_fused_proposals(repository, proposals, *, as_of: datetime, model_artifact_id: str):
    """채택된 ML 모델의 수치 예측을 TradingAgents 의견과 합친다.

    반영되면 신호의 출처가 달라지므로 LLM·ML 조합을 새 artifact로 기록한다. paper/live는
    이 조합 artifact가 사람에게 승격돼야만 실행된다.
    """
    fused, outcome = compute_ml_fusion(
        repository, proposals, as_of_at=as_of, model_path=default_active_model_path(),
    )
    log.info("ML fusion comparison: %s", outcome.log_payload())
    if not outcome.applied:
        return list(proposals), model_artifact_id
    identity = {
        "upstream_artifact_id": model_artifact_id,
        "ml_artifact_id": outcome.model_artifact_id,
        "fusion_version": "ml-tradingagents-fusion-v1",
    }
    artifact_id = stable_id("artifact", identity)
    repository.save_model_artifact({
        "artifact_id": artifact_id, "algorithm": "rule", "feature_version": "ml-tradingagents-fusion-v1",
        "train_start": None, "train_end": None, "seed": None,
        "artifact_uri": str(default_active_model_path()),
        "sha256": hashlib.sha256(canonical_json(identity).encode()).hexdigest(),
        "params": {**identity, "model_confidence": outcome.model_confidence,
                   "feature_as_of_at": outcome.feature_as_of_at},
        "code_commit": os.environ.get("GITHUB_SHA"),
    })
    return fused, artifact_id


def _case_key(ticker: str, as_of_at: datetime) -> str:
    raw = (
        f"{ticker}__{as_of_at.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}__"
        f"{DEFAULT_HORIZON_DAYS}d__"
        f"{AGENT_POLICY_KEY}-v{AGENT_POLICY_VERSION}"
    )
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", raw)


def _model_pool_ledger_path() -> Path:
    configured = os.environ.get("AI_INVESTOR_MODEL_POOL_LEDGER_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(
        os.environ.get("AI_INVESTOR_ARTIFACT_DIR", "artifacts/ai_investor/tradingagents")
    ).expanduser() / "metadata" / "llm-model-usage.sqlite3"


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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.trading.decision.portfolio_shadow")
    parser.add_argument("--ticker", action="append")
    parser.add_argument("--limit", type=int, default=int(os.environ.get("AI_INVESTOR_DAILY_LIMIT", "5")))
    parser.add_argument("--as-of")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


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
    universe = select_tracked_tickers(
        repository,
        args.ticker,
        limit=args.limit,
        as_of_at=as_of,
    )
    tickers = list(universe.selected)
    signal_ttl_hours = int(os.environ.get("AI_INVESTOR_SIGNAL_TTL_HOURS", "24"))
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
    ledger_path = _model_pool_ledger_path()
    risk_policy = PortfolioRiskPolicy()
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
    repository.save_policy({
        "policy_key": risk_policy.key,
        "policy_version": risk_policy.version,
        "stage": "shadow",
        "model_provider": "deterministic_python",
        "model_name": "DeterministicRiskGate",
        "prompt_version": "none",
        "config": risk_policy.to_config(),
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
    for bundle in bundles:
        case_key = _case_key(bundle.ticker, as_of)
        base = {
            "case_key": case_key,
            "run_id": run_id,
            "ticker": bundle.ticker,
            "as_of_at": bundle.as_of_at,
            "horizon_days": DEFAULT_HORIZON_DAYS,
            "policy_key": AGENT_POLICY_KEY,
            "policy_version": AGENT_POLICY_VERSION,
            "source_kind": "live_shadow",
        }
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
            final_decision = {
                **proposal.to_dict(),
                "action": proposal.signal,
                "engine": result.engine,
                "engine_version": result.engine_version,
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
        except Exception as exc:  # noqa: BLE001 - 한 종목 실패 뒤에도 나머지를 평가한다.
            failures.append(f"{bundle.ticker}:{type(exc).__name__}")
            failed_tickers.append(bundle.ticker)
            external_evidence = tuple(getattr(exc, "external_evidence", ()) or ())
            failed_evidence_bundle = {
                **bundle.to_dict(),
                "external_evidence": list(external_evidence),
            }
            archived = archive_case_evidence(
                case_key=case_key,
                evidence_bundle=failed_evidence_bundle,
                role_analyses={},
                code_commit=os.environ.get("GITHUB_SHA"),
            )
            repository.save_case({
                **base,
                "model_provider": "model_pool",
                "model_name": "exhausted",
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
            if isinstance(exc, ModelPoolError):
                # 예산이 없는 상태에서는 나머지 종목을 실패로 위장하지 않고 다음 회차에 남긴다.
                log.warning('analysis paused: model pool budget unavailable; remaining symbols stay pending')
                break

    proposals, model_artifact_id = _effective_proposals(
        repository, proposals, as_of=as_of, model_artifact_id=model_artifact_id,
    )
    proposals, model_artifact_id = _ml_fused_proposals(
        repository, proposals, as_of=as_of, model_artifact_id=model_artifact_id,
    )
    completed_at = datetime.now(timezone.utc)
    batch = SignalBatch(
        batch_id=stable_id("signal_batch", {"run_id": run_id, "as_of_at": as_of.isoformat()}),
        as_of_at=as_of.isoformat(),
        completed_at=completed_at.isoformat(),
        requested_symbols=tuple(tickers),
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

    sectors = repository.sp500_sector_map(tickers)
    portfolio = from_optimized_security_proposals(
        proposals,
        run_id=run_id,
        source_version=runner.version,
        current_weights={CASH_SYMBOL: 1.0},
        case_keys=tuple(successful_case_keys),
        sector_by_symbol=sectors,
        optimizer_policy=OptimizerPolicy(
            max_symbol_weight=risk_policy.max_symbol_weight,
            max_sector_weight=risk_policy.max_sector_weight,
            max_turnover=risk_policy.max_turnover,
            min_cash_weight=risk_policy.min_cash_weight,
        ),
        coverage=(
            "full_portfolio"
            if {proposal.ticker for proposal in proposals} == set(universe.members)
            else "partial_universe"
        ),
    )
    repository.save_portfolio_proposal(portfolio.to_dict())
    risk = DeterministicRiskGate(risk_policy).evaluate(
        portfolio,
        current_weights={CASH_SYMBOL: 1.0},
        tradable_symbols=set(universe.members),
        decided_at=datetime.now(timezone.utc),
        sector_by_symbol=sectors,
    )
    repository.save_risk_decision(risk.to_dict())
    decision_identity = {
        "run_id": run_id,
        "proposal_id": portfolio.proposal_id,
        "risk_decision_id": risk.risk_decision_id,
    }
    repository.save_portfolio_decision({
        "decision_id": stable_id("decision", decision_identity),
        **decision_identity,
        "champion_policy": {
            "source_type": "optimizer",
            "source_version": f"optimizer:{runner.version}",
            "automatic_promotion": False,
        },
        "status": "approved" if risk.is_approved else "rejected",
    })
    repository.finish_decision_run(
        run_id,
        status="partial" if failures else "completed",
    )
    log.info(
        "portfolio shadow done run_id=%s proposals=%d failures=%d risk_approved=%s",
        run_id, len(proposals), len(failures), risk.is_approved,
    )
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
