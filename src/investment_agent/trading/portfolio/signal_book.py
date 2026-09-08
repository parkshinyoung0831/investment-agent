"""종목별 최신 유효 의견과 분석 배치 완전성을 관리하는 순수 계약."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Iterable

from investment_agent.trading.contracts import ContractError, json_value, parse_datetime
from investment_agent.trading.portfolio.contracts import SecurityProposal
from investment_agent.platform.serialization import stable_id

_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")


def _symbols(values: Iterable[str], field_name: str, *, required: bool = False) -> tuple[str, ...]:
    raw = tuple(values)
    if any(not isinstance(value, str) for value in raw):
        raise ContractError(f"{field_name} must contain strings")
    normalized_values = tuple(value.upper().strip() for value in raw if value.strip())
    invalid = [value for value in normalized_values if value == "CASH" or not _SYMBOL_RE.fullmatch(value)]
    if invalid:
        raise ContractError(f"{field_name} contains invalid symbols: {sorted(invalid)}")
    if len(normalized_values) != len(set(normalized_values)):
        raise ContractError(f"{field_name} contains duplicate symbols")
    normalized = tuple(sorted(normalized_values))
    if required and not normalized:
        raise ContractError(f"{field_name} must not be empty")
    return normalized


@dataclass(frozen=True)
class SignalBatch:
    """한 분석 회차에서 요청·성공·실패·미완료 종목을 고정한다."""

    batch_id: str
    as_of_at: str
    completed_at: str
    requested_symbols: tuple[str, ...]
    successful_symbols: tuple[str, ...]
    failed_symbols: tuple[str, ...] = ()
    model_artifact_id: str | None = None

    def __post_init__(self) -> None:
        batch_id = str(self.batch_id).strip()
        if not batch_id:
            raise ContractError("batch_id is required")
        as_of_at = parse_datetime(self.as_of_at).isoformat()
        completed_at = parse_datetime(self.completed_at).isoformat()
        if parse_datetime(completed_at) < parse_datetime(as_of_at):
            raise ContractError("signal batch completed_at cannot precede as_of_at")
        requested = _symbols(self.requested_symbols, "requested_symbols", required=True)
        successful = _symbols(self.successful_symbols, "successful_symbols")
        failed = _symbols(self.failed_symbols, "failed_symbols")
        requested_set = set(requested)
        if not set(successful) <= requested_set or not set(failed) <= requested_set:
            raise ContractError("signal batch outcomes must be requested symbols")
        overlap = set(successful) & set(failed)
        if overlap:
            raise ContractError("signal batch success and failure symbols overlap")
        artifact_id = (
            str(self.model_artifact_id).strip()
            if self.model_artifact_id is not None else None
        )
        if artifact_id == "":
            raise ContractError("model_artifact_id cannot be empty")
        object.__setattr__(self, "batch_id", batch_id)
        object.__setattr__(self, "as_of_at", as_of_at)
        object.__setattr__(self, "completed_at", completed_at)
        object.__setattr__(self, "requested_symbols", requested)
        object.__setattr__(self, "successful_symbols", successful)
        object.__setattr__(self, "failed_symbols", failed)
        object.__setattr__(self, "model_artifact_id", artifact_id)

    @property
    def pending_symbols(self) -> tuple[str, ...]:
        classified = set(self.successful_symbols) | set(self.failed_symbols)
        return tuple(symbol for symbol in self.requested_symbols if symbol not in classified)

    @property
    def is_complete(self) -> bool:
        """모든 요청이 성공한 배치만 실행 후보가 될 수 있다."""
        return (
            not self.failed_symbols
            and not self.pending_symbols
            and self.successful_symbols == self.requested_symbols
        )

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class SignalRecord:
    """SecurityProposal의 생성 배치와 유효기간을 묶는다."""

    batch_id: str
    proposal: SecurityProposal
    recorded_at: str
    expires_at: str
    case_key: str | None = None
    signal_id: str = field(init=False)

    def __post_init__(self) -> None:
        batch_id = str(self.batch_id).strip()
        if not batch_id or not isinstance(self.proposal, SecurityProposal):
            raise ContractError("signal record requires batch_id and SecurityProposal")
        recorded_at = parse_datetime(self.recorded_at).isoformat()
        expires_at = parse_datetime(self.expires_at).isoformat()
        proposal_time = parse_datetime(self.proposal.as_of_at)
        if parse_datetime(recorded_at) < proposal_time:
            raise ContractError("signal recorded_at cannot precede proposal as_of_at")
        if parse_datetime(expires_at) <= parse_datetime(recorded_at):
            raise ContractError("signal expires_at must be after recorded_at")
        case_key = str(self.case_key).strip() if self.case_key is not None else None
        case_key = case_key or None
        object.__setattr__(self, "batch_id", batch_id)
        object.__setattr__(self, "recorded_at", recorded_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "case_key", case_key)
        identity = {
            "batch_id": batch_id,
            "proposal": self.proposal.to_dict(),
            "recorded_at": recorded_at,
            "expires_at": expires_at,
            "case_key": case_key,
        }
        object.__setattr__(self, "signal_id", stable_id("signal", identity))

    def is_valid_at(self, as_of_at: str | datetime) -> bool:
        """양 끝 중 만료 시각만 배제해 재현 가능한 TTL 경계를 만든다."""
        point = parse_datetime(as_of_at)
        return parse_datetime(self.recorded_at) <= point < parse_datetime(self.expires_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "batch_id": self.batch_id,
            "proposal": self.proposal.to_dict(),
            "recorded_at": self.recorded_at,
            "expires_at": self.expires_at,
            "case_key": self.case_key,
        }


@dataclass(frozen=True)
class SignalBook:
    """완료 배치의 최신 유효 의견만 노출하는 불변 SignalBook."""

    batches: tuple[SignalBatch, ...] = ()
    records: tuple[SignalRecord, ...] = ()

    def __post_init__(self) -> None:
        batches = tuple(self.batches)
        records = tuple(self.records)
        if any(not isinstance(batch, SignalBatch) for batch in batches):
            raise ContractError("batches must contain SignalBatch values")
        if any(not isinstance(record, SignalRecord) for record in records):
            raise ContractError("records must contain SignalRecord values")
        batches = tuple(sorted(batches, key=lambda item: (item.completed_at, item.batch_id)))
        records = tuple(sorted(records, key=lambda item: (item.recorded_at, item.signal_id)))
        batch_by_id = {batch.batch_id: batch for batch in batches}
        if len(batch_by_id) != len(batches):
            raise ContractError("signal book contains duplicate batch_id values")
        signal_ids = {record.signal_id for record in records}
        if len(signal_ids) != len(records):
            raise ContractError("signal book contains duplicate signal records")
        for record in records:
            batch = batch_by_id.get(record.batch_id)
            if batch is None:
                raise ContractError(f"signal record references unknown batch: {record.batch_id}")
            if record.proposal.ticker not in batch.successful_symbols:
                raise ContractError("signal record ticker is not a successful batch outcome")
            if parse_datetime(record.proposal.as_of_at) != parse_datetime(batch.as_of_at):
                raise ContractError("signal record and batch must share as_of_at")
            if parse_datetime(record.recorded_at) > parse_datetime(batch.completed_at):
                raise ContractError("signal record cannot be recorded after batch completion")
        object.__setattr__(self, "batches", batches)
        object.__setattr__(self, "records", records)

    def batch(self, batch_id: str) -> SignalBatch:
        for batch in self.batches:
            if batch.batch_id == batch_id:
                return batch
        raise ContractError(f"unknown signal batch: {batch_id}")

    def assert_batch_execution_ready(
        self,
        batch_id: str,
        *,
        as_of_at: str | datetime,
    ) -> SignalBatch:
        """부분·실패·만료 배치를 full portfolio 입력에서 차단한다."""
        batch = self.batch(batch_id)
        point = parse_datetime(as_of_at)
        if parse_datetime(batch.completed_at) > point:
            raise ContractError("signal batch is not completed at portfolio decision time")
        if not batch.is_complete:
            raise ContractError("partial or failed signal batch is not execution eligible")
        covered = {
            record.proposal.ticker
            for record in self.records
            if record.batch_id == batch.batch_id and record.is_valid_at(point)
        }
        missing = sorted(set(batch.successful_symbols) - covered)
        if missing:
            raise ContractError("complete signal batch has missing or expired records: " + ", ".join(missing))
        return batch

    def valid_records_for_batch(
        self,
        batch_id: str,
        *,
        as_of_at: str | datetime,
    ) -> dict[str, SignalRecord]:
        """지정된 단일 배치에만 속하며 만료되지 않은 종목 의견을 반환한다."""
        batch = self.assert_batch_execution_ready(batch_id, as_of_at=as_of_at)
        point = parse_datetime(as_of_at)
        records = {
            record.proposal.ticker: record
            for record in self.records
            if record.batch_id == batch.batch_id and record.is_valid_at(point)
        }
        missing = sorted(set(batch.successful_symbols) - set(records))
        if missing:
            raise ContractError("batch has missing or expired records: " + ", ".join(missing))
        return {ticker: records[ticker] for ticker in sorted(records)}

    def latest_valid(
        self,
        *,
        as_of_at: str | datetime,
        complete_batches_only: bool = True,
    ) -> dict[str, SignalRecord]:
        """종목마다 point-in-time 기준 가장 최신인 유효 의견을 반환한다."""
        point = parse_datetime(as_of_at)
        eligible_batches = {
            batch.batch_id
            for batch in self.batches
            if parse_datetime(batch.completed_at) <= point
            and (batch.is_complete or not complete_batches_only)
        }
        latest: dict[str, SignalRecord] = {}
        for record in self.records:
            if record.batch_id not in eligible_batches or not record.is_valid_at(point):
                continue
            ticker = record.proposal.ticker
            current = latest.get(ticker)
            ordering = (
                parse_datetime(record.proposal.as_of_at),
                parse_datetime(record.recorded_at),
                record.signal_id,
            )
            if current is None or ordering > (
                parse_datetime(current.proposal.as_of_at),
                parse_datetime(current.recorded_at),
                current.signal_id,
            ):
                latest[ticker] = record
        return {ticker: latest[ticker] for ticker in sorted(latest)}

    def append(
        self,
        batch: SignalBatch,
        records: Iterable[SignalRecord],
    ) -> "SignalBook":
        """원본을 바꾸지 않고 새 분석 배치를 누적한다."""
        return SignalBook(
            batches=(*self.batches, batch),
            records=(*self.records, *tuple(records)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "batches": [batch.to_dict() for batch in self.batches],
            "records": [record.to_dict() for record in self.records],
        }


__all__ = ["SignalBatch", "SignalBook", "SignalRecord"]
