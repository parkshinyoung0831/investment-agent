"""SignalBook과 실제 계좌 snapshot을 전체 목표 비중으로 결합한다."""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from investment_agent.trading.contracts import ContractError, parse_datetime
from investment_agent.platform.serialization import canonical_json
from investment_agent.trading.portfolio.contracts import CASH_SYMBOL, PortfolioProposal, validated_weights
from investment_agent.trading.portfolio.proposals import from_optimized_security_proposals
from investment_agent.trading.portfolio.signal_book import SignalBatch, SignalBook, SignalRecord
from investment_agent.execution.orders.snapshots import AccountSnapshot

_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")


def _tracked_symbols(values: Iterable[str]) -> tuple[str, ...]:
    symbols = tuple(sorted({str(value).upper().strip() for value in values if str(value).strip()}))
    if not symbols:
        raise ContractError("tracked universe must not be empty")
    invalid = [symbol for symbol in symbols if symbol == CASH_SYMBOL or not _SYMBOL_RE.fullmatch(symbol)]
    if invalid:
        raise ContractError("tracked universe contains invalid symbols: " + ", ".join(invalid))
    return symbols


@dataclass(frozen=True)
class PortfolioConstructionPolicy:
    """모델이 변경할 수 없는 계좌 병합 규칙."""

    key: str = "full-portfolio-constructor"
    version: int = 1
    max_snapshot_age_seconds: float = 300.0
    weight_tolerance: float = 1e-8

    def __post_init__(self) -> None:
        if not self.key or self.version < 1:
            raise ValueError("construction policy key and positive version are required")
        if isinstance(self.max_snapshot_age_seconds, bool):
            raise ValueError("max_snapshot_age_seconds must be positive")
        if not math.isfinite(float(self.max_snapshot_age_seconds)) or self.max_snapshot_age_seconds <= 0:
            raise ValueError("max_snapshot_age_seconds must be positive")
        if isinstance(self.weight_tolerance, bool):
            raise ValueError("weight_tolerance must be between 0 and 1")
        if not math.isfinite(float(self.weight_tolerance)) or not 0 < self.weight_tolerance < 1:
            raise ValueError("weight_tolerance must be between 0 and 1")

    @property
    def hash(self) -> str:
        return hashlib.sha256(canonical_json(asdict(self)).encode("utf-8")).hexdigest()


