"""대시보드가 읽는 로컬 산출물 경로가 쓰는 쪽과 같은 곳을 가리킨다(DB-01).

`parents[N]`로 깊이를 세던 시절에는 화면이 `src/artifacts/...`를 읽어, 하네스 상태 파일이
있어도 항상 "없음"으로 나왔다. 존재 여부는 환경마다 달라 계약이 못 되므로, 쓰는 쪽(operations·research)의
경로와 같은지를 묻는다.
"""
from __future__ import annotations

import unittest

from investment_agent.dashboard import ops as dashboard_ops
from investment_agent.dashboard.app_pages import system
from investment_agent.operations.paths import HARNESS_STATE_DIR
from investment_agent.platform.storage_paths import repository_root


class DashboardStoragePathAgreementTest(unittest.TestCase):
    def test_harness_state_path_matches_the_writer(self) -> None:
        expected = HARNESS_STATE_DIR / "state.json"
        self.assertEqual(dashboard_ops.DEFAULT_HARNESS_STATE, expected)
        self.assertEqual(system.STATE_PATH, expected)

    def test_artifacts_live_at_repository_root_not_under_src(self) -> None:
        root = repository_root()
        for path in (dashboard_ops.DEFAULT_HARNESS_STATE,):
            self.assertEqual(path.relative_to(root).parts[0], "artifacts")


if __name__ == "__main__":
    unittest.main()
