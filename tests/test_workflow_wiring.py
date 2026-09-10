"""워크플로 배선 회귀 테스트 — 어긋나도 조용히 실패하는 것들만 지킨다.

여기 걸린 규칙은 전부 "틀려도 CI가 초록이고, 알림만 안 온다" 부류다:
workflow_run이 참조하는 이름이 안 맞으면 발화하지 않고, 발송 워크플로가 concurrency
그룹을 공유하지 않으면 같은 공시가 두 번 나갈 수 있다.

PyYAML을 쓰지 않고 텍스트로 확인한다 — 테스트는 외부 의존성 없이 도는 게 관례다.
"""
from __future__ import annotations

import ast
import re
import sys
import tomllib
import unittest
from pathlib import Path

_WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
_PROJECT_ROOT = _WORKFLOWS.parents[1]
# 관심종목 공시를 실제로 Discord로 보내는 워크플로. 서로 겹치면 중복 발송이 난다.
_EARNINGS_SENDERS = ("notify_fundamentals",)
_RUNTIME_LEDGER_SCOPES = {
    "notify_macro_core": "macro",
    "notify_macro_watch": "macro",
    "notify_fundamentals": "fundamentals",
    "notify_fundamentals_calendar": "fundamentals",
    "notify_econ_calendar_release": "macro-releases",
    "econ_calendar_watch": "macro-releases",
    "institutional_13f": "institutional",
    "notify_strategy": "strategy",
    "notify_bootstrap": "bootstrap",
    "notify_investment": "investment",
}


def _text(name: str) -> str:
    return (_WORKFLOWS / f"{name}.yml").read_text(encoding="utf-8")


def _crons(name: str) -> list[str]:
    """워크플로의 schedule cron 목록(주석 처리된 줄은 제외)."""
    body = "\n".join(
        line for line in _text(name).splitlines() if not line.lstrip().startswith("#")
    )
    return re.findall(
        r"^\s*-\s*cron:\s*[\"']([^\"']+)[\"']",
        body,
        re.MULTILINE,
    )


def _workflow_names() -> set[str]:
    return {path.stem for path in _WORKFLOWS.glob("*.yml")}


