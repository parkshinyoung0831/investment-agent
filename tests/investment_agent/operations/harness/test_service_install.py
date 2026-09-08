from __future__ import annotations

import plistlib
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from investment_agent.operations.commands.install_investment_harness import _plans, _require_apply_environment
from investment_agent.operations.harness.service_install import (
    INSTALL_CONFIRMATION,
    apply_install_plan,
    macos_launchd_plan,
    windows_task_plan,
)


class ServiceInstallTest(unittest.TestCase):
    def test_apply_preflight_reports_names_but_never_secret_values(self):
        with mock.patch.dict("os.environ", {
            "SUPABASE_URL": "https://safe.invalid",
            "SUPABASE_SERVICE_KEY": "secret-service-value",
        }, clear=True):
            with self.assertRaises(RuntimeError) as raised:
                _require_apply_environment(
                    service="approval-listener",
                    mode="analysis_only",
                )
        message = str(raised.exception)
        self.assertIn("DISCORD_APPROVAL_BOT_TOKEN", message)
        self.assertIn("DISCORD_APPROVER_USER_IDS", message)
        self.assertNotIn("secret-service-value", message)

    def test_windows_plan_has_no_secret_and_restarts_without_duplicate_instance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            plan = windows_task_plan(
                python_executable=root / "python.exe",
                repository_root=root,
                state_dir=root / "state",
                user_id="local-user",
            )
            rendered = repr(plan.to_dict()).upper()
            self.assertIn("SCHTASKS", rendered)
            root_xml = ET.fromstring(plan.descriptor_text)
            namespace = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
            self.assertEqual(root_xml.findtext(".//t:RunLevel", namespaces=namespace), "LeastPrivilege")
            self.assertEqual(root_xml.findtext(".//t:Principal/t:UserId", namespaces=namespace), "local-user")
            self.assertEqual(root_xml.findtext(".//t:MultipleInstancesPolicy", namespaces=namespace), "IgnoreNew")
            self.assertEqual(root_xml.findtext(".//t:RestartOnFailure/t:Interval", namespaces=namespace), "PT1M")
            self.assertNotIn("TOSS_CLIENT", rendered)
            self.assertNotIn("SUPABASE_SERVICE", rendered)
            self.assertNotIn("DISCORD_BOT_TOKEN", rendered)

    def test_macos_plan_is_valid_plist_with_working_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            plan = macos_launchd_plan(
                python_executable=root / "python",
                repository_root=root,
                state_dir=root / "state",
                launch_agents_dir=root / "LaunchAgents",
                uid=501,
            )
            payload = plistlib.loads(plan.descriptor_text.encode("utf-8"))
            self.assertEqual(payload["WorkingDirectory"], str(root))
            self.assertIn("--serve", payload["ProgramArguments"])
            self.assertEqual(plan.register_command[:2], ("launchctl", "bootstrap"))

    def test_discord_gateway_is_a_distinct_restartable_service(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            windows = windows_task_plan(
                python_executable=root / "python.exe",
                repository_root=root,
                state_dir=root / "state",
                label="com.local.investment-ai-approval-listener",
                entry_module="investment_agent.operations.commands.approval_listener",
                entry_arguments=(),
                descriptor_filename="approval.task.xml",
                user_id="local-user",
            )
            self.assertIn("approval_listener", windows.descriptor_text)
            self.assertNotEqual(windows.label, "com.local.investment-ai-harness")
            self.assertIn("IgnoreNew", windows.descriptor_text)

            macos = macos_launchd_plan(
                python_executable=root / "python",
                repository_root=root,
                state_dir=root / "state",
                launch_agents_dir=root / "LaunchAgents",
                label="com.local.investment-ai-approval-listener",
                entry_module="investment_agent.operations.commands.approval_listener",
                entry_arguments=(),
                log_prefix="approval_listener",
                uid=501,
            )
            payload = plistlib.loads(macos.descriptor_text.encode("utf-8"))
            self.assertIn("investment_agent.operations.commands.approval_listener", payload["ProgramArguments"])
            self.assertTrue(payload["KeepAlive"])

    def test_default_bundle_uses_locked_ops_wrapper_for_gateway(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            plans = _plans(
                platform="windows",
                common={
                    "python_executable": root / "python.exe",
                    "repository_root": root,
                    "state_dir": root / "state",
                },
                service="all",
                mode="analysis_only",
            )
            self.assertEqual(len(plans), 2)
            self.assertIn(
                "investment_agent.operations.commands.approval_listener_service",
                plans[1].descriptor_text,
            )
            self.assertIn("--state-dir", plans[1].descriptor_text)

    def test_dry_run_does_not_write_or_call_os_and_apply_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            plan = windows_task_plan(
                python_executable=root / "python.exe",
                repository_root=root,
                state_dir=root / "state",
            )
            runner = mock.Mock()
            self.assertFalse(apply_install_plan(plan, runner=runner))
            self.assertFalse(Path(plan.descriptor_path).exists())
            runner.assert_not_called()
            with self.assertRaisesRegex(ValueError, "requires --confirm"):
                apply_install_plan(
                    plan, apply=True, confirm="wrong", current_platform="windows", runner=runner,
                )

    def test_explicit_apply_writes_descriptor_and_uses_argument_list(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            plan = windows_task_plan(
                python_executable=root / "python.exe",
                repository_root=root,
                state_dir=root / "state",
            )
            runner = mock.Mock()
            applied = apply_install_plan(
                plan,
                apply=True,
                confirm=INSTALL_CONFIRMATION,
                current_platform="windows",
                runner=runner,
            )
            self.assertTrue(applied)
            self.assertTrue(Path(plan.descriptor_path).exists())
            args, kwargs = runner.call_args
            self.assertIsInstance(args[0], list)
            self.assertFalse(kwargs["shell"])


if __name__ == "__main__":
    unittest.main()
