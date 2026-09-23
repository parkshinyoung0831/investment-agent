"""trading 스키마를 읽고 쓰는 유일한 자리.

## 한 회차의 흐름이 표로 남는다

```
decision_runs  →  security_decisions  →  portfolio_proposals
                                              ↓
                                        risk_decisions
                                              ↓
                                       portfolio_decisions
```

각 단계가 자기 행을 남기므로 "왜 이 포트폴리오가 나왔나"를 거슬러 올라갈 수 있다.
판단·제안·위험 승인·채택을 분리해 거절된 제안도 기록한다.

## 부분 성공을 성공으로 승격하지 않는다

500종목 중 3개가 실패한 회차는 `partial`이다. `completed`로 적으면 빠진 종목이
"신호 없음"으로 보이고, 그 구멍은 아무도 못 본다.

## 근거 payload는 여기 없다

`decision_evidence`에 주소와 지문만 넣는다. 내용은 `evidence/artifacts.py`의 `archive_case_evidence`가 파일로 옮긴다.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
from contextlib import nullcontext

from investment_agent.platform.clock import utc_now
from investment_agent.platform.db.postgres import Database
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

SCHEMA = "trading"
SCHEMA_REPORTING = "reporting"

T_POLICIES = "policies"
T_MODEL_VERSIONS = "model_versions"
T_MODEL_PROMOTIONS = "model_promotions"
V_CURRENT_MODEL_STAGE = "current_model_stage"
RPC_APPROVE_MODEL_PROMOTION = "approve_model_promotion"
T_RUNS = "decision_runs"
T_SECURITY_DECISIONS = "security_decisions"
T_EVIDENCE = "decision_evidence"
T_SIGNAL_RUNS = "signal_runs"
T_SIGNALS = "signals"
T_PROPOSALS = "portfolio_proposals"
T_RISK_DECISIONS = "risk_decisions"
T_PORTFOLIO_DECISIONS = "portfolio_decisions"
T_EVALUATIONS = "decision_evaluations"
T_ATTRIBUTION_REPORTS = "attribution_reports"
T_PERFORMANCE = "performance_daily"

RUN_STATUSES = ("running", "completed", "partial", "failed")

_DECISION_COLUMNS = (
    "case_key, run_id, security_id, as_of_at, horizon_days, policy_key, policy_version, "
    "model_provider, model_name, source_kind, status, context_hash, final_decision, "
    "failure_reason, created_at"
)



def evaluation_calendar_days(horizon: int) -> int:
    """H거래일이 확실히 지났다고 볼 달력 일수. 주말(7/5)과 연휴 여유 3일."""
    return -(-horizon * 7 // 5) + 3


def has_matured_gap(as_of_at: Any, evaluated: set[int], horizons: Sequence[int], *, now: datetime) -> bool:
    """아직 채점하지 않은 기간 중 달력상 이미 지났을 기간이 있는가."""
    decided = as_of_at if isinstance(as_of_at, datetime) else datetime.fromisoformat(str(as_of_at).replace("Z", "+00:00"))
    if decided.tzinfo is None:
        decided = decided.replace(tzinfo=timezone.utc)
    age = now - decided
    return any(horizon not in evaluated and age >= timedelta(days=evaluation_calendar_days(horizon))
               for horizon in horizons)

class TradingRepository:
    def __init__(self, db: Database | None = None) -> None:
        if db is None:
            from investment_agent.trading.local_store import LocalTradingDatabase
            db = LocalTradingDatabase()
        self._db = db

    # ── 정책·모델 수명주기 ────────────────────────────────────────────────
    def record_policy(self, row: dict[str, Any]) -> int:
        """판단 정책을 불변 버전으로 기록한다.

        같은 버전이 이미 있으면 덮어쓰지 않는다. 정책 정의를 바꾸려면 버전을
        올려야 하며, 그래야 과거 판단을 재현할 수 있다.
        """
        return int(self._db.insert_ignore_duplicate(
            schema=SCHEMA,
            table=T_POLICIES,
            row=dict(row),
        ))

    def record_model_version(self, row: dict[str, Any]) -> int:
        """모델 파일 자체가 아니라 주소·해시·학습 메타데이터만 기록한다."""
        allowed = {
            "artifact_id", "algorithm", "train_start", "train_end",
            "seed", "artifact_uri", "sha256", "params", "code_commit",
        }
        payload = {key: value for key, value in dict(row).items() if key in allowed}
        return self._db.insert_ignore_duplicate(
            schema=SCHEMA,
            table=T_MODEL_VERSIONS,
            row=payload,
        )

    def model_version(self, artifact_id: str) -> dict[str, Any] | None:
        artifact_id = str(artifact_id).strip()
        if not artifact_id:
            raise ValueError("artifact_id is required")
        rows = (
            self._db.table(SCHEMA, T_MODEL_VERSIONS)
            .select("*")
            .eq("artifact_id", artifact_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        return dict(rows[0]) if rows else None

    def record_model_promotion(self, row: dict[str, Any]) -> dict[str, Any]:
        """승인 전 제안·거절 audit만 기록한다. 승인은 수동 게이트를 거친다."""
        if row.get("status") == "approved":
            raise ValueError("approved promotions must use approve_model_promotion")
        inserted = (
            self._db.table(SCHEMA, T_MODEL_PROMOTIONS)
            .insert(dict(row))
            .execute()
            .data
            or []
        )
        if isinstance(inserted, dict):
            return dict(inserted)
        rows = list(inserted)
        if len(rows) != 1:
            raise RuntimeError("model promotion insert did not return exactly one row")
        return dict(rows[0])

    def approve_model_promotion(
        self,
        *,
        audit_row: dict[str, Any],
        artifact_id: str,
        from_stage: str,
        to_stage: str,
    ) -> dict[str, Any]:
        """현재 단계를 잠근 뒤 승인 audit만 추가한다."""
        inserted = (
            self._db.rpc(SCHEMA, RPC_APPROVE_MODEL_PROMOTION, {
                "p_artifact_id": str(artifact_id),
                "p_from_stage": str(from_stage),
                "p_to_stage": str(to_stage),
                "p_evidence": audit_row["evidence"],
                "p_approved_by": audit_row["approved_by"],
                "p_approved_at": audit_row["approved_at"],
                "p_confirmation_text": audit_row["confirmation_text"],
            })
            .execute()
            .data
            or []
        )
        if isinstance(inserted, dict):
            rows = [inserted]
        else:
            rows = list(inserted)
        if len(rows) != 1:
            raise RuntimeError("model promotion failed closed: promotion audit insert failed")
        return dict(rows[0])

    def current_model_stage(self, artifact_id: str) -> str | None:
        """reporting read model에서 artifact의 현재 승인 단계를 읽는다."""
        artifact_id = str(artifact_id).strip()
        if not artifact_id:
            raise ValueError("artifact_id is required")
        rows = (
            self._db.table(SCHEMA_REPORTING, V_CURRENT_MODEL_STAGE)
            .select("stage")
            .eq("artifact_id", artifact_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        return str(rows[0]["stage"]) if rows else None

    def model_promotions(self, artifact_id: str) -> list[dict[str, Any]]:
        artifact_id = str(artifact_id).strip()
        if not artifact_id:
            raise ValueError("artifact_id is required")
        return self._db.select_paged(
            lambda: self._db.table(SCHEMA, T_MODEL_PROMOTIONS)
            .select("*")
            .eq("artifact_id", artifact_id),
            order_by="created_at,promotion_id",
        )

    # ── 판단 회차·종목 판단 ──────────────────────────────────────────────
    def record_run(self, row: dict[str, Any]) -> int:
        """이미 계산된 회차 상태를 v1 원장에 기록한다."""
        return self._db.upsert(
            schema=SCHEMA,
            table=T_RUNS,
            rows=[dict(row)],
            on_conflict="run_id",
        )

    def security_decision_attempts(self) -> list[dict[str, Any]]:
        """저장된 모든 판단 시도의 security_id·status·as_of_at과 관여한 모델을 읽는다.

        후보 선정이 "마지막으로 분석한 시각"과 "마지막으로 시도한 시각"을 계산하는 입력이다.
        원장은 ticker가 아니라 security_id를 저장하므로 ticker 해석은 Data owner가 한다.

        model_provider·model_name도 함께 읽는다 — 실패한 시도가 **모델에 닿은 실패**인지
        예산이 없어 시작조차 못 한 것인지를 후보 선정이 구분해야 하기 때문이다
        (`decision.model_pool.never_reached_a_model`).
        """
        return list(
            self._db.table(SCHEMA, T_SECURITY_DECISIONS)
            .select("security_id,status,as_of_at,model_provider,model_name")
            .execute()
            .data
            or []
        )

    def decision_exists(self, case_key: str) -> bool:
        rows = (
            self._db.table(SCHEMA, T_SECURITY_DECISIONS)
            .select("case_key,status")
            .eq("case_key", case_key)
            .limit(1)
            .execute()
            .data
            or []
        )
        return bool(rows and rows[0].get("status") != "failed")

    # ── 신호 배치 ─────────────────────────────────────────────────────────
    def record_signal_batch(
        self,
        *,
        batch: dict[str, Any],
        signals: Sequence[dict[str, Any]],
    ) -> None:
        """완전성 배치와 immutable 종목 신호를 함께 기록한다."""
        batch_id = str(batch.get("batch_id") or "")
        if not batch_id:
            raise ValueError("signal batch needs batch_id")
        if any(str(row.get("batch_id") or "") != batch_id for row in signals):
            raise ValueError("signal records do not belong to the supplied batch")
        transaction = self._db.transaction() if hasattr(self._db, "transaction") else nullcontext()
        with transaction:
            self._db.insert_ignore_duplicate(schema=SCHEMA, table=T_SIGNAL_RUNS, row=dict(batch))
            for row in signals:
                self._db.insert_ignore_duplicate(schema=SCHEMA, table=T_SIGNALS, row=dict(row))

    def latest_signal_batch_id(self, *, as_of_at: datetime) -> str | None:
        rows = (
            self._db.table(SCHEMA, T_SIGNAL_RUNS)
            .select("batch_id")
            .lte("completed_at", as_of_at.isoformat())
            .order("completed_at", desc=True)
            .order("batch_id", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        return str(rows[0]["batch_id"]) if rows else None

    def signal_batch_id_for_as_of(self, as_of_at: datetime) -> str:
        rows = (
            self._db.table(SCHEMA, T_SIGNAL_RUNS)
            .select("batch_id,run_id")
            .eq("as_of_at", as_of_at.isoformat())
            .order("batch_id")
            .limit(2)
            .execute()
            .data
            or []
        )
        if not rows:
            raise LookupError(f"signal batch not found for as_of_at={as_of_at.isoformat()}")
        if len(rows) != 1:
            raise RuntimeError(
                "multiple signal batches share the requested as_of_at; explicit batch_id is required"
            )
        return str(rows[0]["batch_id"])

    def signal_batches(
        self,
        *,
        as_of_at: datetime,
        lookback_days: int,
    ) -> list[dict[str, Any]]:
        if lookback_days < 1 or lookback_days > 365:
            raise ValueError("lookback_days must be between 1 and 365")
        lower = (as_of_at - timedelta(days=lookback_days)).isoformat()
        return self._db.select_paged(
            lambda: self._db.table(SCHEMA, T_SIGNAL_RUNS)
            .select(
                "batch_id,as_of_at,completed_at,requested_symbols,successful_symbols,"
                "failed_symbols,model_artifact_id"
            )
            .gte("completed_at", lower)
            .lte("completed_at", as_of_at.isoformat()),
            order_by="completed_at,batch_id",
        )

    def signal_rows_recorded_between(self, *, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """기록 시각이 창 안인 종목 의견 전부(만료 여부와 무관). System 논지는 만료가 아니라 판단 시점으로 유효를 가른다."""
        return self._db.select_paged(
            lambda: self._db.table(SCHEMA, T_SIGNALS)
            .select("signal_id,batch_id,security_id,proposal,recorded_at")
            .gte("recorded_at", start.isoformat())
            .lte("recorded_at", end.isoformat()),
            order_by="recorded_at,signal_id",
        )

    # ── portfolio proposal → risk → adoption ─────────────────────────────
    def portfolio_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        rows = (
            self._db.table(SCHEMA, T_PROPOSALS)
            .select("*")
            .eq("proposal_id", str(proposal_id))
            .limit(1)
            .execute()
            .data
            or []
        )
        return dict(rows[0]) if rows else None

    def risk_decision(self, risk_decision_id: str) -> dict[str, Any] | None:
        rows = (
            self._db.table(SCHEMA, T_RISK_DECISIONS)
            .select("*")
            .eq("risk_decision_id", str(risk_decision_id))
            .limit(1)
            .execute()
            .data
            or []
        )
        return dict(rows[0]) if rows else None

    # ── 사후 평가 ─────────────────────────────────────────────────────────
    def evaluation_candidates(self, limit: int = 200, *, now: datetime | None = None) -> list[dict[str, Any]]:
        """채점할 수 있는 기간이 하나라도 새로 찬 판단만, 오래된 것부터.

        아직 끝나지 않은 기간만 남은 판단(60일을 기다리는 것)까지 후보로 세면, 가장 오래된 `limit`건이 그런
        판단으로 차서 최근 판단의 5·20일 채점이 그 판단들이 60일을 채울 때까지 밀린다.
        """
        if limit < 1:
            raise ValueError("limit must be positive")
        from investment_agent.research.adapters.trading import EVALUATION_HORIZONS
        from investment_agent.trading.local_store import LocalTradingDatabase
        moment = now or utc_now()
        if isinstance(self._db, LocalTradingDatabase):
            placeholders = ",".join("?" for _ in EVALUATION_HORIZONS)
            with self._db.transaction(read_only=True) as connection:
                cursor = connection.execute(
                    f"SELECT d.*, (SELECT group_concat(e.horizon_days) FROM {T_EVALUATIONS} e "
                    "WHERE e.case_key=d.case_key) AS _evaluated "
                    f"FROM {T_SECURITY_DECISIONS} d "
                    "WHERE d.status IN ('completed','abstained') AND "
                    f"(SELECT count(*) FROM {T_EVALUATIONS} e WHERE e.case_key=d.case_key "
                    f"AND e.horizon_days IN ({placeholders})) < ? "
                    "ORDER BY d.as_of_at,d.case_key",
                    [*EVALUATION_HORIZONS, len(EVALUATION_HORIZONS)],
                )
                columns = self._db.columns(connection, T_SECURITY_DECISIONS)
                names = [item[0] for item in cursor.description]
                rows = []
                for raw in cursor.fetchall():
                    row = dict(zip(names, raw))
                    evaluated = sorted({int(value) for value in str(row.pop("_evaluated") or "").split(",") if value})
                    rows.append({**self._db.decode(row, columns), "evaluated_horizons": evaluated})
        else:
            cases = self.decision_cases()
            completed = self._db.select_in_chunks(
                schema=SCHEMA, table=T_EVALUATIONS, columns="case_key,horizon_days",
                filter_column="case_key", values=[str(row["case_key"]) for row in cases],
                order_by="case_key,horizon_days",
            ) if cases else []
            horizons: dict[str, set[int]] = {}
            for row in completed:
                horizons.setdefault(str(row["case_key"]), set()).add(int(row["horizon_days"]))
            rows = [{**row, "evaluated_horizons": sorted(horizons.get(str(row["case_key"]), set()))} for row in cases]
        return [row for row in rows
                if has_matured_gap(row["as_of_at"], set(row["evaluated_horizons"]), EVALUATION_HORIZONS, now=moment)
                ][:limit]

    def decision_cases(self) -> list[dict[str, Any]]:
        """승인·매수 여부와 무관한 원본 완료 판단을 읽는다."""
        return self._db.select_paged(
            lambda: self._db.table(SCHEMA, T_SECURITY_DECISIONS)
            .select(_DECISION_COLUMNS).in_("status", ["completed", "abstained"]),
            order_by="as_of_at,case_key",
        )

    def evaluation_rows(self) -> list[dict[str, Any]]:
        """채점 원장 전체. 판단 성적표가 기간·엔진 버전별로 묶는 입력이다."""
        return self._db.select_paged(
            lambda: self._db.table(SCHEMA, T_EVALUATIONS)
            .select("case_key,horizon_days,excess_return,direction_correct,brier_score"),
            order_by="case_key,horizon_days",
        )

    def evaluation_horizons(self, case_key: str) -> set[int]:
        rows = self._db.select_paged(
            lambda: self._db.table(SCHEMA, T_EVALUATIONS)
            .select("horizon_days")
            .eq("case_key", str(case_key)),
            order_by="horizon_days",
        )
        return {int(row["horizon_days"]) for row in rows}

    def record_evaluation(self, row: dict[str, Any]) -> int:
        return self._db.upsert(
            schema=SCHEMA,
            table=T_EVALUATIONS,
            rows=[dict(row)],
            on_conflict="case_key,horizon_days",
        )

    def record_attribution_report(self, row: dict[str, Any]) -> int:
        return self._db.upsert(
            schema=SCHEMA,
            table=T_ATTRIBUTION_REPORTS,
            rows=[dict(row)],
            on_conflict="period_start,period_end,execution_mode",
        )

    def previous_decision_row(self, *, security_id: int, as_of_at: datetime) -> dict[str, Any] | None:
        """판단 시점 직전의 완료된 판단 하나. 결과 평가 여부와 무관하다(시점 이전 사실만 읽는다)."""
        rows = (
            self._db.table(SCHEMA, T_SECURITY_DECISIONS)
            .select("case_key,as_of_at,horizon_days,final_decision")
            .eq("security_id", int(security_id))
            .in_("status", ["completed", "abstained"])
            .lt("as_of_at", as_of_at.isoformat())
            .order("as_of_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        return dict(rows[0]) if rows else None

    def evaluated_memory_rows(
        self,
        *,
        security_id: int,
        limit: int = 5,
        as_of_at: datetime | None = None,
    ) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be positive")
        case_query = (
            self._db.table(SCHEMA, T_SECURITY_DECISIONS)
            .select("case_key,security_id,as_of_at,final_decision")
            .eq("security_id", int(security_id))
            .in_("status", ["completed", "abstained"])
        )
        if as_of_at is not None:
            case_query = case_query.lt("as_of_at", as_of_at.isoformat())
        cases = case_query.order("as_of_at", desc=True).limit(limit * 3).execute().data or []
        if not cases:
            return []
        keys = [str(row["case_key"]) for row in cases]
        evaluation_rows = self._db.select_in_chunks(
            schema=SCHEMA,
            table=T_EVALUATIONS,
            columns="case_key,horizon_days,excess_return,direction_correct,brier_score,evaluated_at",
            filter_column="case_key",
            values=keys,
            configure=(
                (lambda query: query.lte("evaluated_at", as_of_at.isoformat()))
                if as_of_at is not None else None
            ),
            order_by="evaluated_at",
        )
        by_case: dict[str, list[dict[str, Any]]] = {}
        for row in evaluation_rows:
            by_case.setdefault(str(row["case_key"]), []).append(row)
        for rows in by_case.values():
            rows.sort(key=lambda row: str(row.get("evaluated_at") or ""), reverse=True)
        return [
            {**row, "evaluations": by_case[str(row["case_key"])]}
            for row in cases
            if str(row["case_key"]) in by_case
        ][:limit]

    # ── 회차 ──────────────────────────────────────────────────────────────
    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        failure_reason: str | None = None,
        finished_at: datetime | None = None,
    ) -> int:
        """회차를 닫는다. 상태와 사유의 짝이 맞지 않으면 여기서 막는다.

        저장소도 같은 것을 CHECK로 막지만, 거기서 걸리면 배치 전체가 죽는다.
        """
        if status not in ("completed", "partial", "failed"):
            raise ValueError(f"cannot finish a run as {status!r}")
        if status == "failed" and not (failure_reason or "").strip():
            raise ValueError("a failed run must say why")
        if status != "failed" and failure_reason:
            # 성공했는데 실패 사유가 있으면 나중에 읽는 사람이 어느 쪽을 믿을지 모른다.
            raise ValueError("a non-failed run must not carry a failure reason")
        return self._db.upsert(
            schema=SCHEMA,
            table=T_RUNS,
            rows=[{
                "run_id": run_id,
                "status": status,
                "failure_reason": failure_reason,
                "finished_at": (finished_at or utc_now()).isoformat(),
            }],
            on_conflict="run_id",
        )

    # ── 종목 판단 ─────────────────────────────────────────────────────────
    def record_decision(self, row: dict[str, Any]) -> int:
        """판단 한 건. `final_decision`과 `failure_reason`은 배타적이다."""
        status = row.get("status")
        if status == "failed" and row.get("final_decision") is not None:
            raise ValueError("a failed decision must not carry a decision payload")
        if status in ("completed", "abstained") and row.get("final_decision") is None:
            # abstained도 "왜 판단을 보류했는가"를 payload로 남긴다.
            raise ValueError(f"a {status} decision needs a final_decision")
        return self._db.upsert(
            schema=SCHEMA, table=T_SECURITY_DECISIONS, rows=[row], on_conflict="case_key"
        )

    def record_evidence(self, rows: Sequence[dict[str, Any]]) -> int:
        return self._db.upsert(
            schema=SCHEMA, table=T_EVIDENCE, rows=list(rows),
            on_conflict="case_key,evidence_kind",
        )

    # ── 신호 ──────────────────────────────────────────────────────────────
    # ── 제안 → 판정 → 채택 ────────────────────────────────────────────────
    def record_proposal(self, row: dict[str, Any]) -> int:
        return self._db.upsert(
            schema=SCHEMA, table=T_PROPOSALS, rows=[row], on_conflict="proposal_id"
        )

    def record_risk_decision(self, row: dict[str, Any]) -> int:
        """위험 판정. 거절이면 승인 비중이 없어야 한다."""
        if not row.get("is_approved") and row.get("approved_weights") is not None:
            # 거절인데 비중이 남아 있으면 그것을 주문으로 읽는 길이 열린다.
            raise ValueError("a rejected risk decision must not carry approved weights")
        if row.get("is_approved") and row.get("approved_weights") is None:
            raise ValueError("an approved risk decision needs weights")
        return self._db.upsert(
            schema=SCHEMA, table=T_RISK_DECISIONS, rows=[row], on_conflict="risk_decision_id"
        )

    def adopt_portfolio(self, row: dict[str, Any]) -> int:
        """채택. 제안·판정이 같은 회차에 속하는지는 저장소의 복합 FK가 강제한다."""
        return self._db.upsert(
            schema=SCHEMA, table=T_PORTFOLIO_DECISIONS, rows=[row], on_conflict="decision_id"
        )

__all__ = [
    "RUN_STATUSES",
    "SCHEMA",
    "TradingRepository",
    "T_ATTRIBUTION_REPORTS",
    "T_EVALUATIONS",
    "T_EVIDENCE",
    "T_MODEL_PROMOTIONS",
    "T_MODEL_VERSIONS",
    "T_PERFORMANCE",
    "T_POLICIES",
    "T_PORTFOLIO_DECISIONS",
    "T_PROPOSALS",
    "T_RISK_DECISIONS",
    "T_RUNS",
    "T_SECURITY_DECISIONS",
    "T_SIGNALS",
    "T_SIGNAL_RUNS",
]


class LedgerAccess:
    """Trading 원장(`TradingRepository`)을 여는 역할 클래스의 공통 기반.

    후보 선정·승격처럼 원장의 한 조각만 쓰는 역할이 같은 원장 연결 방식을 공유한다.
    """

    @staticmethod
    def _trading_repository() -> TradingRepository:
        return TradingRepository()