def _group_requirements(name: str) -> str:
    """pyproject의 dependency group을 include-group까지 펼친다."""
    groups = tomllib.loads((_PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["dependency-groups"]
    pending = [name]
    seen: set[str] = set()
    requirements: list[str] = []
    while pending:
        group = pending.pop()
        if group in seen:
            continue
        seen.add(group)
        for dependency in groups[group]:
            if isinstance(dependency, dict):
                pending.append(dependency["include-group"])
            else:
                requirements.append(dependency)
    return "\n".join(requirements)


# import 이름과 배포 패키지 이름이 다른 것들. 나머지는 이름이 같다고 본다.
_DISTRIBUTION_NAMES = {
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "yaml": "pyyaml",
    "PIL": "pillow",
    "sklearn": "scikit-learn",
}


def _entry_modules(name: str) -> list[str]:
    """워크플로가 실제로 실행하는 `python -m investment_agent....` 진입점들."""
    return sorted(set(re.findall(r"python -m (investment_agent\.[A-Za-z0-9_.]+)", _text(name))))


def _workflow_groups(name: str) -> list[str]:
    """composite action과 인라인 uv 설치가 요청하는 의존성 그룹."""
    text = _text(name)
    return sorted(set(
        re.findall(r"uv sync --locked --no-dev --group ([A-Za-z0-9_-]+)", text)
        + re.findall(
            r"uses: \./\.github/actions/python-job\s*\n\s*with:\s*\n\s*group:\s*([A-Za-z0-9_-]+)",
            text,
        )
    ))


def _module_path(module: str) -> Path | None:
    base = _WORKFLOWS.parents[1] / "src" / Path(*module.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.exists():
            return candidate
    return None


def _imported_names(node: ast.AST) -> list[str]:
    """이 import 문이 실제로 불러들이는 모듈 후보들.

    `from pkg import mod`는 pkg뿐 아니라 pkg.mod도 불러온다. 후자를 놓치면
    패키지 `__init__.py`만 보고 정작 무거운 의존성을 가진 모듈을 지나친다.
    """
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        if node.level:  # 상대 import는 같은 패키지 안이다.
            return []
        module = node.module or ""
        return [module] + [f"{module}.{alias.name}" for alias in node.names]
    return []


def _third_party_imports(module: str) -> set[str]:
    """진입점에서 도달하는 src 모듈들의 **모듈 레벨** 서드파티 import를 모은다.

    src 간선은 함수 안 지연 import까지 따라간다 — 그 모듈에 닿는 순간 모듈 레벨
    코드가 실행되기 때문이다. 반대로 서드파티는 모듈 레벨만 센다: 이 저장소는
    무거운 의존성을 일부러 함수 안에서 부르고(관례 5), 그런 import는 해당 분기가
    돌 때만 필요하므로 정적으로는 필요 여부를 알 수 없다.

    fundamentals_backfill이 죽은 경로가 정확히 전자였다 — entry가 fsds를 함수 안에서
    부르지만, fsds.py는 모듈 레벨에서 secfsdstools를 import한다.
    """
    stdlib = set(sys.stdlib_module_names)
    found: set[str] = set()
    seen: set[str] = set()
    pending = [module]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        path = _module_path(current)
        if path is None:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        top_level = {id(node) for node in tree.body}
        for node in ast.walk(tree):
            for name in _imported_names(node):
                if name.startswith("investment_agent."):
                    pending.append(name)
                    continue
                top = name.split(".")[0]
                if not top or top == "investment_agent" or top in stdlib:
                    continue
                if id(node) in top_level:
                    found.add(top)
    return found


class WorkflowNameTest(unittest.TestCase):
    """CLAUDE.md 관례 11 — name:이 파일명과 다르면 workflow_run이 발화하지 않는다."""

    def test_every_workflow_name_matches_its_filename(self):
        for path in sorted(_WORKFLOWS.glob("*.yml")):
            with self.subTest(workflow=path.name):
                first = path.read_text(encoding="utf-8").splitlines()[0]
                self.assertEqual(first, f"name: {path.stem}")

    def test_top_level_workflow_sections_are_not_duplicated(self):
        """이어 붙은 YAML은 파서가 뒤 키를 택해 앞쪽 결함을 조용히 숨길 수 있다."""
        for path in sorted(_WORKFLOWS.glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            for key in ("name", "on", "permissions", "jobs"):
                with self.subTest(workflow=path.name, key=key):
                    self.assertEqual(
                        len(re.findall(rf"(?m)^{key}:", text)),
                        1,
                    )

    def test_workflow_run_references_resolve_to_real_workflows(self):
        known = _workflow_names()
        pattern = re.compile(r'workflows:\s*\[([^\]]*)\]')
        for path in sorted(_WORKFLOWS.glob("*.yml")):
            for group in pattern.findall(path.read_text(encoding="utf-8")):
                for raw in group.split(","):
                    referenced = raw.strip().strip('"').strip("'")
                    if not referenced:
                        continue
                    with self.subTest(workflow=path.name, references=referenced):
                        self.assertIn(referenced, known)


class UniverseCadenceTest(unittest.TestCase):
    def test_membership_check_runs_three_times_per_week_after_us_close(self):
        self.assertEqual(_crons("universe_membership_check"), ["40 22 * * 1,3,5"])

    def test_universe_workflows_dispatch_only_after_a_real_change(self):
        for name in ("universe_monthly", "universe_membership_check"):
            with self.subTest(workflow=name):
                text = _text(name)
                self.assertIn("actions: write", text)
                self.assertIn("steps.universe.outputs.changed == 'true'", text)
                self.assertIn("gh workflow run market_backfill.yml", text)
                self.assertIn("gh workflow run fundamentals_backfill.yml", text)
                self.assertIn("gh workflow run fundamentals_dimensions_backfill.yml", text)

    def test_backfills_are_manual_dispatch_targets_not_unconditional_followers(self):
        for name in (
            "market_backfill",
            "fundamentals_backfill",
            "fundamentals_dimensions_backfill",
        ):
            with self.subTest(workflow=name):
                text = _text(name)
                self.assertIn("workflow_dispatch:", text)
                self.assertNotIn("workflow_run:", text)


class NotifyChainTest(unittest.TestCase):
    def test_notify_fundamentals_follows_both_etl_paths(self):
        text = _text("notify_fundamentals")

        self.assertIn("fundamentals_daily", text)
        self.assertIn("fundamentals_watchlist_fast", text)

    def test_notify_fundamentals_keeps_a_safety_net_cron(self):
        # workflow_run이 발화하지 않는 경우(브랜치 조건·재시도 등)를 덮는 하루 1회.
        self.assertIn("schedule:", _text("notify_fundamentals"))

    def test_notify_is_not_gated_on_etl_success(self):
        """무관한 CIK 하나로 ETL이 exit 1 하는 일이 잦다 — success로 잠그면 알림이 묻힌다."""
        # 주석은 이 규칙을 설명하느라 같은 문구를 담으므로 실행되는 줄만 본다.
        code = "\n".join(
            line for line in _text("notify_fundamentals").splitlines()
            if not line.lstrip().startswith("#")
        )

        self.assertIn("conclusion != 'cancelled'", code)
        self.assertNotIn("conclusion == 'success'", code)

    def test_earnings_senders_share_one_concurrency_group(self):
        groups = {
            name: re.search(r"concurrency:\s*\n\s*#[^\n]*\n(?:\s*#[^\n]*\n)*\s*group:\s*(\S+)|concurrency:\s*\n\s*group:\s*(\S+)", _text(name))
            for name in _EARNINGS_SENDERS
        }
        found = {
            name: (match.group(1) or match.group(2)) for name, match in groups.items() if match
        }
        self.assertEqual(len(found), len(_EARNINGS_SENDERS))
        self.assertEqual(len(set(found.values())), 1, found)


class MacroChainTest(unittest.TestCase):
    """매크로 알림 3종. 상류가 둘(macro_etl / macro_etl_monday)이라 한쪽만 들으면 요일이 빈다."""

    _NOTIFIERS = ("notify_macro_core", "notify_macro_watch")

    def test_macro_notifies_follow_both_etl_paths(self):
        for name in self._NOTIFIERS:
            with self.subTest(workflow=name):
                text = _text(name)
                self.assertIn("macro_etl", text)
                self.assertIn("macro_etl_monday", text)

    def test_macro_notifies_are_not_gated_on_etl_success(self):
        """ECOS 키 하나가 만료돼도 ETL은 exit 1 한다 — success로 잠그면 카드가 묻힌다."""
        for name in self._NOTIFIERS:
            with self.subTest(workflow=name):
                code = "\n".join(
                    line for line in _text(name).splitlines()
                    if not line.lstrip().startswith("#")
                )
                self.assertIn("conclusion != 'cancelled'", code)
                self.assertNotIn("conclusion == 'success'", code)

    def test_every_macro_notify_has_its_own_trigger(self):
        """workflow_run이 발화하지 않아도 스스로 한 번은 돈다."""
        for name in self._NOTIFIERS:
            with self.subTest(workflow=name):
                self.assertIn("schedule:", _text(name))

    def test_macro_watch_does_not_poll_faster_than_its_data(self):
        """워치가 볼 수 있는 새 관측치는 macro ETL이 넣어주는 것뿐이다.

        `macro.observation_versions`는 macro_etl/macro_etl_monday가 하루 한 번만 갱신하고,
        `load_watch_pending()`이 `(series_id, obs_date)`로 이미 평가한 것을 걸러낸다.
        그래서 같은 날 두 번째부터는 반드시 0건이다 — 장중 매시 실행은 러너만 쓰고
        새 경보를 만들 수 없다. 상류 workflow_run + 하루 한 번 안전망이 상한이다.
        """
        crons = _crons("notify_macro_watch")
        self.assertEqual(len(crons), 1, "워치 cron은 안전망 하나뿐이어야 한다")
        minute, hour, _dom, _mon, _dow = crons[0].split()
        self.assertNotIn("-", hour, "시간 범위를 쓰면 하루 여러 번 돈다")
        self.assertNotIn("/", hour, "스텝을 쓰면 하루 여러 번 돈다")
        self.assertNotIn(",", hour, "시간 목록을 쓰면 하루 여러 번 돈다")
        # 상류(macro_etl 00:25 UTC)보다 뒤여야 그날 관측치를 보고 판정한다.
        self.assertGreater((int(hour), int(minute)), (0, 25))


class EconCalendarChainTest(unittest.TestCase):
    def test_release_notify_is_a_safety_net_not_a_second_runner(self):
        """watcher가 같은 러너에서 이미 보내므로 여기에 workflow_run을 걸지 않는다.

        걸면 watch가 도는 족족 러너가 한 번 더 떠서, 보낼 것이 없는 실행에까지 비용을
        두 번 낸다. 남는 것은 속보가 실패했을 때를 위한 cron 안전망뿐이다.
        """
        text = _text("notify_econ_calendar_release")
        self.assertNotIn("workflow_run:", text)
        self.assertIn("schedule:", text)
        self.assertIn("--notify", _text("econ_calendar_watch"))

    def test_calendar_runs_on_its_own_schedule(self):
        text = _text("econ_calendar_daily")
        self.assertIn("schedule:", text)
        self.assertNotIn("workflow_run:", text)

    def test_release_watcher_wakes_only_inside_the_release_window(self):
        """미국 지표 발표 시각대에만 깨어난다.

        24시간 `*/5`는 한 달 8,766번이고 저장소 할당은 2,000분이라, 이 워크플로 하나가
        예산을 8배 넘긴다. 시드의 미국 지표 21개가 ET 08:30~10:30에 몰려 있고 그 구간은
        서머타임 양쪽에서 UTC 12~15시 안에 든다.
        """
        text = _text("econ_calendar_watch")
        self.assertIn("investment_agent.operations.commands.econ_calendar_watch_releases", text)
        self.assertIn("--poll-attempts 4", text)

        crons = _crons("econ_calendar_watch")
        self.assertEqual(len(crons), 1)
        _minute, hour, _dom, _mon, dow = crons[0].split()
        self.assertEqual(hour, "12-15", "발표 창 밖에서 깨어나면 예산을 넘긴다")
        self.assertEqual(dow, "1-5", "지표는 평일에만 발표된다")

    def test_revision_audit_is_separate_from_daily(self):
        text = _text("econ_calendar_revision_audit")
        self.assertIn("investment_agent.data.macro.commands.econ_calendar_revision_audit", text)
        self.assertIn("ALFRED vintage", text)


class CardInstallGuardTest(unittest.TestCase):
    """PNG 카드 렌더 준비의 시간 상한을 지킨다.

    설치는 이제 `.github/actions/card-render` composite 하나에 있다. 그래서 검사도
    거기를 본다 — 워크플로 본문에서 `playwright install`을 찾던 예전 방식은 설치를
    옮긴 순간 **찾을 대상이 없어져 조용히 통과**한다.

    상한이 필요한 이유는 실측이다(2026-08-19): apt 미러가 죽어 300초 상한에 걸리자
    매크로 카드 2종이 통째로 빠졌고, `--with-deps` 한 방으로 묶은 설치는 exit 124로
    브라우저까지 못 받았다.
    """

    ACTION = _WORKFLOWS.parents[0] / "actions" / "card-render" / "action.yml"

    def _action_text(self) -> str:
        return self.ACTION.read_text(encoding="utf-8")

    def _callers(self):
        """이 composite를 실제로 부르는 워크플로. 없으면 그 자체가 실패다."""
        found = sorted(
            path for path in _WORKFLOWS.glob("*.yml")
            if "actions/card-render" in path.read_text(encoding="utf-8")
        )
        self.assertTrue(found, "card-render를 부르는 워크플로가 하나도 없다")
        return found

    def test_the_action_exists_and_installs_chromium(self):
        self.assertTrue(self.ACTION.exists(), f"{self.ACTION} 이 없다")
        self.assertIn("playwright install chromium", self._action_text())

    def test_every_apt_and_playwright_command_is_time_bounded(self):
        """상한이 **하나라도** 빠지면 실패해야 한다.

        `playwright install`은 두 번 나온다(install-deps, install chromium). 정규식
        하나가 어디든 걸리면 통과하게 두면, 한쪽 상한을 지워도 검사가 조용히 넘어간다.
        실제로 그런 검사를 쓰고 있었다.
        """
        commands = ("apt-get update", "apt-get install", "python -m playwright install")
        unbounded = []
        for line in self._action_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not any(c in stripped for c in commands):
                continue
            if not re.search(r"timeout -k \d+ \d+ (sudo )?", stripped):
                unbounded.append(stripped)
        self.assertEqual([], unbounded)

    def test_sudo_never_wraps_timeout(self):
        """`timeout ... sudo`는 신호가 자식에 닿지 않아 상한이 무력해진다."""
        self.assertNotRegex(self._action_text(), r"timeout (-k \d+ )?\d+ sudo ")

    def test_missing_cjk_font_stops_the_job(self):
        """폰트 없이 렌더하면 한글이 두부로 나가는데 예외는 안 난다. 여기서 멈춰야 한다."""
        self.assertRegex(self._action_text(), r'fc-list \| grep -qi "noto sans cjk" \|\| \{[^}]*exit 1')

    def test_install_budget_fits_inside_every_caller_job_cap(self):
        """안쪽 상한의 합이 부르는 잡의 상한을 넘으면 상한을 둔 의미가 없다.

        composite action의 스텝은 `timeout-minutes`를 못 쓴다. 그래서 이 검사가
        예전의 단계별 상한을 대신한다.
        """
        budget_sec = sum(int(n) for n in re.findall(r"timeout -k \d+ (\d+) ", self._action_text()))
        self.assertGreater(budget_sec, 0)
        for path in self._callers():
            caps = [
                int(n) for n in
                re.findall(r"timeout-minutes:\s*(\d+)", path.read_text(encoding="utf-8"))
            ]
            with self.subTest(workflow=path.name):
                self.assertTrue(caps, f"{path.name}: 잡 상한(timeout-minutes)이 없다")
                self.assertLess(budget_sec / 60, min(caps))


class SharedSetupTest(unittest.TestCase):
    """준비 단계는 composite action 하나로 모은다.

    공통 설정을 한 곳에서 검증해 모든 workflow가 같은 Python·secret 계약을 사용하게 한다.
    """

    ACTION = _WORKFLOWS.parents[0] / "actions" / "python-job" / "action.yml"

    # setup-python을 직접 쓰는 것이 허용된 워크플로와 그 이유. 목록이 곧 부채이므로
    # 짧게 유지한다 — 옮길 때마다 여기서 지운다.
    ALLOWED_INLINE = {
        # 테스트 워크플로는 dev group 하나를 쓰지만 캐시·매트릭스 계약이 달라 그대로 둔다.
        "ci.yml",
        # 관심종목 fast path만 core와 data 둘을 설치한다. action의 계약은 group 하나다.
        "fundamentals_watchlist_fast.yml",
    }

    def test_the_action_exists(self):
        self.assertTrue(self.ACTION.exists(), f"{self.ACTION} 이 없다")

    def test_the_action_syncs_the_requested_locked_group(self):
        text = self.ACTION.read_text(encoding="utf-8")
        self.assertIn("group:", text)
        self.assertIn("uv sync --locked --no-dev --group", text)
        self.assertIn("uv.lock", text)

    def test_secret_validation_reports_names_without_values(self):
        """로그는 공개될 수 있다. 없는 것의 이름만 말하고 값은 절대 찍지 않는다."""
        text = self.ACTION.read_text(encoding="utf-8")
        self.assertIn("required secrets are empty", text)
        self.assertNotIn("${!name}\"", text.replace('[ -z "${!name}" ]', ""))

    def test_workflows_do_not_reinline_the_setup_block(self):
        offenders = sorted(
            path.name for path in _WORKFLOWS.glob("*.yml")
            if "actions/setup-python" in path.read_text(encoding="utf-8")
            and path.name not in self.ALLOWED_INLINE
        )
        self.assertEqual([], offenders)

    def test_the_allow_list_has_no_stale_entries(self):
        """옮기고 나서 목록에 남겨두면 그 목록이 거짓말을 시작한다."""
        stale = sorted(
            name for name in self.ALLOWED_INLINE
            if "actions/setup-python" not in (_WORKFLOWS / name).read_text(encoding="utf-8")
        )
        self.assertEqual([], stale)

    def test_ci_installs_dev_and_discovers_from_the_project_root(self):
        """tests 패키지가 src 패키지를 가리는 300여 import 오류를 막는다."""
        text = _text("ci")

        self.assertIn("uv sync --locked --group dev", text)
        self.assertNotIn("uv sync --locked --no-dev --group dev", text)
        self.assertIn(
            "uv run python -m unittest discover -s tests -t .",
            text,
        )


class RuntimeLedgerWorkflowTest(unittest.TestCase):
    ACTION = _WORKFLOWS.parents[0] / "actions" / "runtime-ledger" / "action.yml"

    def test_runtime_ledger_action_restores_then_initializes_sqlite(self):
        text = self.ACTION.read_text(encoding="utf-8")

        self.assertIn("uses: actions/cache@v4", text)
        self.assertIn("data/local/runtime", text)
        self.assertIn("${{ inputs.scope }}", text)
        self.assertIn("${{ github.run_id }}-${{ github.run_attempt }}", text)
        self.assertIn(
            "python -m investment_agent.operations.commands.runtime_init",
            text,
        )

    def test_every_hosted_runtime_reader_prepares_the_expected_ledger(self):
        for name, scope in _RUNTIME_LEDGER_SCOPES.items():
            with self.subTest(workflow=name):
                text = _text(name)
                setup_at = text.index("uses: ./.github/actions/python-job")
                ledger_at = text.index("uses: ./.github/actions/runtime-ledger")
                self.assertGreater(ledger_at, setup_at)
                self.assertRegex(
                    text[ledger_at:],
                    rf"with:\s*\n\s*scope:\s*{re.escape(scope)}(?:\s|$)",
                )

    def test_shared_producers_share_concurrency_groups(self):
        for names in (
            ("notify_macro_core", "notify_macro_watch"),
            ("notify_fundamentals", "notify_fundamentals_calendar"),
            ("notify_econ_calendar_release", "econ_calendar_watch"),
        ):
            groups = {
                re.search(r"(?m)^\s*group:\s*([^\s]+)", _text(name)).group(1)
                for name in names
            }
            with self.subTest(workflows=names):
                self.assertEqual(1, len(groups))

    def test_earnings_watcher_leaves_discord_to_followup_notifier(self):
        text = _text("fundamentals_earnings_watch")

        self.assertNotIn("--notify", text)
        self.assertIn(
            'workflows: ["fundamentals_daily", "fundamentals_watchlist_fast", "fundamentals_earnings_watch"]',
            _text("notify_fundamentals"),
        )

    def test_investment_notifier_is_manual_only_because_its_source_is_local(self):
        self.assertEqual([], _crons("notify_investment"))
        self.assertIn("workflow_dispatch:", _text("notify_investment"))


class KillSwitchTest(unittest.TestCase):
    """킬 스위치는 워크플로 레벨 게이트다 — Python 코드 안에서 검사하지 않는다."""

    def test_fundamentals_workflows_gate_on_the_repo_variable(self):
        for name in (
            "fundamentals_daily",
            "fundamentals_backfill",
            "fundamentals_watchlist_fast",
            "notify_fundamentals",
            "notify_fundamentals_calendar",
        ):
            with self.subTest(workflow=name):
                self.assertIn("vars.FUNDAMENTALS_KILL != 'on'", _text(name))

    def test_kill_switch_is_never_read_from_python(self):
        src = Path(__file__).resolve().parents[1] / "src"
        offenders = [
            path.relative_to(src).as_posix()
            for path in src.rglob("*.py")
            if "FUNDAMENTALS_KILL" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])


class ExpectationsWorkflowTest(unittest.TestCase):
    def test_tracked_universe_is_default_and_collection_is_time_bounded(self):
        text = _text("fundamentals_expectations")

        self.assertIn("default: all", text)
        self.assertIn("inputs.scope || 'all'", text)
        self.assertIn("--collection-budget-sec 1500", text)
        self.assertIn("--workers 4", text)
        self.assertIn("timeout -k 30 1800", text)


class FailureAlertTest(unittest.TestCase):
    """실패 알림은 timeout 취소(cancelled) 상태도 포착해야 한다.

    GitHub Actions는 timeout 초과 시 결론을 'cancelled'로 처리하므로,
    'failure() || cancelled()' 조건을 사용하여 장애 알림 누락을 방지한다.
    """

    def test_every_alert_also_fires_on_cancellation(self):
        for path in sorted(_WORKFLOWS.glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            if "failure()" not in text:
                continue
            with self.subTest(workflow=path.name):
                self.assertNotRegex(text, r"if:\s*(\$\{\{\s*)?failure\(\)\s*\}?\}?\s*$")
                self.assertIn("failure() || cancelled()", text)

    def test_ci_has_no_concurrency_group_that_cancels_pending_tests(self):
        """CI는 읽기 전용이므로 새 push가 대기 검증을 취소할 이유가 없다."""
        self.assertNotIn("concurrency:", _text("ci"))

    def test_every_workflow_can_alert_at_all(self):
        """source workflow가 공통 리포터를 건너뛰면 조용한 장애가 생긴다."""
        for path in sorted(_WORKFLOWS.glob("*.yml")):
            if path.stem == "ops_failure_report":
                continue
            with self.subTest(workflow=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn("failure() || cancelled()", text)
                self.assertIn("uses: ./.github/workflows/ops_failure_report.yml", text)
                self.assertIn("source_conclusion:", text)
                self.assertIn("discord_webhook_ops:", text)
                self.assertNotIn("curl -", text)
                self.assertNotRegex(text, r"discord(?:app)?\.com/api/webhooks")

    def test_reusable_reporter_fetches_actions_context_and_keeps_raw_logs_out_of_discord(self):
        text = _text("ops_failure_report")

        self.assertIn("actions: read", text)
        self.assertIn("GITHUB_TOKEN: ${{ github.token }}", text)
        # 인라인이든 composite action이든 "가벼운 core만 깐다"가 이 검사의 뜻이다.
        self.assertEqual(["core"], _workflow_groups("ops_failure_report"))
        self.assertIn("investment_agent.operations.commands.workflow_failure", text)


    def test_fast_path_runs_company_before_notifying(self):
        text = _text("fundamentals_watchlist_fast")

        self.assertIn(
            "investment_agent.data.fundamentals.commands.sync_filings --content company --watchlist-only",
            text,
        )

    def test_preflight_runs_before_the_heavy_install(self):
        """비싼 설치 앞에 게이트가 있어야 한다 — preflight를 없애면 안 된다."""
        text = _text("fundamentals_watchlist_fast")
        gate = text.index("investment_agent.data.fundamentals.commands.check_earnings_season")
        heavy = text.index("uv sync --locked --no-dev --group data", text.index("Install collection"))

        self.assertLess(gate, heavy)

    def test_calendar_installs_card_renderer_only_when_sending(self):
        """보낼 카드가 없는 날 Chromium과 61MB 폰트를 받으면 그 시간은 그냥 사라진다.

        설치가 composite로 옮겨갔으므로 게이트도 그 호출에 붙어 있어야 한다 —
        설치 명령 문자열만 찾으면 실제 단계의 구성을 검증하지 못하고
        조용히 통과한다.
        """
        text = _text("notify_fundamentals_calendar")
        call = text.index("- uses: ./.github/actions/card-render")
        step = text[call:call + 200]

        self.assertIn("steps.pending.outputs.should_notify == 'true'", step)

    def test_every_workflow_is_manually_dispatchable(self):
        for name in ("fundamentals_watchlist_fast", "notify_fundamentals",
                     "notify_fundamentals_calendar"):
            with self.subTest(workflow=name):
                self.assertIn("workflow_dispatch:", _text(name))

    def test_company_sync_installs_earnings_event_dependencies(self):
        """company 동기화는 8-K 보도자료와 Yahoo 발표 실적도 함께 처리한다."""
        dependencies = _group_requirements("data").lower()
        self.assertIn("beautifulsoup4", dependencies)
        self.assertIn("yfinance", dependencies)

    def test_every_workflow_installs_what_its_entry_point_imports(self):
        """진입점이 import하는 서드파티가 그 워크플로 dependency group에 다 있어야 한다.

        파이프라인별 dependency group에서 빠진 핀은 CI에서만 드러난다 —
        단위 테스트는 로컬 전체 설치 위에서 돌기 때문에 초록이다. 실제로
        fundamentals_backfill이 secfsdstools 없이 배포돼 ModuleNotFoundError로
        죽었다. 그 부류를 여기서 잡는다.

        판정은 일부러 넉넉하다: 어떤 인자로 부르든 진입점에서 닿을 수 있는 모듈을
        전부 센다. 그래서 특정 실행이 실제로 쓰지 않는 패키지까지 요구할 수 있다
        (`fundamentals_dimensions`의 yfinance가 그 경우다). 안 쓰는 걸 하나 더
        설치하는 비용보다 워크플로가 import 단계에서 조용히 죽는 비용이 크다.
        """
        for name in sorted(_workflow_names()):
            groups = _workflow_groups(name)
            modules = _entry_modules(name)
            if not groups or not modules:
                continue  # 파이썬을 안 돌리거나 설치를 안 하는 워크플로
            installed = "\n".join(_group_requirements(group) for group in groups).lower()
            for module in modules:
                needed = _third_party_imports(module)
                for package in sorted(needed):
                    distribution = _DISTRIBUTION_NAMES.get(package, package)
                    with self.subTest(workflow=name, module=module, package=package):
                        self.assertIn(
                            distribution.lower(),
                            installed,
                            f"{name}: {module}이 {package}를 import하는데 "
                            f"{groups}에 {distribution}이 없다",
                        )


if __name__ == "__main__":
    unittest.main()


def _run_commands(text: str) -> list[str]:
    r"""`run:` 블록의 줄바꿈(`\`, `>-`)을 이어 붙인 실행 명령들."""
    commands: list[str] = []
    pending = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            continue
        if pending:
            pending = pending[:-1].rstrip() + " " + line
            if not pending.endswith("\\"):
                commands.append(pending)
                pending = ""
            continue
        if "python -m investment_agent" not in line:
            continue
        if line.endswith("\\"):
            pending = line
        else:
            commands.append(line)
    if pending:
        commands.append(pending)
    return commands


def _invocations(name: str) -> list[tuple[str, frozenset[str]]]:
    r"""이 워크플로가 실제로 실행하는 (진입점, 넘기는 옵션) 쌍.

    `>-` 접기와 `\` 이음, `${{ }}` 표현식을 지운 뒤 남는 리터럴 옵션에,
    셸 변수로 조립해 넘기는 옵션을 더한다. 조립은 두 형태를 다 쓰고 있어
    (`ARGS=(--x)` / `ARGS+=(--y)` 배열, `ARGS="$ARGS --z"` 문자열) 둘 다 읽는다 —
    한쪽만 읽으면 `market_backfill`처럼 문자열로 넘기는 워크플로가 통째로 빠진다.
    """
    text = _text(name)
    assembled: dict[str, set[str]] = {}
    for line in text.splitlines():
        for variable in re.findall(r"""(?:^|\s|;)([A-Za-z_]+)\+?=[("']""", line):
            assembled.setdefault(variable, set()).update(
                re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]*)", line)
            )
    found = []
    for command in _run_commands(text):
        at = command.index("python -m investment_agent")
        cleaned = re.sub(r"\$\{\{[^}]*\}\}", "X", command[at:])
        expanded = set(re.findall(r"\$\{?([A-Za-z_]+)(?:\[@\])?\}?", cleaned))
        cleaned = re.sub(r'"?\$\{?[A-Za-z_]+(\[@\])?\}?"?', "", cleaned)
        parts = cleaned.split()
        flags = {p for p in parts[3:] if p.startswith("--")}
        for variable in expanded:
            flags |= assembled.get(variable, set())
        found.append((parts[2], frozenset(flags)))
    return found


def _direct_module_imports(module: str) -> set[str]:
    """진입점이 **모듈 레벨에서** 직접 가져오는 investment_agent 모듈들."""
    path = _module_path(module)
    if path is None:
        return set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in tree.body:
        for name in _imported_names(node):
            if name.startswith("investment_agent."):
                found.add(name)
    return found


def _declared_flags(module: str) -> set[str]:
    """진입점이 받아들이는 옵션.

    `add_argument`는 진입점 자신뿐 아니라 그것이 직접 import한 헬퍼에도 있다
    (`operations.backfill.add_backfill_from_arg`). 거기까지만 본다 — 더 멀리
    따라가면 다른 CLI의 옵션까지 긁어와 검사가 헐거워진다.
    """
    flags: set[str] = set()
    for candidate in {module} | _direct_module_imports(module):
        path = _module_path(candidate)
        if path is None:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            attribute = getattr(node.func, "attr", None)
            if attribute != "add_argument":
                continue
            for argument in node.args:
                if isinstance(argument, ast.Constant) and str(argument.value).startswith("--"):
                    flags.add(str(argument.value))
    return flags


class EntryPointOptionTest(unittest.TestCase):
    """워크플로가 넘기는 옵션을 진입점이 실제로 받는지 본다.

    안 받으면 argparse가 exit 2로 죽는데, 그 워크플로가 수동 dispatch 전용이면
    아무도 부르지 않는 동안 CI는 계속 초록이다. 실제로 둘이 그 상태였다:
    `market_backfill`은 옮겨간 발행주식수 시절의 `--dataset`을 계속 넘기고 있었고,
    `strategy_monthly`의 `--mark-sent`는 구현·문서·워크플로 입력이 다 있는데
    `add_argument`만 없었다.
    """

    def test_every_workflow_option_is_declared_by_its_entry_point(self):
        checked = 0
        for name in sorted(_workflow_names()):
            for module, flags in _invocations(name):
                declared = _declared_flags(module)
                for flag in sorted(flags):
                    checked += 1
                    with self.subTest(workflow=name, module=module, option=flag):
                        self.assertIn(flag, declared)
        # 추출이 조용히 0건이 되면 이 검사는 아무것도 지키지 않는다.
        self.assertGreater(checked, 20, "워크플로 명령 추출이 비었다 — 검사가 공허하다")

    def test_every_entry_point_module_exists(self):
        missing = sorted({
            f"{name}:{module}"
            for name in _workflow_names()
            for module, _flags in _invocations(name)
            if _module_path(module) is None
        })
        self.assertEqual([], missing)


class RunnerImageTest(unittest.TestCase):
    """러너 라벨은 `ubuntu-latest` 하나로 둔다.

    버전을 박으면 그 이미지가 만료된다. ubuntu-22.04가 그랬다 — 2026-09-17부터
    deprecation에 들어가고 브라운아웃 기간에는 잡을 실패시킨다
    (actions/runner-images#14254). 걸려 있던 13개가 알림 카드 발송 쪽이라,
    조용히 빠지면 가장 티가 안 나는 자리였다.

    핀이 필요하면 이유와 함께 PINNED에 적는다. 목록이 곧 부채이므로 비워 둔다.
    """

    #: 워크플로 파일명 -> 그 라벨을 박아야 하는 이유.
    PINNED: dict[str, str] = {}

    def test_every_job_runs_on_the_floating_label(self):
        found = 0
        for path in sorted(_WORKFLOWS.glob("*.yml")):
            labels = re.findall(r"^\s*runs-on:\s*(\S+)", path.read_text(encoding="utf-8"), re.M)
            found += len(labels)
            for label in labels:
                with self.subTest(workflow=path.name, image=label):
                    self.assertEqual(self.PINNED.get(path.name, "ubuntu-latest"), label)
        self.assertGreater(found, 30, "runs-on을 거의 못 찾았다 — 검사가 공허하다")

    def test_the_pin_list_has_no_stale_entries(self):
        """옮기고 나서 목록에 남겨두면 그 목록이 거짓말을 시작한다."""
        stale = sorted(name for name in self.PINNED if not (_WORKFLOWS / name).exists())
        self.assertEqual([], stale)
