"""CLI가 기록한 정비 보류와 잠금을 기본 라이브러리도 같은 위치에서 읽는다."""
from __future__ import annotations

import unittest
from pathlib import Path

from investment_agent.operations.paths import REPOSITORY_ROOT, HARNESS_STATE_DIR
from investment_agent.operations.harness import emergency, maintenance, switch
from investment_agent.operations.commands import harness_switch, investment_harness


class DefaultPathsTest(unittest.TestCase):
    def test_paths_refer_to_repository_not_src_directory(self):
        expected = Path(__file__).resolve().parents[4]
        self.assertEqual(expected, REPOSITORY_ROOT)
        self.assertTrue((expected / "AGENTS.md").is_file())
        self.assertEqual(expected / "artifacts/ops/investment_harness", HARNESS_STATE_DIR)
        self.assertEqual(HARNESS_STATE_DIR / "MAINTENANCE_HOLD", maintenance.get_maintenance_path())
        self.assertEqual(HARNESS_STATE_DIR / "EXECUTION_LOCKDOWN", emergency.get_lockdown_path())
        for module in (switch, harness_switch, investment_harness):
            self.assertEqual(HARNESS_STATE_DIR, module._DEFAULT_STATE_DIR)
