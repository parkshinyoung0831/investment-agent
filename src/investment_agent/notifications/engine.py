"""알림 발행 엔진 — 알릴 거리(Notice)를 원장에 맡겨 한 번만 사람에게 닿게 한다.

알림 패키지는 두 가지만 한다.
1. 원천에서 Notice를 계산한다: 정체성(subject·occurrence), 사실 시각, 같은 알림인지
   가를 표시 값(basis). basis의 hash가 revision이다.
2. 원장이 보내라고 한 Notice만 그린다(render).

나머지 — 중복 판단, 묶음, 전송·수정, 재시도, 결과 기록, 실패 보고 — 는 여기 한 곳에
있다. 같은 Notice로 몇 번을 불러도(로컬 하네스·Actions·안전망·수동) 사람에게는 한 번
닿는다. 그래서 스케줄은 정합성이 아니라 "얼마나 빨리"만의 문제가 된다.
"""
from __future__ import annotations

import math
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from investment_agent.notifications.channels.contracts import (
    NONCE_MAX_LENGTH,
    Delivery,
    DeliveryRejected,
    DeliveryUnknown,
    ForumThread,
    NotificationChannel,
)
from investment_agent.notifications.ledger import NotificationLedger, Reservation
from investment_agent.notifications.problems import note_problem
from investment_agent.notifications.topics import Topic
from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import content_hash
from investment_agent.reporting.models import public_exception_message

log = get_logger(__name__)

# 카드 렌더(Playwright)와 전송이 이 안에 끝나야 한다. 넘기면 다른 실행이 다시 잡는다.
LEASE_SECONDS = 900
MAX_ATTEMPTS = 3
RESERVE_CHUNK = 100
RENDER_RETRY_SECONDS = 1800
REPLAY_ENV = "NOTIFY_REPLAY"


@dataclass(frozen=True)
class Notice:
    """사람에게 알릴 거리 하나."""

    subject: str
    occurrence: str
    #: 알린 사실이 일어난 시각. topic의 baseline보다 앞서면 보내지 않는다.
    fact_at: datetime
    #: 같은 알림인지 가르는 표시 값. 매일 바뀌는 곁가지(가격 이력 등)는 넣지 않는다.
    basis: Mapping[str, Any]
    #: render가 쓰는 원본. hash하지 않는다.
    data: Any = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if not str(self.subject).strip() or not str(self.occurrence).strip():
            raise ValueError("notice identity must not be empty")
        if self.fact_at.tzinfo is None:
            raise ValueError("notice fact_at must be timezone-aware")

    @property
    def key(self) -> tuple[str, str]:
        return self.subject, self.occurrence

    @property
    def revision(self) -> str:
        return content_hash(self.basis)


@dataclass(frozen=True)
class Rendered:
    message: dict[str, Any]
    attachment_path: str | None = None
    thread: ForumThread | None = None


Renderer = Callable[[list[Notice]], Rendered]


@dataclass
class PublishReport:
    topic: str
    candidates: int = 0
    created: int = 0
    edited: int = 0
    suppressed: int = 0
    unchanged: int = 0
    failed: int = 0
    # 원장이 맡기지 않은 건 — 같은 revision을 이미 보냈거나, 고칠 수 없는 topic이라 새 revision을 기록만 했다.
    already_recorded: int = 0

    @property
    def delivered(self) -> int:
        return self.created + self.edited


@dataclass(frozen=True)
class PublishContext:
    ledger: NotificationLedger
    channel: NotificationChannel
    owner: str


def fact_time(value: Any) -> datetime:
    """공시일·관측일·시각을 알림의 fact_at으로. 날짜만 있으면 그날 00:00 UTC다."""
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value or "").strip()
        if not text:
            raise ValueError("a notice needs the time its fact happened")
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def new_owner() -> str:
    """이 실행의 식별자. 예약과 결과 기록이 같은 실행에서 왔는지 가른다."""
    runner = os.environ.get("GITHUB_RUN_ID") or "local"
    return f"{runner}:{os.getpid()}:{os.urandom(6).hex()}"


def replay_requested() -> bool:
    """사람이 수동 실행에서 다시 그리기를 요청했는가(`notify --force`)."""
    return os.environ.get(REPLAY_ENV, "").strip().lower() in {"1", "true", "on"}


