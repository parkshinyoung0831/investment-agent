"""모델 승격의 원장 역할. 실주문 직전 검사와 수동 승격 명령이 지나가는 좁은 자리다.

승격 규칙(수명주기·전이·확인 문구)은 Research 승격 게이트가 갖는다. 여기서는 Trading 원장에서
현재 단계와 승인 기록을 읽고 승인 행을 추가하며, 판정은 게이트 함수에 넘긴다.
"""
from __future__ import annotations

from typing import Any

import investment_agent.research.adapters.trading as research_adapter
from investment_agent.research.adapters.trading import EvaluationSummary, PromotionDecision
from investment_agent.trading.repository import LedgerAccess


class PromotionLedger(LedgerAccess):
    def model_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        return self._trading_repository().model_version(artifact_id)

    def model_stage(self, artifact_id: str) -> str | None:
        return self._trading_repository().current_model_stage(artifact_id)

    def model_evaluation_summary(self, artifact_id: str) -> EvaluationSummary:
        """평가 원장 전체를 보수적인 승격 요약으로 집계한다."""
        if self.model_artifact(artifact_id) is None:
            raise LookupError(f"model artifact not found: {artifact_id}")
        return research_adapter.open_research_store(read_only=True).model_evaluation_summary(artifact_id)

    def save_promotion(self, row: dict) -> None:
        """승인 전 제안·거절 audit만 기록한다. 승인은 `approve_model_promotion`만 쓴다."""
        self._trading_repository().record_model_promotion(row)

    def approve_model_promotion(self, decision: PromotionDecision, *, confirmation: str) -> dict[str, Any]:
        """평가 재검증 뒤 현재 단계를 잠그고 승인 audit만 기록한다."""
        audit_row = research_adapter.approval_audit_row(
            decision,
            confirmation=confirmation,
            model_artifact=self.model_artifact(decision.artifact_id),
            model_stage=self.model_stage(decision.artifact_id),
        )
        return self._trading_repository().approve_model_promotion(
            audit_row=audit_row,
            artifact_id=decision.artifact_id,
            from_stage=decision.from_stage,
            to_stage=decision.to_stage,
        )

    def has_approved_promotion(self, artifact_id: str, to_stage: str) -> bool:
        """실주문 직전 검사. 규칙은 Research 승격 게이트가 갖고, 여기서는 원장 두 조각만 읽어 넘긴다."""
        if to_stage not in {"paper", "live"}:
            return False
        return research_adapter.has_approved_chain(
            artifact_id=artifact_id,
            current_stage=self.model_stage(artifact_id),
            to_stage=to_stage,
            audits=self._trading_repository().model_promotions(artifact_id),
        )
