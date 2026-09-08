"""한 LLM을 여섯 역할로 순차 실행하는 근거 기반 하네스."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from investment_agent.trading.contracts import (
    DECISION_OUTPUT_SCHEMA,
    ROLE_OUTPUT_SCHEMA,
    EvidenceBundle,
    InvestmentDecision,
    RoleAnalysis,
)
from investment_agent.platform.serialization import canonical_json
from investment_agent.trading.decision.llm.client import LLMClient
from investment_agent.trading.decision.policy import ShadowPolicy
from investment_agent.trading.decision.prompts import COMMON_SYSTEM, PORTFOLIO_INSTRUCTION, ROLE_INSTRUCTIONS


@dataclass(frozen=True)
class HarnessResult:
    analyses: tuple[RoleAnalysis, ...]
    decision: InvestmentDecision

    def to_dict(self) -> dict[str, Any]:
        return {
            "analyses": [analysis.to_dict() for analysis in self.analyses],
            "decision": self.decision.to_dict(),
        }


def _domain_bundle(bundle: EvidenceBundle, domains: set[str]) -> dict[str, Any]:
    return {
        "ticker": bundle.ticker,
        "as_of_at": bundle.as_of_at,
        "source_kind": bundle.source_kind,
        "evidence": [
            item.to_dict() for item in bundle.evidence if item.domain in domains
        ],
        "missing_data": list(bundle.missing_data),
        "warnings": list(bundle.warnings),
    }


class InvestmentHarness:
    ROLE_ORDER = (
        "researcher",
        "fundamental_analyst",
        "market_analyst",
        "macro_news_analyst",
        "skeptic",
    )
    ROLE_DOMAINS = {
        "researcher": {"market", "technical", "fundamentals", "estimates", "macro", "segments", "gurus", "economic_calendar"},
        "fundamental_analyst": {"fundamentals", "estimates", "segments"},
        "market_analyst": {"market", "technical"},
        "macro_news_analyst": {"macro", "economic_calendar", "gurus"},
        "skeptic": {"market", "technical", "fundamentals", "estimates", "macro", "segments", "gurus", "economic_calendar"},
    }

    def __init__(self, client: LLMClient, policy: ShadowPolicy | None = None):
        self.client = client
        self.policy = policy or ShadowPolicy()

    def run(self, bundle: EvidenceBundle, *, memory_text: str = "평가된 과거 사례 없음") -> HarnessResult:
        from concurrent.futures import ThreadPoolExecutor

        # 1. Researcher executes first to establish baseline context
        researcher_user = canonical_json({
            "instruction": ROLE_INSTRUCTIONS["researcher"],
            "evidence_bundle": _domain_bundle(bundle, self.ROLE_DOMAINS["researcher"]),
            "prior_analyses": [],
            "evaluated_case_memory": memory_text,
        })
        raw_res = self.client.complete_json(
            system=COMMON_SYSTEM,
            user=researcher_user,
            output_schema=ROLE_OUTPUT_SCHEMA,
            task_name="researcher",
        )
        researcher_analysis = RoleAnalysis.from_dict("researcher", raw_res, bundle.evidence_ids)

        # 2. Independent domain analysts run concurrently in parallel
        prior_context = [researcher_analysis.to_dict()]

        def _execute_analyst(role: str) -> RoleAnalysis:
            user = canonical_json({
                "instruction": ROLE_INSTRUCTIONS[role],
                "evidence_bundle": _domain_bundle(bundle, self.ROLE_DOMAINS[role]),
                "prior_analyses": prior_context,
                "evaluated_case_memory": "역할상 생략",
            })
            raw = self.client.complete_json(
                system=COMMON_SYSTEM,
                user=user,
                output_schema=ROLE_OUTPUT_SCHEMA,
                task_name=role,
            )
            return RoleAnalysis.from_dict(role, raw, bundle.evidence_ids)

        with ThreadPoolExecutor(max_workers=3) as executor:
            fund_future = executor.submit(_execute_analyst, "fundamental_analyst")
            mkt_future = executor.submit(_execute_analyst, "market_analyst")
            macro_future = executor.submit(_execute_analyst, "macro_news_analyst")

            fund_analysis = fund_future.result()
            mkt_analysis = mkt_future.result()
            macro_analysis = macro_future.result()

        analyses = [researcher_analysis, fund_analysis, mkt_analysis, macro_analysis]

        # 3. Skeptic executes next with all prior analyses
        skeptic_user = canonical_json({
            "instruction": ROLE_INSTRUCTIONS["skeptic"],
            "evidence_bundle": _domain_bundle(bundle, self.ROLE_DOMAINS["skeptic"]),
            "prior_analyses": [a.to_dict() for a in analyses],
            "evaluated_case_memory": memory_text,
        })
        raw_skeptic = self.client.complete_json(
            system=COMMON_SYSTEM,
            user=skeptic_user,
            output_schema=ROLE_OUTPUT_SCHEMA,
            task_name="skeptic",
        )
        analyses.append(RoleAnalysis.from_dict("skeptic", raw_skeptic, bundle.evidence_ids))

        # 4. Portfolio Manager executes final portfolio decision
        final_user = canonical_json({
            "instruction": PORTFOLIO_INSTRUCTION,
            "ticker": bundle.ticker,
            "as_of_at": bundle.as_of_at,
            "horizon_days": self.policy.horizon_days,
            "available_evidence_ids": sorted(bundle.evidence_ids),
            "bundle_missing_data": list(bundle.missing_data),
            "bundle_warnings": list(bundle.warnings),
            "role_analyses": [analysis.to_dict() for analysis in analyses],
            "evaluated_case_memory": memory_text,
        })
        raw_decision = self.client.complete_json(
            system=COMMON_SYSTEM,
            user=final_user,
            output_schema=DECISION_OUTPUT_SCHEMA,
            task_name="portfolio_manager",
        )
        decision = InvestmentDecision.from_dict(
            raw_decision,
            ticker=bundle.ticker,
            as_of_at=bundle.as_of_at,
            allowed_ids=bundle.evidence_ids,
        )
        return HarnessResult(tuple(analyses), self.policy.enforce(decision, bundle))