def publish(topic: Topic, notices: Sequence[Notice], render: Renderer, *,
            context: PublishContext, target: str, replay: bool | None = None) -> PublishReport:
    """Notice들을 원장에 맡기고, 원장이 이 실행에 맡긴 것만 그려서 보낸다.

    replay면 이미 보낸 알림도 다시 그린다 — 메시지가 있으면 그 메시지를 고치고, 없으면
    새로 보낸다. 사람이 정한 재발송이라 "직전과 같으면 생략"도 건너뛴다.
    """
    report = PublishReport(topic.name, candidates=len(notices))
    by_key = _unique(notices)
    pending = list(by_key.values())
    if replay if replay is not None else replay_requested():
        for notice in pending:
            context.ledger.replay(topic.name, notice.subject, notice.occurrence)
    elif topic.skip_unchanged:
        pending = _without_unchanged(topic, pending, context.ledger, report)
    if not pending:
        return report

    reservations: list[Reservation] = []
    for start in range(0, len(pending), RESERVE_CHUNK):
        chunk = pending[start:start + RESERVE_CHUNK]
        reservations.extend(context.ledger.reserve(
            topic.name,
            [{"subject": n.subject, "occurrence": n.occurrence, "revision": n.revision,
              "fact_at": n.fact_at.isoformat()} for n in chunk],
            owner=context.owner, lease_seconds=LEASE_SECONDS, revisable=topic.is_revisable,
        ))
    report.suppressed = sum(1 for r in reservations if r.action == "suppressed")
    report.already_recorded = len(pending) - len(reservations)
    creates = sorted((r for r in reservations if r.action == "create"), key=lambda r: r.key)
    edits = [r for r in reservations if r.action == "edit"]
    groups = [creates[i:i + topic.batch_size] for i in range(0, len(creates), topic.batch_size)]
    groups += [[reservation] for reservation in edits]
    for group in groups:
        _deliver(topic, group, by_key, render, context, target, report)
    log.info(
        "notification publish topic=%s candidates=%d created=%d edited=%d suppressed=%d unchanged=%d failed=%d "
        "already_recorded=%d",
        report.topic, report.candidates, report.created, report.edited,
        report.suppressed, report.unchanged, report.failed, report.already_recorded,
    )
    return report


def unsettled(topic: Topic, notices: Sequence[Notice], *, ledger: NotificationLedger) -> list[Notice]:
    """원장이 아직 사람에게 보내지 않았거나 다시 보낼 차례인 알림.

    보내기 전 무거운 준비(카드 렌더 의존성 설치)를 할지 정하는 사전 점검용이다. 실제
    판단은 publish가 원자적으로 다시 내리므로, 여기서 조금 넉넉하게 답해도 중복은 없다.
    """
    states = ledger.states(topic.name, [notice.key for notice in notices])
    out = []
    for notice in notices:
        state = states.get(notice.key)
        if state is None or state.status in {"failed", "reserved"}:
            out.append(notice)
        elif topic.is_revisable and state.status == "sent" and state.sent_revision != notice.revision:
            out.append(notice)
    return out


def _unique(notices: Sequence[Notice]) -> dict[tuple[str, str], Notice]:
    by_key: dict[tuple[str, str], Notice] = {}
    for notice in notices:
        previous = by_key.get(notice.key)
        if previous is not None and previous.revision != notice.revision:
            raise ValueError(f"conflicting notices for {notice.key}")
        by_key.setdefault(notice.key, notice)
    return by_key


def _without_unchanged(topic: Topic, notices: list[Notice], ledger: NotificationLedger,
                       report: PublishReport) -> list[Notice]:
    kept = []
    for notice in notices:
        last = ledger.last_known(topic.name, notice.subject)
        if last is not None and last.occurrence != notice.occurrence and last.revision == notice.revision:
            report.unchanged += 1
            continue
        kept.append(notice)
    return kept


def _label(keys: Sequence[tuple[str, str]]) -> str:
    return ",".join(f"{subject}@{occurrence}" for subject, occurrence in keys)


def _nonce(topic: Topic, notices: Sequence[Notice]) -> str:
    return content_hash({
        "topic": topic.name,
        "notices": [[n.subject, n.occurrence, n.revision] for n in notices],
    })[:NONCE_MAX_LENGTH]