class PortfolioConstructor:
    """부분 종목 의견을 기존 보유를 보존하는 full_portfolio로 변환한다."""

    def __init__(self, policy: PortfolioConstructionPolicy | None = None):
        self.policy = policy or PortfolioConstructionPolicy()

    def _validated_batch_inputs(
        self,
        *,
        as_of_at: str | datetime,
        active_batch_id: str,
        signal_book: SignalBook,
        snapshot: AccountSnapshot,
        expected_account_id: str,
        tracked_symbols: Iterable[str],
    ) -> tuple[datetime, SignalBatch, tuple[str, ...], dict[str, SignalRecord]]:
        decision_time = parse_datetime(as_of_at)
        snapshot.assert_usable(
            expected_account_id=expected_account_id,
            as_of_at=decision_time,
            max_age_seconds=self.policy.max_snapshot_age_seconds,
        )
        active_batch = signal_book.assert_batch_execution_ready(
            active_batch_id,
            as_of_at=decision_time,
        )
        if parse_datetime(snapshot.captured_at) < parse_datetime(active_batch.completed_at):
            raise ContractError("portfolio snapshot must be captured after the active signal batch")
        if snapshot.base_currency != "USD":
            raise ContractError("S&P 500 portfolio construction requires a USD account snapshot")
        if snapshot.open_order_ids:
            raise ContractError("portfolio snapshot contains open orders and is not execution eligible")
        tracked_tuple = _tracked_symbols(tracked_symbols)
        records = signal_book.valid_records_for_batch(active_batch.batch_id, as_of_at=decision_time)
        for record in records.values():
            if record.batch_id != active_batch.batch_id:
                raise ContractError(
                    f"signal record batch {record.batch_id} does not match active batch {active_batch.batch_id}"
                )
        return decision_time, active_batch, tracked_tuple, records

    def construct_optimized(
        self,
        *,
        run_id: str,
        source_version: str,
        stage: str,
        as_of_at: str | datetime,
        active_batch_id: str,
        signal_book: SignalBook,
        snapshot: AccountSnapshot,
        expected_account_id: str,
        tracked_symbols: Iterable[str],
        sector_by_symbol: Mapping[str, str] | None = None,
        covariance: Sequence[Sequence[float]] | None = None,
        covariance_symbols: Sequence[str] | None = None,
        covariance_metadata: Mapping[str, Any] | None = None,
    ) -> PortfolioProposal:
        """LLM 예비 비중 없이, 계좌·완료 배치·optimizer를 하나의 실행 제안으로 결합한다."""
        decision_time, active_batch, tracked_tuple, records = self._validated_batch_inputs(
            as_of_at=as_of_at,
            active_batch_id=active_batch_id,
            signal_book=signal_book,
            snapshot=snapshot,
            expected_account_id=expected_account_id,
            tracked_symbols=tracked_symbols,
        )
        proposals = [records[ticker].proposal for ticker in sorted(records)]
        optimized = from_optimized_security_proposals(
            proposals,
            run_id=run_id,
            source_version=source_version,
            current_weights=snapshot.weights,
            stage=stage,
            case_keys=tuple(sorted({record.case_key for record in records.values() if record.case_key})),
            coverage="full_portfolio",
            sector_by_symbol=sector_by_symbol,
            covariance=covariance,
            covariance_symbols=covariance_symbols,
            covariance_metadata=covariance_metadata,
            preserve_unanalyzed_holdings=True,
        )
        analyzed = set(records)
        current_weights = snapshot.weights
        current_positions = set(current_weights) - {CASH_SYMBOL}
        changed_unanalyzed = sorted(
            symbol for symbol in current_positions - analyzed
            if abs(optimized.weights.get(symbol, 0.0) - current_weights[symbol]) > self.policy.weight_tolerance
        )
        if changed_unanalyzed:
            raise ContractError(
                "optimizer changed an unanalyzed holding: " + ", ".join(changed_unanalyzed)
            )
        tracked = set(tracked_tuple)
        untracked_new = sorted(
            symbol for symbol, weight in optimized.weights.items()
            if symbol not in {CASH_SYMBOL, *current_positions}
            and weight > self.policy.weight_tolerance
            and symbol not in tracked
        )
        if untracked_new:
            raise ContractError("optimizer opened an untracked symbol: " + ", ".join(untracked_new))
        batch_by_id = {batch.batch_id: batch for batch in signal_book.batches}
        signal_artifacts = sorted({
            str(batch_by_id[record.batch_id].model_artifact_id)
            for record in records.values()
            if batch_by_id[record.batch_id].model_artifact_id
        })
        if active_batch.model_artifact_id and signal_artifacts != [active_batch.model_artifact_id]:
            raise ContractError("signal artifact IDs do not strictly match active batch model artifact")
        tracked_hash = hashlib.sha256(canonical_json(tracked_tuple).encode("utf-8")).hexdigest()
        metadata = {
            **optimized.metadata,
            "coverage": "full_portfolio",
            "execution_eligible": True,
            "construction_policy_key": self.policy.key,
            "construction_policy_version": self.policy.version,
            "construction_policy_hash": self.policy.hash,
            "active_batch_id": active_batch.batch_id,
            "active_batch_complete": active_batch.is_complete,
            "active_batch_symbols": list(active_batch.requested_symbols),
            "signal_ids": [records[ticker].signal_id for ticker in sorted(records)],
            "signal_model_artifact_ids": signal_artifacts,
            "signal_actions": {ticker: records[ticker].proposal.signal for ticker in sorted(records)},
            "preserved_unanalyzed_symbols": sorted(current_positions - analyzed),
            "tracked_universe_count": len(tracked_tuple),
            "tracked_universe_hash": tracked_hash,
            "snapshot_broker": snapshot.broker,
            "snapshot_captured_at": snapshot.captured_at,
            "snapshot_open_order_count": len(snapshot.open_order_ids),
            "target_weight_source": "cvxpy_optimizer",
            "llm_target_weight_used": False,
        }
        return PortfolioProposal.create(
            run_id=run_id,
            source_type="optimizer",
            source_version=optimized.source_version,
            stage=stage,
            as_of_at=decision_time.isoformat(),
            weights=optimized.weights,
            confidence=optimized.confidence,
            reasoning=(
                "완료된 SignalBook의 expected return 신호를 계좌 snapshot과 결합",
                "cvxpy optimizer만 목표 비중을 결정하고 LLM target_weight는 사용하지 않음",
                "미분석 기존 보유는 snapshot 비중으로 고정",
            ),
            case_keys=optimized.case_keys,
            model_artifact_id=active_batch.model_artifact_id,
            metadata=metadata,
        )

    def _apply_signal(
        self,
        *,
        record: SignalRecord,
        current_weights: dict[str, float],
        target_weights: dict[str, float],
        tracked: set[str],
    ) -> str:
        proposal = record.proposal
        ticker = proposal.ticker
        signal = proposal.signal
        current = float(current_weights.get(ticker, 0.0))
        target = float(proposal.target_weight)
        held = current > self.policy.weight_tolerance
        is_tracked = ticker in tracked

        if signal in {"avoid", "watch"}:
            if target > self.policy.weight_tolerance:
                raise ContractError(f"{ticker} {signal} signal must have zero target_weight")
            # 관찰 의견은 기존 보유를 암묵적으로 청산하지 않는다.
            return "preserved" if held else "ignored"

        if signal == "open":
            if held:
                raise ContractError(f"{ticker} open signal conflicts with an existing position")
            if not is_tracked:
                raise ContractError(f"{ticker} cannot be opened because tracked is false")
            if target <= self.policy.weight_tolerance:
                raise ContractError(f"{ticker} open signal requires a positive target_weight")
            target_weights[ticker] = target
            return "opened"

        if signal == "increase":
            if not held:
                raise ContractError(f"{ticker} increase signal requires an existing position")
            if not is_tracked:
                raise ContractError(f"{ticker} cannot be increased because tracked is false")
            if target <= current + self.policy.weight_tolerance:
                raise ContractError(f"{ticker} increase target must exceed its current weight")
            target_weights[ticker] = target
            return "increased"

        if signal == "hold":
            if not held:
                raise ContractError(f"{ticker} hold signal requires an existing position")
            # target_weight는 예비값이므로 hold는 실제 snapshot 비중을 단일 기준으로 삼는다.
            target_weights[ticker] = current
            return "held"

        if signal == "reduce":
            if not held:
                raise ContractError(f"{ticker} reduce signal requires an existing position")
            if target <= self.policy.weight_tolerance:
                raise ContractError(f"{ticker} reduce cannot imply zero; use an explicit exit signal")
            if target >= current - self.policy.weight_tolerance:
                raise ContractError(f"{ticker} reduce target must be below its current weight")
            target_weights[ticker] = target
            return "reduced"

        if signal == "exit":
            if not held:
                raise ContractError(f"{ticker} exit signal requires an existing position")
            if target > self.policy.weight_tolerance:
                raise ContractError(f"{ticker} exit signal must have zero target_weight")
            target_weights[ticker] = 0.0
            return "exited"

        raise ContractError(f"unsupported security signal: {signal}")

    def construct(
        self,
        *,
        run_id: str,
        source_version: str,
        stage: str,
        as_of_at: str | datetime,
        active_batch_id: str,
        signal_book: SignalBook,
        snapshot: AccountSnapshot,
        expected_account_id: str,
        tracked_symbols: Iterable[str],
    ) -> PortfolioProposal:
        """fresh 계좌와 완전한 분석 배치만 실행 가능한 전체 제안으로 만든다."""
        if stage in {"paper", "live"}:
            raise ContractError(
                "paper/live portfolio construction requires construct_optimized; "
                "LLM target_weight is not executable"
            )
        decision_time, active_batch, tracked_tuple, records = self._validated_batch_inputs(
            as_of_at=as_of_at,
            active_batch_id=active_batch_id,
            signal_book=signal_book,
            snapshot=snapshot,
            expected_account_id=expected_account_id,
            tracked_symbols=tracked_symbols,
        )
        tracked = set(tracked_tuple)
        current_weights = snapshot.weights
        target_weights = {
            ticker: weight
            for ticker, weight in current_weights.items()
            if ticker != CASH_SYMBOL
        }
        current_positions = set(target_weights)
        actions: dict[str, str] = {}
        for ticker in sorted(records):
            actions[ticker] = self._apply_signal(
                record=records[ticker],
                current_weights=current_weights,
                target_weights=target_weights,
                tracked=tracked,
            )

        risky_total = math.fsum(target_weights.values())
        if risky_total > 1.0 + self.policy.weight_tolerance:
            raise ContractError(
                f"constructed risky weights exceed 1: {risky_total:.12f}; allocation policy must resolve it"
            )
        if risky_total > 1.0:
            risky_total = 1.0
        target_weights[CASH_SYMBOL] = 1.0 - risky_total
        final_weights = validated_weights(target_weights)

        used_records = tuple(records[ticker] for ticker in sorted(records))
        confidence = (
            math.fsum(record.proposal.confidence for record in used_records) / len(used_records)
            if used_records else 0.0
        )
        case_keys = tuple(sorted({record.case_key for record in used_records if record.case_key}))
        analyzed = set(records)
        preserved_unanalyzed = sorted(current_positions - analyzed)
        tracked_hash = hashlib.sha256(canonical_json(tracked_tuple).encode("utf-8")).hexdigest()
        batch_by_id = {batch.batch_id: batch for batch in signal_book.batches}
        signal_artifacts = sorted({
            str(batch_by_id[record.batch_id].model_artifact_id)
            for record in used_records
            if batch_by_id[record.batch_id].model_artifact_id
        })
        if active_batch.model_artifact_id and signal_artifacts != [active_batch.model_artifact_id]:
            raise ContractError("signal artifact IDs do not strictly match active batch model artifact")
        metadata = {
            "coverage": "full_portfolio",
            "execution_eligible": True,
            "construction_policy_key": self.policy.key,
            "construction_policy_version": self.policy.version,
            "construction_policy_hash": self.policy.hash,
            "active_batch_id": active_batch.batch_id,
            "active_batch_complete": active_batch.is_complete,
            "active_batch_symbols": list(active_batch.requested_symbols),
            "signal_ids": [record.signal_id for record in used_records],
            "signal_model_artifact_ids": signal_artifacts,
            "signal_actions": actions,
            "preserved_unanalyzed_symbols": preserved_unanalyzed,
            "tracked_universe_count": len(tracked_tuple),
            "tracked_universe_hash": tracked_hash,
            "snapshot_broker": snapshot.broker,
            "snapshot_captured_at": snapshot.captured_at,
            "snapshot_open_order_count": len(snapshot.open_order_ids),
        }
        return PortfolioProposal.create(
            run_id=run_id,
            source_type="llm",
            source_version=source_version,
            stage=stage,
            as_of_at=decision_time.isoformat(),
            weights=final_weights,
            confidence=confidence,
            reasoning=(
                "완료된 SignalBook 의견을 fresh 계좌 snapshot과 결합",
                "미분석 기존 보유는 유지하고 명시적 exit만 목표 비중 0으로 반영",
                "is_tracked=true 종목만 신규·추가매수를 허용",
            ),
            case_keys=case_keys,
            model_artifact_id=active_batch.model_artifact_id,
            metadata=metadata,
        )


__all__ = ["PortfolioConstructionPolicy", "PortfolioConstructor"]
