"""LLM 출력 위에 적용하는 변경 불가능한 Shadow 위험 정책."""
from __future__ import annotations

from dataclasses import dataclass, replace

from investment_agent.trading.decision.constants import DEFAULT_HORIZON_DAYS, POLICY_KEY, POLICY_VERSION
from investment_agent.trading.contracts import EvidenceBundle, InvestmentDecision


@dataclass(frozen=True)
class ShadowPolicy:
    key: str = POLICY_KEY
    version: int = POLICY_VERSION
    horizon_days: int = DEFAULT_HORIZON_DAYS
    min_confidence_for_risk: float = 0.60
    max_target_risk_unit: float = 0.05
    required_domains: tuple[str, ...] = ("market", "technical", "fundamentals", "estimates")
    benchmark: str = "SPY"
    stage: str = "shadow"

    def to_record(self, *, model_provider: str, model_name: str, prompt_version: str) -> dict:
        return {
            "policy_key": self.key,
            "policy_version": self.version,
            "stage": self.stage,
            "model_provider": model_provider,
            "model_name": model_name,
            "prompt_version": prompt_version,
            "config": {
                "horizon_days": self.horizon_days,
                "min_confidence_for_risk": self.min_confidence_for_risk,
                "max_target_risk_unit": self.max_target_risk_unit,
                "required_domains": list(self.required_domains),
                "benchmark": self.benchmark,
            },
        }

    def enforce(self, decision: InvestmentDecision, bundle: EvidenceBundle) -> InvestmentDecision:
        """근거가 불완전하면 신규 위험을 허용하지 않고 watch로 낮춘다."""
        missing_domains = sorted(set(self.required_domains) - bundle.domains)
        cited_domains = {
            item.domain for item in bundle.evidence
            if item.evidence_id in decision.evidence_ids
        }
        uncited_domains = sorted(set(self.required_domains) - cited_domains)
        action = decision.action
        risk = min(decision.target_risk_unit, self.max_target_risk_unit)
        missing = list(bundle.missing_data) + list(decision.missing_data)
        if missing_domains:
            missing.append("필수 근거 영역 없음: " + ", ".join(missing_domains))
        if uncited_domains:
            missing.append("최종 판단이 인용하지 않은 필수 근거: " + ", ".join(uncited_domains))
        if action in {"open", "increase"} and (
            decision.confidence < self.min_confidence_for_risk
            or missing_domains
            or uncited_domains
        ):
            action = "watch"
            risk = 0.0
        if action in {"avoid", "watch", "exit"}:
            risk = 0.0
        return replace(
            decision,
            horizon_days=self.horizon_days,
            action=action,
            target_risk_unit=risk,
            missing_data=tuple(dict.fromkeys(missing)),
        )
