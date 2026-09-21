"""전역 거래 스위치를 읽는 곳이 모두 같은 답을 낸다(OP-06).

실주문 게이트는 `TRADING_KILL_SWITCH`가 정확히 `off`일 때만 풀린다. 하네스·점검·대시보드가 `false`·`0`·`no`를
OFF로 읽으면 화면은 "주문 가능"인데 게이트는 막혀 있다.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from investment_agent.config import Config
from investment_agent.execution.safety.control import LiveTradingControls
from investment_agent.dashboard.app_pages.system import _kill_switch_label
from investment_agent.operations.harness.contracts import HarnessMode
from investment_agent.operations.harness.emergency import check_runtime_status
from investment_agent.operations.harness.kill_switches import KillSwitches
from investment_agent.operations.harness.security_audit import _check_kill_switches
from investment_agent.platform.trading_switch import kill_switch_on, live_enabled

# (환경변수 값, 켜진 것으로 읽어야 하는가)
KILL_CASES = [(None, True), ("", True), ("  ", True), ("on", True), ("ON", True), ("true", True), ("1", True),
              ("false", True), ("0", True), ("no", True), ("disabled", True), ("of", True),
              ("off", False), ("OFF", False), (" off ", False)]
LIVE_CASES = [(None, False), ("", False), ("false", False), ("1", False), ("yes", False), ("on", False),
              ("enabled", False), ("true", True), ("TRUE", True), (" true ", True)]


class TradingSwitchRuleTest(unittest.TestCase):
    def test_rule_matches_the_execution_gate(self) -> None:
        for raw, expected in KILL_CASES:
            with self.subTest(kill=raw):
                values = {"TOSS_ACCOUNT_SEQ": "1"}
                if raw is not None:
                    values["TRADING_KILL_SWITCH"] = raw
                controls = LiveTradingControls.from_config(Config(env=values, dotenv_path=None, dotenv_loaded=False))
                self.assertEqual(controls.kill_switch_on, expected)
                self.assertEqual(kill_switch_on(raw), expected)
        for raw, expected in LIVE_CASES:
            with self.subTest(live=raw):
                values = {"TOSS_ACCOUNT_SEQ": "1"}
                if raw is not None:
                    values["TOSS_LIVE_ENABLED"] = raw
                self.assertEqual(LiveTradingControls.from_config(Config(env=values, dotenv_path=None, dotenv_loaded=False)).live_enabled, expected)
                self.assertEqual(live_enabled(raw), expected)

    def test_harness_stage_gate_reads_the_same_rule(self) -> None:
        for raw, expected in KILL_CASES:
            with self.subTest(kill=raw):
                env = {} if raw is None else {"TRADING_KILL_SWITCH": raw}
                self.assertEqual(KillSwitches(env).trading_blocked, expected)

    def test_status_readouts_agree_with_the_gate(self) -> None:
        for raw, expected in KILL_CASES:
            with self.subTest(kill=raw):
                env = {} if raw is None else {"TRADING_KILL_SWITCH": raw}
                with tempfile.TemporaryDirectory() as temp:
                    status = check_runtime_status(state_dir=Path(temp), environ=env)
                self.assertEqual(status["trading_kill_switch"], "on" if expected else "off")
                with mock.patch.dict("os.environ", env, clear=True):
                    label, _detail = _kill_switch_label()
                self.assertEqual(label.startswith("ON"), expected)

    def test_security_audit_reports_armed_only_when_the_gate_is_open(self) -> None:
        for raw, expected in KILL_CASES:
            with self.subTest(kill=raw):
                env = {} if raw is None else {"TRADING_KILL_SWITCH": raw}
                codes = {item.code for item in _check_kill_switches(env, HarnessMode.APPROVAL_WORKFLOW)}
                self.assertEqual("TRADING_KILL_SWITCH_ACTIVE" in codes, expected)

    def test_job_kill_switch_keeps_its_own_lenient_default_off(self) -> None:
        # job별 스위치는 거래 스위치가 아니다: 없으면 꺼져 있고, 알 수 없는 값만 켜진 것으로 본다.
        self.assertFalse(KillSwitches({}).job_blocked("x"))
        self.assertTrue(KillSwitches({"HARNESS_JOB_X_KILL_SWITCH": "garbage"}).job_blocked("x"))


if __name__ == "__main__":
    unittest.main()
