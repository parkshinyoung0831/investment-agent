from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import launcher


def _touch(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _runtime(version: tuple[int, int, int] = (3, 12, 0)) -> launcher.RuntimeProbe:
    return launcher.RuntimeProbe(version=version)


class DashboardLauncherPreflightTest(unittest.TestCase):
    def test_dashboard_allows_missing_env_as_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _touch(root / ".venv" / "Scripts" / "python.exe")
            _touch(root / ".venv" / "Scripts" / "streamlit.exe")
            _touch(root / "src" / "investment_agent" / "dashboard" / "app.py")

            report = launcher.build_preflight_report(
                "dashboard",
                root=root,
                effective_env={},
                runtime=_runtime(),
            )

        self.assertTrue(report.ok)
        warning_text = " ".join(report.warnings)
        self.assertIn(".env", warning_text)
        self.assertIn("SUPABASE_URL", warning_text)
        self.assertIn("SUPABASE_SERVICE_KEY", warning_text)

    def test_dashboard_requires_app(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _touch(root / ".venv" / "Scripts" / "python.exe")
            report = launcher.build_preflight_report(
                "dashboard",
                root=root,
                effective_env={
                    "SUPABASE_URL": "https://example.invalid",
                    "SUPABASE_SERVICE_KEY": "secret",
                },
                runtime=_runtime(),
            )

        self.assertFalse(report.ok)
        error_text = " ".join(report.errors)
        self.assertIn("대시보드 앱", error_text)

    def test_harness_blocks_missing_core_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _touch(root / ".venv" / "Scripts" / "python.exe")
            _touch(root / ".env", "# test\n")
            _touch(
                root
                / "src"
                / "investment_agent"
                / "operations"
                / "commands"
                / "investment_harness.py"
            )
            effective = {name: "configured" for name in launcher.HARNESS_REQUIRED_ENV}
            effective.pop("DISCORD_APPROVER_USER_IDS")

            report = launcher.build_preflight_report(
                "harness",
                root=root,
                effective_env=effective,
                runtime=_runtime(),
            )

        self.assertFalse(report.ok)
        self.assertIn("DISCORD_APPROVER_USER_IDS", " ".join(report.errors))

    def test_harness_allows_injected_environment_without_env_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _touch(root / ".venv" / "Scripts" / "python.exe")
            _touch(
                root
                / "src"
                / "investment_agent"
                / "operations"
                / "commands"
                / "investment_harness.py"
            )
            effective = {name: "configured" for name in launcher.HARNESS_REQUIRED_ENV}

            report = launcher.build_preflight_report(
                "harness",
                root=root,
                effective_env=effective,
                runtime=_runtime(),
            )

        self.assertTrue(report.ok)
        self.assertIn(".env", " ".join(report.warnings))

    def test_harness_accepts_singular_approver_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _touch(root / ".venv" / "Scripts" / "python.exe")
            _touch(root / ".env", "# test\n")
            _touch(
                root
                / "src"
                / "investment_agent"
                / "operations"
                / "commands"
                / "investment_harness.py"
            )
            effective = {name: "configured" for name in launcher.HARNESS_REQUIRED_ENV}
            effective.pop("DISCORD_APPROVER_USER_IDS")
            effective["DISCORD_APPROVER_USER_ID"] = "configured"

            report = launcher.build_preflight_report(
                "harness",
                root=root,
                effective_env=effective,
                runtime=_runtime(),
            )

        self.assertTrue(report.ok)

    def test_old_python_and_missing_imports_are_blockers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _touch(root / ".venv" / "Scripts" / "python.exe")
            _touch(root / ".venv" / "Scripts" / "streamlit.exe")
            _touch(root / "src" / "investment_agent" / "dashboard" / "app.py")
            report = launcher.build_preflight_report(
                "dashboard",
                root=root,
                effective_env={},
                runtime=launcher.RuntimeProbe(
                    version=(3, 10, 9),
                    missing_imports=("streamlit", "plotly"),
                ),
            )

        error_text = " ".join(report.errors)
        self.assertIn("Python 3.11", error_text)
        self.assertIn("streamlit", error_text)
        self.assertIn("plotly", error_text)

    def test_the_project_itself_is_part_of_the_import_check(self):
        """`.venv`에 의존성만 있고 이 저장소가 안 깔린 상태가 실제로 있었다.

        서드파티만 세면 사전 점검이 "이상 없음"이라 말한 뒤 앱이
        `ModuleNotFoundError: investment_agent`로 죽는다 — run.bat과
        dashboard.bat이 둘 다 그 자리에서 멈췄다.
        """
        for modules in (launcher.DASHBOARD_IMPORTS, launcher.HARNESS_IMPORTS):
            with self.subTest(modules=modules):
                self.assertIn("investment_agent", modules)

    def test_a_missing_project_install_names_how_to_repair_it(self):
        """모듈 이름만 알려주면 무엇을 실행해야 하는지 알 수 없다."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _touch(root / ".venv" / "Scripts" / "python.exe")
            _touch(root / ".venv" / "Scripts" / "streamlit.exe")
            _touch(root / "src" / "investment_agent" / "dashboard" / "app.py")
            report = launcher.build_preflight_report(
                "dashboard",
                root=root,
                effective_env={"SUPABASE_URL": "x", "SUPABASE_SERVICE_KEY": "y"},
                runtime=launcher.RuntimeProbe(
                    version=(3, 12, 0),
                    missing_imports=("investment_agent",),
                ),
            )

        error_text = " ".join(report.errors)
        self.assertIn("investment_agent", error_text)
        self.assertIn("uv sync", error_text)
        self.assertFalse(report.ok)

    def test_corrupt_state_blocks_harness_but_only_warns_dashboard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _touch(root / ".venv" / "Scripts" / "python.exe")
            _touch(root / ".venv" / "Scripts" / "streamlit.exe")
            _touch(root / ".env", "# test\n")
            _touch(root / "src" / "investment_agent" / "dashboard" / "app.py")
            _touch(
                root
                / "src"
                / "investment_agent"
                / "operations"
                / "commands"
                / "investment_harness.py"
            )
            _touch(
                root / "artifacts" / "ops" / "investment_harness" / "state.json",
                "not-json",
            )
            effective = {name: "configured" for name in launcher.HARNESS_REQUIRED_ENV}

            harness = launcher.build_preflight_report(
                "harness",
                root=root,
                effective_env=effective,
                runtime=_runtime(),
            )
            dashboard = launcher.build_preflight_report(
                "dashboard",
                root=root,
                effective_env=effective,
                runtime=_runtime(),
            )

        self.assertFalse(harness.ok)
        self.assertTrue(dashboard.ok)
        self.assertIn("상태 파일", " ".join(harness.errors))
        self.assertIn("상태 파일", " ".join(dashboard.warnings))


class DashboardLauncherPortTest(unittest.TestCase):
    def test_finds_first_available_port_in_bounded_range(self):
        checked: list[int] = []

        def available(port: int) -> bool:
            checked.append(port)
            return port == 8503

        selected = launcher.find_available_port(8501, 8505, available=available)

        self.assertEqual(selected, 8503)
        self.assertEqual(checked, [8501, 8502, 8503])

    def test_returns_none_when_bounded_range_is_full(self):
        selected = launcher.find_available_port(
            8501,
            8503,
            available=lambda _port: False,
        )

        self.assertIsNone(selected)

    def test_rejects_invalid_port_range(self):
        with self.assertRaises(ValueError):
            launcher.find_available_port(8510, 8501)


class DashboardLauncherSafetyStateTest(unittest.TestCase):
    def test_safe_defaults_are_display_only(self):
        environment: dict[str, str] = {}

        kill_text, live_text = launcher._safety_state(environment)

        self.assertIn("ON", kill_text)
        self.assertIn("false", live_text)
        self.assertEqual(environment, {})

    def test_kill_switch_tokens_match_harness_parser(self):
        for value in ("0", "off", "false", "no", " OFF "):
            with self.subTest(value=value):
                kill_text, _ = launcher._safety_state({"TRADING_KILL_SWITCH": value})
                self.assertIn("OFF", kill_text)

        for value in ("1", "on", "true", "yes", " ON ", "typo", ""):
            with self.subTest(value=value):
                kill_text, _ = launcher._safety_state({"TRADING_KILL_SWITCH": value})
                self.assertIn("ON", kill_text)


class DashboardLauncherCliTest(unittest.TestCase):
    def test_dashboard_flag_selects_read_only_launch_path(self):
        args = launcher.parse_args(["--dashboard"])

        self.assertTrue(args.dashboard)
        self.assertFalse(args.harness)

    def test_harness_shortcuts_use_single_switch_entrypoint(self):
        for mode in ("analysis_only", "approval_workflow"):
            with self.subTest(mode=mode):
                command = launcher.harness_switch_command(mode)

                self.assertIn("investment_agent.operations.commands.harness_switch", command)
                self.assertIn("--on", command)
                self.assertEqual(command[-2:], ["--mode", mode])
                self.assertNotIn("investment_agent.operations.commands.investment_harness", command)
                self.assertNotIn("--serve", command)

    def test_shadow_and_approval_shortcuts_dispatch_through_switch(self):
        for runner, mode in (
            (launcher.run_shadow_harness, "analysis_only"),
            (launcher.run_harness, "approval_workflow"),
        ):
            with (
                self.subTest(mode=mode),
                mock.patch.object(launcher, "clear_screen"),
                mock.patch.object(
                    launcher,
                    "run_preflight",
                    return_value=(launcher.PreflightReport(), {}),
                ),
                mock.patch.object(
                    launcher.subprocess,
                    "run",
                    return_value=mock.Mock(returncode=0),
                ) as run_mock,
            ):
                self.assertEqual(runner(), 0)

                command = run_mock.call_args.args[0]
                self.assertIn("investment_agent.operations.commands.harness_switch", command)
                self.assertEqual(command[-2:], ["--mode", mode])

    def test_main_menu_only_exposes_two_task_groups(self):
        with (
            mock.patch.object(launcher, "clear_screen"),
            mock.patch("builtins.input", return_value="0"),
            mock.patch("builtins.print") as print_mock,
        ):
            exit_code = launcher.interactive_menu()

        rendered = "\n".join(
            " ".join(str(value) for value in call.args)
            for call in print_mock.call_args_list
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("[1] ATLAS 운영 제어센터", rendered)
        self.assertIn("[2] 점검·개발 도구", rendered)
        self.assertNotIn("[9]", rendered)

    def test_main_menu_opens_control_center_and_returns(self):
        with (
            mock.patch.object(launcher, "clear_screen"),
            mock.patch("builtins.input", side_effect=("1", "0")),
            mock.patch(
                "investment_agent.operations.control_center.run_control_center",
                return_value=0,
            ) as control_center,
        ):
            exit_code = launcher.interactive_menu()

        self.assertEqual(exit_code, 0)
        control_center.assert_called_once_with()

    def test_developer_tools_menu_dispatches_and_returns(self):
        with (
            mock.patch.object(launcher, "clear_screen"),
            mock.patch("builtins.input", side_effect=("1", "0")),
            mock.patch.object(launcher, "run_ai_dry_run") as dry_run,
        ):
            launcher.developer_tools_menu()

        dry_run.assert_called_once_with()

    def test_discord_test_requires_exact_send_confirmation(self):
        with (
            mock.patch.object(launcher, "clear_screen"),
            mock.patch("builtins.input", side_effect=("send", "")),
            mock.patch.object(launcher.subprocess, "run") as run_mock,
        ):
            exit_code = launcher.run_test_notify()

        self.assertEqual(exit_code, 0)
        run_mock.assert_not_called()

    def test_windows_batch_launchers_use_crlf_and_project_venv(self):
        """모든 .bat은 CRLF여야 하고, 시스템 python이 아니라 프로젝트 .venv를 쓴다.

        LF로 저장되면 cmd.exe가 마지막 줄을 삼켜 조용히 아무것도 실행되지 않고,
        시스템 python을 쓰면 의존성이 달라 같은 명령이 기계마다 다르게 돈다.
        """
        root = Path(__file__).resolve().parents[1]
        batches = sorted(
            path for path in root.rglob("*.bat")
            if ".venv" not in path.parts and ".git" not in path.parts
        )
        self.assertTrue(batches, "실행용 .bat이 하나도 없다")
        for path in batches:
            with self.subTest(name=str(path.relative_to(root))):
                content = path.read_bytes()
                self.assertIn(b"\r\n", content)
                self.assertNotIn(b"\n", content.replace(b"\r\n", b""))
                self.assertIn(b".venv\\Scripts\\python.exe", content)

    def test_only_one_batch_entry_point_sits_at_the_repository_root(self):
        """루트에는 run.bat 하나만 둔다 — 나머지는 목적별 scripts/ 하위에 있다."""
        root = Path(__file__).resolve().parents[1]
        self.assertEqual([path.name for path in sorted(root.glob("*.bat"))], ["run.bat"])

    def test_dashboard_retries_when_selected_port_is_taken_during_start(self):
        first_failure = mock.Mock(returncode=1)
        second_success = mock.Mock(returncode=0)
        with (
            mock.patch.object(launcher, "clear_screen"),
            mock.patch.object(
                launcher,
                "run_preflight",
                return_value=(launcher.PreflightReport(), {}),
            ),
            mock.patch.object(
                launcher,
                "find_available_port",
                side_effect=(8501, 8502),
            ),
            mock.patch.object(
                launcher,
                "is_port_available",
                return_value=False,
            ),
            mock.patch.object(
                launcher.subprocess,
                "run",
                side_effect=(first_failure, second_success),
            ) as run_mock,
        ):
            exit_code = launcher.run_dashboard()

        self.assertEqual(exit_code, 0)
        self.assertEqual(run_mock.call_count, 2)
        first_command = run_mock.call_args_list[0].args[0]
        second_command = run_mock.call_args_list[1].args[0]
        self.assertIn("--server.address=127.0.0.1", first_command)
        self.assertIn("--server.port=8501", first_command)
        self.assertIn("--server.port=8502", second_command)


if __name__ == "__main__":
    unittest.main()
