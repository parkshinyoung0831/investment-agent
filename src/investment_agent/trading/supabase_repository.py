"""Trading 원장과 domain owner 사이의 저장소 경계.

판단·신호·모델·포트폴리오의 영구 원장은 v1 ``trading`` schema가 소유한다.
재계산 가능한 research 산출물은 Supabase에 저장하지 않는다.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from investment_agent.trading.decision.candidates import CandidateSelection
from investment_agent.trading.promotion import PromotionLedger
from investment_agent.trading.contracts import parse_datetime
from investment_agent.research.adapters.trading import PitReader
from investment_agent.trading.portfolio.signal_book import SignalBatch, SignalRecord
from investment_agent.trading.decision.universe import normalize_ticker
from investment_agent.platform.logging import get_logger
from investment_agent.data.universe.persistence import select_security_ids_by_ticker, select_tickers_by_security_id

log = get_logger(__name__)


def _security_id(ticker: str) -> int:
    symbol = normalize_ticker(ticker)
    value = select_security_ids_by_ticker([symbol]).get(symbol)
    if value is None:
        raise RuntimeError(f"unknown universe security: {symbol}")
    return value


def _security_ids(tickers: Sequence[str]) -> dict[str, int]:
    symbols = sorted({normalize_ticker(ticker) for ticker in tickers})
    result = select_security_ids_by_ticker(symbols)
    missing = [symbol for symbol in symbols if symbol not in result]
    if missing:
        raise RuntimeError(f"unknown universe securities: {missing[:10]}")
    return result


class SupabaseRepository(PitReader, CandidateSelection, PromotionLedger):
    """PIT 읽기(Research)·후보 선정·승격(Trading 역할)을 합성하고 판단 원장 위임을 직접 갖는 Trading 저장소 경계."""

    def save_policy(self, row: dict) -> None:
        self._trading_repository().record_policy(row)

    def save_case(self, row: dict) -> None:
        payload = dict(row)
        ticker = payload.pop("ticker", None)
        evidence_bundle = payload.pop("evidence_bundle", None)
        payload.pop("role_analyses", None)
        evidence_meta = dict(evidence_bundle or {})
        final_decision = payload.get("final_decision")
        if isinstance(final_decision, dict):
            final_decision = dict(final_decision)
            if isinstance(evidence_meta.get("_digest"), dict):
                final_decision["evidence_digest"] = evidence_meta["_digest"]
            if evidence_meta.get("_artifact_error"):
                final_decision["evidence_artifact_error"] = str(
                    evidence_meta["_artifact_error"]
                )[:500]
            payload["final_decision"] = final_decision
        payload["security_id"] = _security_id(str(ticker))
        repository = self._trading_repository()
        repository.record_decision(payload)
        artifact = dict(evidence_meta.get("_artifact") or {})
        if artifact:
            repository.record_evidence([{
                "case_key": payload["case_key"],
                "evidence_kind": "bundle",
                "artifact_uri": artifact.get("uri") or artifact.get("artifact_uri"),
                "sha256": artifact["sha256"],
                "byte_size": int(artifact["byte_size"]),
                "schema_version": str(artifact["schema_version"]),
            }])

    def save_decision_run(self, row: dict) -> None:
        self._trading_repository().record_run(row)

    def finish_decision_run(
        self,
        run_id: str,
        *,
        status: str,
        failure_reason: str | None = None,
    ) -> None:
        self._trading_repository().finish_run(
            run_id,
            status=status,
            failure_reason=failure_reason,
        )

    def save_signal_batch(
        self,
        *,
        run_id: str,
        batch: SignalBatch,
        records: tuple[SignalRecord, ...],
    ) -> None:
        """배치 행을 먼저 저장한 뒤 종목 의견을 immutable ID로 저장한다."""
        if any(record.batch_id != batch.batch_id for record in records):
            raise ValueError("signal records do not belong to the supplied batch")
        batch_row = {
            "batch_id": batch.batch_id,
            "run_id": run_id,
            "as_of_at": batch.as_of_at,
            "completed_at": batch.completed_at,
            "requested_symbols": list(batch.requested_symbols),
            "successful_symbols": list(batch.successful_symbols),
            "failed_symbols": list(batch.failed_symbols),
            "is_complete": batch.is_complete,
            "model_artifact_id": batch.model_artifact_id,
        }
        security_ids = _security_ids([record.proposal.ticker for record in records]) if records else {}
        signal_rows = [{
            "signal_id": record.signal_id,
            "batch_id": record.batch_id,
            "case_key": record.case_key,
            "security_id": security_ids[normalize_ticker(record.proposal.ticker)],
            "proposal": record.proposal.to_dict(),
            "recorded_at": record.recorded_at,
            "expires_at": record.expires_at,
        } for record in records]
        self._trading_repository().record_signal_batch(batch=batch_row, signals=signal_rows)

    def latest_signal_batch_id(self, *, as_of_at: datetime) -> str | None:
        return self._trading_repository().latest_signal_batch_id(as_of_at=as_of_at)

    def signal_batch_id_for_as_of(self, as_of_at: str | datetime) -> str:
        """Shadow 입력 시각과 정확히 같은 단일 batch만 반환해 완료시각 경합을 없앤다."""
        point = parse_datetime(as_of_at)
        return self._trading_repository().signal_batch_id_for_as_of(point)

    def save_portfolio_proposal(self, row: dict) -> None:
        self._trading_repository().record_proposal(dict(row))

    def save_risk_decision(self, row: dict) -> None:
        self._trading_repository().record_risk_decision(dict(row))

    def save_portfolio_decision(self, row: dict) -> None:
        self._trading_repository().adopt_portfolio(row)

    def save_model_artifact(self, row: dict) -> None:
        self._trading_repository().record_model_version(row)


    def decision_cases_for_experiences(self) -> list[dict]:
        """체결 여부로 거르지 않은 원본 판단이다."""
        rows = self._trading_repository().decision_cases()
        tickers = select_tickers_by_security_id([int(row["security_id"]) for row in rows])
        return [{**row, "ticker": tickers[int(row["security_id"])]}
                for row in rows if int(row["security_id"]) in tickers]

    def cases_for_evaluation(self, limit: int = 200) -> list[dict]:
        rows = self._trading_repository().evaluation_candidates(limit=limit)
        tickers = select_tickers_by_security_id([int(row["security_id"]) for row in rows])
        return [
            {**row, "ticker": tickers[int(row["security_id"])]}
            for row in rows if int(row["security_id"]) in tickers
        ]

    def existing_evaluation_horizons(self, case_key: str) -> set[int]:
        return self._trading_repository().evaluation_horizons(case_key)

    def save_evaluation(self, row: dict) -> None:
        self._trading_repository().record_evaluation(row)

    def previous_decision(self, ticker: str, *, as_of_at: datetime) -> dict | None:
        """같은 종목의 직전 판단. 다음 판단이 무엇이 바뀌었는지 설명하게 하는 기준이다."""
        return self._trading_repository().previous_decision_row(security_id=_security_id(ticker), as_of_at=as_of_at)

    def evaluated_memories(
        self,
        ticker: str,
        limit: int = 5,
        as_of_at: datetime | None = None,
    ) -> list[dict]:
        cases = self._trading_repository().evaluated_memory_rows(
            security_id=_security_id(ticker),
            limit=limit,
            as_of_at=as_of_at,
        )
        return [
            {
                **row,
                "ticker": normalize_ticker(ticker),
                "evaluations": row["evaluations"],
            }
            for row in cases
        ][:limit]