def _deliver(topic: Topic, group: list[Reservation], by_key: Mapping[tuple[str, str], Notice],
             render: Renderer, context: PublishContext, target: str, report: PublishReport) -> None:
    ledger, owner = context.ledger, context.owner
    action = group[0].action
    keys = [reservation.key for reservation in group]
    label = _label(keys)
    notices = [by_key[key] for key in keys]
    attempts = max(reservation.attempts for reservation in group) + 1

    def finish(outcome: str, delivery: Delivery | None = None, code: str | None = None,
               retry: int | None = None) -> None:
        try:
            finished = ledger.finish(
                topic.name, keys, owner=owner, action=action, outcome=outcome,
                location_id=delivery.location_id if delivery else None,
                message_id=delivery.message_id if delivery else None,
                failure_code=code, retry_seconds=retry,
            )
        except Exception as exc:  # noqa: BLE001 - 기록 실패는 보고하고 다음 묶음으로 간다
            note_problem(topic.name, label, public_exception_message("전송 결과 기록 실패", exc), status="unknown")
            return
        if finished != len(keys):
            note_problem(topic.name, label, f"결과 기록 {finished}/{len(keys)}건", status="unknown")

    try:
        rendered = render(notices)
    except Exception as exc:  # noqa: BLE001 - 한 묶음의 그리기 실패가 나머지를 막지 않는다
        outcome = "abandoned" if attempts >= MAX_ATTEMPTS else "failed"
        log.error("notification render failed topic=%s keys=%s", topic.name, label, exc_info=True)
        finish(outcome, code="render_failed", retry=RENDER_RETRY_SECONDS)
        note_problem(topic.name, label, public_exception_message("알림 그리기 실패", exc), status=outcome)
        report.failed += 1
        return

    if ledger.begin_send(topic.name, keys, owner=owner) != len(keys):
        # 예약이 만료돼 다른 실행이 가져갔을 수 있다. 보내지 않고 이 실행 몫만 놓아준다.
        finish("failed", code="lease_lost", retry=60)
        note_problem(topic.name, label, "예약이 만료돼 보내지 않았다", status="error")
        report.failed += 1
        return

    delivery: Delivery | None = None
    outcome, code, retry = "sent", None, None
    known_thread = None
    try:
        if action == "edit":
            reservation = group[0]
            delivery = context.channel.edit(
                location_id=reservation.location_id, message_id=reservation.message_id,
                message=rendered.message, attachment_path=rendered.attachment_path,
            )
        else:
            if rendered.thread is not None:
                known_thread = ledger.thread(target, rendered.thread.key)
            delivery = _create(context.channel, target, rendered, known_thread, _nonce(topic, notices))
    except DeliveryRejected as exc:
        code = str(exc)
        outcome = ("failed" if exc.is_retryable and (exc.is_throttled or attempts < MAX_ATTEMPTS)
                   else "abandoned")
        retry = max(int(math.ceil(exc.retry_after)), 1)
    except DeliveryUnknown as exc:
        outcome, code = "unknown", str(exc)
    except Exception as exc:  # noqa: BLE001 - 전송 여부를 모르는 모든 경우
        outcome, code = "unknown", type(exc).__name__

    finish(outcome, delivery, code, retry)
    if outcome == "sent":
        if action == "edit":
            report.edited += 1
        else:
            report.created += 1
        if rendered.thread is not None and delivery is not None and delivery.thread_id not in (None, known_thread):
            try:
                ledger.remember_thread(target, rendered.thread.key, delivery.thread_id or "")
            except Exception:  # noqa: BLE001 - 다음 전송이 목록 조회로 다시 찾는다
                log.warning("notification thread was not remembered topic=%s keys=%s", topic.name, label)
        return
    report.failed += 1
    if outcome in {"abandoned", "unknown"}:
        note_problem(topic.name, label, code, status=outcome)


def _create(channel: NotificationChannel, target: str, rendered: Rendered, known_thread: str | None, nonce: str) -> Delivery:
    """새 메시지를 보낸다. 메시지 POST라면 응답을 잃었을 때 같은 nonce로 한 번 더 묻는다."""
    kwargs = dict(
        target=target, message=rendered.message, attachment_path=rendered.attachment_path,
        thread=rendered.thread, known_thread_id=known_thread, nonce=nonce,
    )
    try:
        return channel.deliver(**kwargs)
    except DeliveryUnknown:
        # 새 스레드를 만드는 요청에는 nonce가 없다. 거기서 다시 보내면 스레드가 둘이 된다.
        if rendered.thread is not None and known_thread is None:
            raise
        return channel.deliver(**kwargs)


__all__ = [
    "LEASE_SECONDS", "MAX_ATTEMPTS", "Notice", "PublishContext", "PublishReport", "REPLAY_ENV",
    "Rendered", "Renderer", "fact_time", "new_owner", "publish", "replay_requested", "unsettled",
]
