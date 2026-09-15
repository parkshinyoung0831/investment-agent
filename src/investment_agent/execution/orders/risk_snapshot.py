"""토스 USD sleeve의 일 손실 기준선을 private execution 원장에 기록한다."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

from investment_agent.platform.serialization import parse_datetime
from investment_agent.execution.orders.snapshots import AccountSnapshot
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.orders.toss_snapshot import capture_toss_account_snapshot


class RiskSnapshotRepository(Protocol):
    def save_account_snapshot(self, row: dict) -> int: ...
    def save_position_snapshots(self, rows: list[dict]) -> None: ...


@dataclass(frozen=True)
class StoredRiskSnapshot:
    snapshot_id: int
    captured_at: str
    equity_usd: float
    cash_buying_power_usd: float
    position_count: int
    open_order_count: int


def _account_ref(account_seq: int) -> str:
    return hashlib.sha256(f"toss|{account_seq}".encode("utf-8")).hexdigest()


# 손익·낙폭 기준선은 보유 가치를 기록할 뿐 주문 가격이 아니다. 정규장 마감 뒤(감시 창은 16:30까지)나
# 거래가 드문 종목은 마지막 체결이 120초보다 오래되는 게 정상이라, 주문용 신선도로 잡으면 기준선
# 자체가 비어 일손실 한도가 과거 값을 쓴다. 주문 직전 재검증(live_worker)은 120초를 그대로 쓴다.
RISK_SNAPSHOT_MAX_QUOTE_AGE_SECONDS = 3600.0


def capture_and_store_risk_snapshot(
    *,
    account_seq: int,
    repository: RiskSnapshotRepository,
    captured_at: datetime | None = None,
    capture: Callable[..., AccountSnapshot] = capture_toss_account_snapshot,
    max_quote_age_seconds: float = RISK_SNAPSHOT_MAX_QUOTE_AGE_SECONDS,
) -> StoredRiskSnapshot:
    """브로커 조회만 수행한 뒤 계좌번호를 hash로 바꿔 private DB에 저장한다."""
    if not isinstance(account_seq, int) or isinstance(account_seq, bool) or account_seq <= 0:
        raise ExecutionSafetyError("Toss account_seq must be a positive integer")
    snapshot = capture(account_seq=account_seq, captured_at=captured_at, max_quote_age_seconds=max_quote_age_seconds)
    current = parse_datetime(captured_at or datetime.now(timezone.utc))
    if snapshot.broker != "toss" or snapshot.account_id != str(account_seq):
        raise ExecutionSafetyError("Toss risk snapshot account identity does not match")
    snapshot.assert_usable(
        expected_account_id=str(account_seq),
        as_of_at=current,
        max_age_seconds=5.0,
    )
    account_snapshot_id = repository.save_account_snapshot({
        "execution_mode": "live",
        "broker_account_hash": _account_ref(account_seq),
        "equity": snapshot.total_value,
        "cash": snapshot.cash_value,
        "buying_power": snapshot.cash_value,
        "captured_at": snapshot.captured_at,
        "currency": snapshot.base_currency,
        "positions": [position.to_dict() for position in snapshot.positions],
        "raw_snapshot": {
            "source": "toss_usd_sleeve_baseline",
            "open_order_count": len(snapshot.open_order_ids),
        },
    })
    repository.save_position_snapshots([
        {
            "account_snapshot_id": account_snapshot_id,
            "captured_at": snapshot.captured_at,
            "broker_account_hash": _account_ref(account_seq),
            "execution_mode": "live",
            "currency": snapshot.base_currency,
            "ticker": position.ticker,
            "quantity": position.quantity,
            "market_price": position.market_price,
            "market_value": position.market_value,
            "weight": position.market_value / snapshot.total_value,
        }
        for position in snapshot.positions
    ])
    return StoredRiskSnapshot(
        snapshot_id=account_snapshot_id,
        captured_at=snapshot.captured_at,
        equity_usd=snapshot.total_value,
        cash_buying_power_usd=snapshot.cash_value,
        position_count=len(snapshot.positions),
        open_order_count=len(snapshot.open_order_ids),
    )


__all__ = ["StoredRiskSnapshot", "capture_and_store_risk_snapshot"]
