"""사람이 받지 못했거나 받았는지 모르는 알림을 프로세스 단위로 모은다.

발송 코드는 결과를 모아 올리지 않고 각자 버리는 경우가 많다. 진입점이 끝에서 한 번
더 묻지 않으면 등록·전송 실패가 경고 로그 한 줄로만 남고 GitHub Actions 잡은 초록색으로
끝난다. ETL과 한 프로세스인 진입점은 이것을 자기 실패 목록에 더할 뿐 적재를 되돌리지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass

from investment_agent.platform.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class Problem:
    """알림 하나의 문제. key는 topic 안의 정체성(subject·occurrence)이다."""

    topic: str
    key: str
    status: str
    reason: str | None = None


_unreported: list[Problem] = []


def note_problem(topic: str, key: str, reason: str | None, *, status: str = "error") -> None:
    _unreported.append(Problem(topic, key, status, reason))


def take_problems() -> tuple[Problem, ...]:
    """이 프로세스에서 아직 보고되지 않은 문제를 꺼내고 비운다."""
    problems = tuple(_unreported)
    _unreported.clear()
    return problems


def report_problems(context: str) -> int:
    """남은 문제를 로그로 남기고 개수를 돌려준다. 0이 아니면 진입점은 실패로 끝낸다."""
    problems = take_problems()
    for problem in problems:
        log.error(
            "notification_problem context=%s topic=%s key=%s status=%s reason=%s",
            context, problem.topic, problem.key, problem.status, problem.reason,
        )
    return len(problems)


__all__ = ["Problem", "note_problem", "report_problems", "take_problems"]
