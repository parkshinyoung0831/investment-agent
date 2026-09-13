"""알림 topic 카탈로그 — 무엇을 알리고, 무엇이 "같은 알림"이며, 바뀌면 어떻게 하는가.

topic 이름 하나가 원장·로그·진입점에서 같은 대상을 부른다. 정체성(subject·occurrence)과
revision의 재료(basis)는 각 알림 패키지가 계산하고, 여기는 정책만 선언한다.

정책
- on_revision="ignore": 한 번 알린 것은 내용이 바뀌어도 다시 건드리지 않는다(사건형).
- on_revision="edit":   내용이 바뀌면 이미 보낸 메시지를 수정한다(요약형·진행형).
- batch_size > 1:       한 메시지에 여러 알림을 담는다. 묶음 메시지는 수정할 수 없으므로
                        edit 정책과 함께 쓰지 않는다.
- skip_unchanged:       같은 subject에서 사람이 이미 아는 직전 알림과 내용이 같으면 새 기간·새
                        관측이라도 보내지 않는다. 상태형(경보 등급)과 요약형(오늘의 시장)이 쓴다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_TOPIC_NAME = re.compile(r"^[a-z]+(\.[a-z_]+)+$")
POLICIES = frozenset({"ignore", "edit"})


@dataclass(frozen=True)
class Topic:
    name: str
    #: `subscriptions.KIND_ENV`의 키. 목적지 채널 하나를 가리킨다.
    channel_kind: str
    on_revision: str = "ignore"
    batch_size: int = 1
    skip_unchanged: bool = False

    def __post_init__(self) -> None:
        if not _TOPIC_NAME.fullmatch(self.name):
            raise ValueError(f"invalid topic name {self.name!r}")
        if self.on_revision not in POLICIES:
            raise ValueError(f"{self.name}: unknown revision policy {self.on_revision!r}")
        if self.batch_size < 1:
            raise ValueError(f"{self.name}: batch_size must be positive")
        if self.batch_size > 1 and self.on_revision == "edit":
            raise ValueError(f"{self.name}: a batched message cannot be edited per notice")

    @property
    def is_revisable(self) -> bool:
        return self.on_revision == "edit"


TOPICS: dict[str, Topic] = {topic.name: topic for topic in (
    Topic("econ.release", "econ_calendar_release", batch_size=5),
    Topic("macro.alert", "macro_watch", batch_size=10, skip_unchanged=True),
    Topic("macro.daily", "macro_core", on_revision="edit", skip_unchanged=True),
    Topic("earnings.flash", "fundamentals_flash"),
    Topic("earnings.report", "fundamentals_earnings"),
    Topic("earnings.schedule", "fundamentals_schedule", skip_unchanged=True),
    Topic("earnings.week", "fundamentals_calendar", on_revision="edit"),
    Topic("guru.filing", "gurus_forum"),
    Topic("guru.quarter", "institutional", on_revision="edit"),
    Topic("strategy.allocation", "strategy"),
    Topic("strategy.month", "strategy_summary"),
    Topic("ai.portfolio", "investment_portfolio"),
    Topic("ai.candidate", "investment_candidates"),
    Topic("ai.trade", "investment_trades", on_revision="edit"),
)}


def topic(name: str) -> Topic:
    try:
        return TOPICS[name]
    except KeyError:
        raise KeyError(f"unknown notification topic {name!r}") from None


__all__ = ["POLICIES", "TOPICS", "Topic", "topic"]
