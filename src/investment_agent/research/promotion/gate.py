"""평가 원장을 집계해도 사람의 단계별 확인 없이는 모델을 승격하지 않는다."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from investment_agent.platform.serialization import finite_float as _finite, parse_datetime

#: 모델 수명주기. 승격은 이 순서를 한 칸씩만 오르고, 실행 단계(paper·live)는 앞 전이가 모두 승인돼야 열린다.
PROMOTION_PATH = ("shadow", "backtest", "out_of_sample", "walk_forward", "paper", "live")
_TRANSITIONS = set(zip(PROMOTION_PATH, PROMOTION_PATH[1:]))
_EXECUTION_STAGES = frozenset({"paper", "live"})


def approval_confirmation(artifact_id: str, from_stage: str, to_stage: str) -> str:
    """다른 artifact나 단계에 재사용할 수 없는 수동 확인 문구의 유일한 정의다."""
    return f"PROMOTE {artifact_id} {from_stage}->{to_stage}"


def has_approved_chain(
    *,
    artifact_id: str,
    current_stage: str | None,
    to_stage: str,
    audits: Iterable[Mapping[str, Any]],
) -> bool:
    """artifact가 실행 단계(`to_stage`) 이상이고, 거기까지 모든 전이가 정확한 확인 문구로 승인됐는가.

    승인 기록 하나라도 빠지거나 문구가 다르면 닫힌다. 실주문 직전 검사가 쓴다.
    """
    if to_stage not in _EXECUTION_STAGES or current_stage not in PROMOTION_PATH:
        return False
    target = PROMOTION_PATH.index(to_stage)
    if PROMOTION_PATH.index(current_stage) < target:
        return False
    approved = {
        (str(row.get("from_stage")), str(row.get("to_stage")))
        for row in audits
        if row.get("status") == "approved"
        and row.get("confirmation_text")
        == approval_confirmation(artifact_id, str(row.get("from_stage")), str(row.get("to_stage")))
    }
    return set(zip(PROMOTION_PATH[:target], PROMOTION_PATH[1:target + 1])) <= approved


@dataclass(frozen=True)
class PromotionCriteria:
    min_out_of_sample_days: int = 60
    min_walk_forward_windows: int = 3
    min_paper_days: int = 30
    max_drawdown: float = 0.20
    max_turnover: float = 2.0
    require_positive_excess_return: bool = True


@dataclass(frozen=True)
class EvaluationSummary:
    out_of_sample_days: int
    walk_forward_windows: int
    paper_days: int
    excess_return: float
    max_drawdown: float
    turnover: float
    lookahead_incidents: int = 0
    order_incidents: int = 0
    survivorship_incidents: int = 0
    data_integrity_incidents: int = 0
    research_only: bool = False
    leakage_incidents: int = 0
    evaluation_count: int = 0
    evaluation_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class PromotionDecision:
    artifact_id: str
    from_stage: str
    to_stage: str
    status: str
    violations: tuple[str, ...]
    evidence: dict
    approved_by: str | None = None
    approved_at: str | None = None

    def to_record(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "from_stage": self.from_stage,
            "to_stage": self.to_stage,
            "status": self.status,
            "evidence": {**self.evidence, "violations": list(self.violations)},
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
        }


class ManualPromotionGate:
    def __init__(self, criteria: PromotionCriteria | None = None):
        self.criteria = criteria or PromotionCriteria()

    def propose(
        self,
        artifact_id: str,
        *,
        from_stage: str,
        to_stage: str,
        summary: EvaluationSummary,
    ) -> PromotionDecision:
        violations: list[str] = []
        artifact_id = str(artifact_id).strip()
        if not artifact_id:
            raise ValueError("artifact_id is required")
        if (from_stage, to_stage) not in _TRANSITIONS:
            violations.append(
                "model promotion must follow the declared lifecycle one step at a time"
            )
        if summary.evaluation_count <= 0:
            violations.append("model artifact has no persisted evaluation evidence")
        if summary.lookahead_incidents:
            violations.append("look-ahead incident count is not zero")
        if summary.leakage_incidents:
            violations.append("leakage-check failure count is not zero")
        if summary.order_incidents:
            violations.append("order incident count is not zero")
        if summary.survivorship_incidents:
            violations.append("survivorship-bias incident count is not zero")
        if summary.data_integrity_incidents:
            violations.append("data-integrity incident count is not zero")
        if summary.research_only:
            violations.append("research-only evidence cannot support promotion")
        if summary.max_drawdown < -self.criteria.max_drawdown:
            violations.append("maximum drawdown exceeds the limit")
        if summary.turnover > self.criteria.max_turnover:
            violations.append("turnover exceeds the limit")
        if self.criteria.require_positive_excess_return and summary.excess_return <= 0.0:
            violations.append("excess return is not positive")
        if to_stage in {"paper", "live"} and summary.out_of_sample_days < self.criteria.min_out_of_sample_days:
            violations.append("out-of-sample period is too short")
        if to_stage in {"paper", "live"} and summary.walk_forward_windows < self.criteria.min_walk_forward_windows:
            violations.append("walk-forward window count is too small")
        if to_stage == "live" and summary.paper_days < self.criteria.min_paper_days:
            violations.append("paper trading period is too short")
        return PromotionDecision(
            artifact_id=artifact_id,
            from_stage=from_stage,
            to_stage=to_stage,
            status="rejected" if violations else "proposed",
            violations=tuple(violations),
            evidence={"summary": asdict(summary), "criteria": asdict(self.criteria)},
        )

    @staticmethod
    def approve(
        decision: PromotionDecision,
        *,
        approved_by: str,
        confirmation: str,
    ) -> PromotionDecision:
        if decision.status != "proposed" or decision.violations:
            raise ValueError("only a clean proposed promotion can be approved")
        if not approved_by.strip():
            raise ValueError("approved_by is required")
        expected = ManualPromotionGate.confirmation_text(decision)
        if confirmation != expected:
            raise ValueError(f"confirmation must exactly match: {expected}")
        return replace(
            decision,
            status="approved",
            approved_by=approved_by.strip(),
            approved_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def confirmation_text(decision: PromotionDecision) -> str:
        """다른 artifact나 단계에 재사용할 수 없는 수동 확인 문구다."""
        return approval_confirmation(decision.artifact_id, decision.from_stage, decision.to_stage)


def approval_audit_row(
    decision: PromotionDecision,
    *,
    confirmation: str,
    model_artifact: Mapping[str, Any] | None,
    model_stage: str | None,
) -> dict[str, Any]:
    """승인된 결정을 원장의 감사 행으로 바꾼다. 조건이 하나라도 어긋나면 닫힌다.

    artifact가 없거나 그 사이 단계가 움직였거나 확인 문구가 다르면 쓰지 않는다.
    """
    if decision.status != "approved" or decision.violations:
        raise ValueError("only a manually is_approved clean decision can be persisted")
    if model_artifact is None:
        raise RuntimeError("model promotion failed closed: artifact not found")
    if model_stage != decision.from_stage:
        raise RuntimeError("model promotion failed closed: artifact stage changed")
    expected = approval_confirmation(decision.artifact_id, decision.from_stage, decision.to_stage)
    if confirmation != expected:
        raise ValueError(f"confirmation must exactly match: {expected}")
    return {
        "artifact_id": decision.artifact_id,
        "from_stage": decision.from_stage,
        "to_stage": decision.to_stage,
        "status": "approved",
        "evidence": decision.to_record()["evidence"],
        "approved_by": decision.approved_by,
        "approved_at": decision.approved_at,
        "confirmation_text": confirmation,
    }


def _covered_days(intervals: Sequence[tuple[datetime, datetime]]) -> int:
    """겹치는 평가 구간을 중복 계산하지 않은 완전한 24시간 수다."""
    if not intervals:
        return 0
    merged: list[list[datetime]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        elif end > merged[-1][1]:
            merged[-1][1] = end
    seconds = math.fsum((end - start).total_seconds() for start, end in merged)
    return int(seconds // 86_400)


def _incident_count(metrics: Mapping[str, Any], key: str) -> tuple[int, bool]:
    value = metrics.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0, False
    return value, True


def aggregate_evaluations(rows: Sequence[Mapping[str, Any]]) -> EvaluationSummary:
    """artifact 평가 행을 보수적으로 집계하고 누락된 안전 증명도 실패로 센다."""
    if not rows:
        return EvaluationSummary(
            out_of_sample_days=0,
            walk_forward_windows=0,
            paper_days=0,
            excess_return=0.0,
            max_drawdown=-1.0,
            turnover=1_000_000_000.0,
            data_integrity_incidents=1,
            research_only=True,
            evaluation_count=0,
        )

    out_of_sample: list[tuple[datetime, datetime]] = []
    paper: list[tuple[datetime, datetime]] = []
    walk_forward_windows: set[tuple[str, str, str]] = set()
    excess_returns: list[float] = []
    drawdowns: list[float] = []
    turnovers: list[float] = []
    evaluation_ids: list[int] = []
    lookahead_incidents = 0
    leakage_incidents = 0
    order_incidents = 0
    survivorship_incidents = 0
    data_integrity_incidents = 0
    research_only = False

    for row in rows:
        try:
            start = parse_datetime(str(row["start_at"]))
            end = parse_datetime(str(row["end_at"]))
        except (KeyError, TypeError, ValueError):
            data_integrity_incidents += 1
            continue
        if end <= start:
            data_integrity_incidents += 1
            continue
        kind = str(row.get("evaluation_kind") or "")
        if kind == "out_of_sample":
            out_of_sample.append((start, end))
        elif kind == "walk_forward":
            walk_forward_windows.add((str(row.get("proposal_id") or ""), start.isoformat(), end.isoformat()))
        elif kind == "paper":
            paper.append((start, end))
        elif kind not in {"backtest", "live"}:
            data_integrity_incidents += 1

        excess = _finite(row.get("excess_return"))
        drawdown = _finite(row.get("max_drawdown"))
        turnover = _finite(row.get("turnover"))
        if excess is None or drawdown is None or drawdown > 0 or turnover is None or turnover < 0:
            data_integrity_incidents += 1
        else:
            excess_returns.append(excess)
            drawdowns.append(drawdown)
            turnovers.append(turnover)

        evaluation_id = row.get("evaluation_id")
        if isinstance(evaluation_id, bool) or not isinstance(evaluation_id, int):
            data_integrity_incidents += 1
        else:
            evaluation_ids.append(evaluation_id)
        metrics_value = row.get("metrics")
        metrics = metrics_value if isinstance(metrics_value, Mapping) else {}
        if not isinstance(metrics_value, Mapping):
            data_integrity_incidents += 1
        for key, target in (
            ("lookahead_incidents", "lookahead"),
            ("order_incidents", "order"),
            ("survivorship_incidents", "survivorship"),
            ("data_integrity_incidents", "integrity"),
        ):
            count, valid = _incident_count(metrics, key)
            if not valid:
                data_integrity_incidents += 1
            elif target == "lookahead":
                lookahead_incidents += count
            elif target == "order":
                order_incidents += count
            elif target == "survivorship":
                survivorship_incidents += count
            else:
                data_integrity_incidents += count

        research_only = research_only or row.get("research_only") is not False
        if row.get("leakage_check_passed") is not True:
            leakage_incidents += 1
        if row.get("survivorship_check_passed") is not True:
            survivorship_incidents += 1
        if row.get("data_integrity_check_passed") is not True:
            data_integrity_incidents += 1

    if len(evaluation_ids) != len(set(evaluation_ids)):
        data_integrity_incidents += 1
    return EvaluationSummary(
        out_of_sample_days=_covered_days(out_of_sample),
        walk_forward_windows=len(walk_forward_windows),
        paper_days=_covered_days(paper),
        # 한 나쁜 window가 평균에 가려지지 않게 최저 초과수익을 사용한다.
        excess_return=min(excess_returns, default=0.0),
        max_drawdown=min(drawdowns, default=-1.0),
        turnover=max(turnovers, default=1_000_000_000.0),
        lookahead_incidents=lookahead_incidents,
        leakage_incidents=leakage_incidents,
        order_incidents=order_incidents,
        survivorship_incidents=survivorship_incidents,
        data_integrity_incidents=data_integrity_incidents,
        research_only=research_only,
        evaluation_count=len(rows),
        evaluation_ids=tuple(sorted(set(evaluation_ids))),
    )


__all__ = [
    "PROMOTION_PATH",
    "EvaluationSummary",
    "ManualPromotionGate",
    "PromotionCriteria",
    "PromotionDecision",
    "aggregate_evaluations",
    "approval_audit_row",
    "approval_confirmation",
    "has_approved_chain",
]
