"""장 마감 뒤 근거 묶음을 만들고 LLM Shadow 판단을 저장한다."""
from __future__ import annotations

import argparse
import hashlib
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from investment_agent.trading.decision.candidate_ranker import validate_live_candidate_as_of
from investment_agent.trading.evidence.context import ContextBuilder
from investment_agent.trading.contracts import parse_datetime
from investment_agent.platform.serialization import canonical_json
from investment_agent.trading.supabase_repository import SupabaseRepository
from investment_agent.trading.evidence.artifacts import archive_case_evidence
from investment_agent.trading.decision.role_runner import InvestmentHarness
from investment_agent.trading.decision.llm.client import OpenAICompatibleClient
from investment_agent.trading.decision.memory import CaseMemory
from investment_agent.trading.decision.policy import ShadowPolicy
from investment_agent.trading.decision.universe import select_tracked_tickers
from investment_agent.trading.decision.prompts import PROMPT_VERSION
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)


def make_case_key(ticker: str, as_of_at: datetime, horizon_days: int, policy: ShadowPolicy) -> str:
    market_date = as_of_at.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    raw = f"{ticker}__{market_date}__{horizon_days}d__{policy.key}-v{policy.version}"
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", raw)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.trading.decision.shadow_daily")
    parser.add_argument("--ticker", action="append", help="지정 종목만 실행. 여러 번 사용 가능")
    parser.add_argument(
        "--limit", type=int, default=int(os.environ.get("AI_INVESTOR_DAILY_LIMIT", "5")),
        help="한 번에 판단할 최대 종목 수. 초기 비용 보호 기본값 5",
    )
    parser.add_argument("--as-of", help="타임존을 포함한 ISO-8601 판단 시각")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="DB 읽기와 근거 검증만 하고 LLM 호출·판단 저장은 하지 않음",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.limit < 1 or args.limit > 500:
        raise SystemExit("--limit must be between 1 and 500")
    if os.environ.get("AI_INVESTOR_MODE", "shadow").lower() != "shadow":
        raise RuntimeError("Phase 1 only permits AI_INVESTOR_MODE=shadow")

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
    builder = ContextBuilder(repository)
    policy = ShadowPolicy()

    if args.dry_run:
        for ticker in tickers:
            bundle = builder.build(ticker, as_of)
            log.info(
                "ai investor context preview ticker=%s evidence=%d domains=%s missing=%d warnings=%d",
                ticker, len(bundle.evidence), sorted(bundle.domains),
                len(bundle.missing_data), len(bundle.warnings),
            )
        log.info("shadow dry-run done tickers=%d model_calls=0 writes=0", len(tickers))
        return 0

    client = OpenAICompatibleClient.from_env()
    repository.save_policy(policy.to_record(
        model_provider=client.provider,
        model_name=client.model,
        prompt_version=PROMPT_VERSION,
    ))
    harness = InvestmentHarness(client, policy)
    memory = CaseMemory(repository)
    completed = failed = skipped = 0
    for ticker in tickers:
        case_key = make_case_key(ticker, as_of, policy.horizon_days, policy)
        if repository.case_exists(case_key):
            skipped += 1
            log.info("shadow case already exists ticker=%s case_key=%s", ticker, case_key)
            continue
        bundle = builder.build(ticker, as_of)
        evidence_bundle = bundle.to_dict()
        context_hash = hashlib.sha256(canonical_json(evidence_bundle).encode("utf-8")).hexdigest()
        base = {
            "case_key": case_key,
            "ticker": ticker,
            "as_of_at": as_of.isoformat(),
            "horizon_days": policy.horizon_days,
            "policy_key": policy.key,
            "policy_version": policy.version,
            "model_provider": client.provider,
            "model_name": client.model,
            "source_kind": "live_shadow",
            "context_hash": context_hash,
        }
        try:
            result = harness.run(bundle, memory_text=memory.render(ticker, as_of_at=as_of))
            decision = result.decision.to_dict()
            archived = archive_case_evidence(
                case_key=case_key,
                evidence_bundle=evidence_bundle,
                role_analyses=[analysis.to_dict() for analysis in result.analyses],
                code_commit=os.environ.get("GITHUB_SHA"),
            )
            repository.save_case({
                **base,
                "status": "abstained" if decision["action"] in {"avoid", "watch"} else "completed",
                "evidence_bundle": archived.evidence_bundle,
                "role_analyses": archived.role_analyses,
                "final_decision": decision,
                "failure_reason": None,
            })
            if archived.artifact_error:
                log.warning(
                    "decision evidence artifact unavailable ticker=%s case_key=%s: %s",
                    ticker, case_key, archived.artifact_error,
                )
            completed += 1
            log.info(
                "shadow decision saved ticker=%s action=%s confidence=%.3f risk=%.3f case_key=%s",
                ticker, decision["action"], decision["confidence"],
                decision["target_risk_unit"], case_key,
            )
        except Exception as exc:  # noqa: BLE001 - 한 종목 실패가 나머지를 막지 않는다.
            archived = archive_case_evidence(
                case_key=case_key,
                evidence_bundle=evidence_bundle,
                role_analyses=[],
                code_commit=os.environ.get("GITHUB_SHA"),
            )
            repository.save_case({
                **base,
                "status": "failed",
                "evidence_bundle": archived.evidence_bundle,
                "role_analyses": archived.role_analyses,
                "final_decision": None,
                "failure_reason": f"{type(exc).__name__}: {exc}"[:2000],
            })
            if archived.artifact_error:
                log.warning(
                    "failed decision evidence artifact unavailable ticker=%s case_key=%s: %s",
                    ticker, case_key, archived.artifact_error,
                )
            failed += 1
            log.exception("shadow decision failed ticker=%s case_key=%s", ticker, case_key)
    log.info("shadow daily done completed=%d failed=%d skipped=%d", completed, failed, skipped)
    return 1 if failed else 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
