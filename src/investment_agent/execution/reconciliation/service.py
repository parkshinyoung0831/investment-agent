"""우리 원장과 broker 상태를 다시 맞춘다.

## broker_order_id로만 맞춘다

종목·수량·시각이 비슷하다고 같은 주문으로 묶지 않는다. **추정 매칭은 중복 주문
위험을 만든다** — 다른 주문을 같은 것으로 보면 하나가 미체결로 남고, 같은 주문을
다른 것으로 보면 다시 보낸다.

그래서 확실한 키가 없는 것은 맞추지 않고 **운영자 확인 대상으로 남긴다.** 자동으로
처리할 수 없는 것을 자동으로 처리하지 않는 것이 여기서 하는 일이다.

## 세 가지가 나온다

* `matched` — 양쪽에 있고 id가 같다.
* `missing_remote` — 우리에게는 있는데 broker에 없다. 보냈는지 아닌지 모르는 것이
  대부분이라, **자동 재전송 대상이 아니다.**
* `external_remote` — broker에는 있는데 우리에게 없다. 사람이 앱에서 직접 낸 주문이거나,
  우리가 보내고 기록을 잃은 주문이다. 둘의 구분은 사람만 할 수 있다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol

# 더 이상 변하지 않는 broker 상태. 이 상태의 주문은 재동기화 대상에서 뺀다.
TERMINAL_STATUSES = frozenset({
    "FILLED", "CANCELED", "REJECTED", "CANCEL_REJECTED", "REPLACE_REJECTED", "REPLACED",
})


class RemoteOrder(Protocol):
    """broker 응답에서 이 모듈이 요구하는 최소한."""

    order_id: str
    status: str


@dataclass(frozen=True)
class LocalOrder:
    """우리 원장의 주문 한 줄."""

    local_order_id: str
    # 없으면 "보냈는지 모른다"는 뜻이다. 그 상태를 없는 것으로 읽으면 다시 보낸다.
    broker_order_id: str | None
    client_order_id: str
    broker_status: str


@dataclass(frozen=True)
class ReconciliationResult:
    matched: tuple[tuple[LocalOrder, RemoteOrder], ...]
    missing_remote: tuple[LocalOrder, ...]
    external_remote: tuple[RemoteOrder, ...]
    terminal_remote_ids: tuple[str, ...]

    @property
    def needs_operator(self) -> bool:
        """사람이 봐야 하는 것이 남았는가."""
        return bool(self.missing_remote or self.external_remote)


def reconcile_orders(
    local_orders: Iterable[LocalOrder],
    remote_orders: Iterable[RemoteOrder],
) -> ReconciliationResult:
    """양쪽 목록을 `broker_order_id`로만 맞춘다."""
    local = tuple(local_orders)
    remote = tuple(remote_orders)

    local_ids = [row.broker_order_id for row in local if row.broker_order_id]
    remote_ids = [row.order_id for row in remote]
    # 중복 id가 있으면 어느 쪽에 맞출지 답이 없다. 조용히 하나를 고르지 않는다.
    if len(local_ids) != len(set(local_ids)):
        raise ValueError("local broker_order_id values must be unique")
    if len(remote_ids) != len(set(remote_ids)):
        raise ValueError("remote order_id values must be unique")

    by_remote: Mapping[str, RemoteOrder] = {row.order_id: row for row in remote}
    matched: list[tuple[LocalOrder, RemoteOrder]] = []
    missing: list[LocalOrder] = []
    for row in local:
        if row.broker_order_id and row.broker_order_id in by_remote:
            matched.append((row, by_remote[row.broker_order_id]))
        else:
            missing.append(row)

    known = {row.broker_order_id for row in local if row.broker_order_id}
    external = [row for row in remote if row.order_id not in known]
    terminal = sorted(row.order_id for row in remote if row.status in TERMINAL_STATUSES)

    return ReconciliationResult(
        matched=tuple(matched),
        missing_remote=tuple(missing),
        external_remote=tuple(external),
        terminal_remote_ids=tuple(terminal),
    )


__all__ = [
    "LocalOrder",
    "ReconciliationResult",
    "RemoteOrder",
    "TERMINAL_STATUSES",
    "reconcile_orders",
]
