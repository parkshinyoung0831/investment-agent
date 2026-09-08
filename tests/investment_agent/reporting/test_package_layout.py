"""Reporting의 배치를 못박는다.

reporting이 존재하는 이유는 "이 값이 어느 저장소에서 오는가"를 화면과 알림에서
감추는 것이다. 그러니 **저장소를 여는 자리는 셀 수 있어야** 한다.

* `readers/` — 저장소를 여는 곳. 파일 이름이 무엇을 여는지 말한다.
* `notifications/` — 알림 종류별 read model. CLAUDE.md 규칙 15가 이름을 정한 자리다.
* `services/` — 읽어 온 것을 주제별로 조립만 한다. 저장소를 열지 않는다.

한 파일짜리 중간 패키지도 만들지 않는다 — 경로만 길어지고 읽는 사람이 얻는 것이 없다.
"""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path("src/investment_agent/reporting")
STORE_MODULES = (
    "investment_agent.platform.db.postgres",
    "investment_agent.platform.db.sqlite",
    "investment_agent.platform.db.duckdb",
)


def _opens_a_store(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    return [name for name in STORE_MODULES if name in source]


class ReportingPackageLayoutTest(unittest.TestCase):
    def test_single_file_wrappers_are_flattened(self) -> None:
        removed = (
            ROOT / "readers" / "intelligence",
            ROOT / "econ_calendar",
            ROOT / "fundamentals",
            ROOT / "strategy",
        )
        for path in removed:
            with self.subTest(path=path):
                self.assertFalse(tuple(path.glob("*.py")))

    def test_services_do_not_open_stores_themselves(self) -> None:
        offenders = [
            f"{path.as_posix()} -> {name}"
            for path in (ROOT / "services").rglob("*.py")
            for name in _opens_a_store(path)
        ]
        self.assertEqual([], sorted(offenders))

    def test_only_readers_and_notifications_open_stores(self) -> None:
        """저장소를 여는 자리가 늘어나면 reporting이 감추는 것이 없어진다."""
        allowed = {"readers", "notifications"}
        offenders = [
            path.as_posix()
            for path in ROOT.rglob("*.py")
            if _opens_a_store(path) and not (set(path.relative_to(ROOT).parts) & allowed)
        ]
        self.assertEqual([], sorted(offenders))

    def test_read_models_keep_descriptive_names(self) -> None:
        expected = (
            ROOT / "readers" / "intelligence.py",
            ROOT / "readers" / "dashboard.py",
            ROOT / "readers" / "financial.py",
            ROOT / "services" / "economic_releases.py",
            ROOT / "services" / "fundamental_segments.py",
            ROOT / "services" / "strategy_labels.py",
        )
        for path in expected:
            with self.subTest(path=path):
                self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
