"""일정 정확도의 목록은 도메인과 저장소가 같아야 한다.

`domain/releases/schedule.py`의 `schedule_window()`가 정확도별 watcher 창을 선언한다 —
그것이 "어떤 정확도가 존재하는가"의 기준이다. 저장소 CHECK가 그보다 좁으면, 빠진
정확도를 쓰는 지표의 **일정 적재가 통째로 죽는다.**

실측(2026-09-08): CHECK에 `rule`이 없어 econ 백필이 `23514`로 크래시했고, 그 크래시가
actual 적재 앞단계에서 일어나 `macro.economic_observations`가 0으로 남았다. 로그에는
"ECON actual OK"가 30줄 찍혀 있었다 — 받아 놓고 저장 전에 죽은 것이다.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from investment_agent.data.macro.domain.releases.schedule import (
    ScheduleContractError,
    schedule_window,
)

ROOT = Path(__file__).resolve().parents[4]
SQL = ROOT / "db" / "postgres" / "v1" / "40_macro.sql"

_CHECK = re.compile(
    r"schedule_precision\s+text\s+NOT\s+NULL\s*(?:--[^\n]*\n\s*)?"
    r"CHECK\s*\(\s*schedule_precision\s+IN\s*\(([^)]*)\)",
    re.S,
)


def _declared_precisions() -> set[str]:
    match = _CHECK.search(SQL.read_text(encoding="utf-8"))
    assert match, "40_macro.sql에서 schedule_precision CHECK를 찾지 못했다"
    return set(re.findall(r"'([a-z_]+)'", match.group(1)))


def _domain_precisions() -> set[str]:
    found = set()
    for candidate in ("exact", "rule", "date_only", "estimated", "unknown", "approximate"):
        try:
            schedule_window(candidate)
        except ScheduleContractError:
            continue
        found.add(candidate)
    return found


class SchedulePrecisionContractTest(unittest.TestCase):
    def test_storage_accepts_every_precision_the_domain_defines(self) -> None:
        missing = sorted(_domain_precisions() - _declared_precisions())
        self.assertEqual([], missing, "저장소 CHECK가 도메인보다 좁다")

    def test_storage_declares_nothing_the_domain_cannot_use(self) -> None:
        """반대 방향도 본다 — 쓰지 않는 값을 받아 두면 오타가 그대로 저장된다."""
        extra = sorted(_declared_precisions() - _domain_precisions())
        self.assertEqual([], extra)

    def test_the_scan_reads_the_real_values(self) -> None:
        """대상을 못 찾으면 위 두 검사는 공허하게 통과한다."""
        self.assertIn("rule", _domain_precisions())
        self.assertIn("rule", _declared_precisions())


if __name__ == "__main__":
    unittest.main()
