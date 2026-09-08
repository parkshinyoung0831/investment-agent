# -*- coding: utf-8 -*-
"""인베스트먼트 에이전트 로컬 실행기.

운영 하네스와 읽기 전용 대시보드를 같은 메뉴에서 시작하되, 실행 목적과
필수 조건을 섞지 않는다. 안전 스위치는 읽어서 표시만 하고 절대 변경하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


# Windows 콘솔은 cp949 등 non-UTF-8 코드페이지가 기본이라, 이 파일의 한국어 문구에
# 흔한 em dash(—) 같은 문자를 그대로 print()하면 UnicodeEncodeError로 죽는다.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
VENV_STREAMLIT = ROOT / ".venv" / "Scripts" / "streamlit.exe"
DASHBOARD_APP = ROOT / "src" / "investment_agent" / "dashboard" / "app.py"
HARNESS_ENTRY = (
    ROOT
    / "src"
    / "investment_agent"
    / "operations"
    / "commands"
    / "investment_harness.py"
)
HARNESS_STATE_PATH = ROOT / "artifacts" / "ops" / "investment_harness" / "state.json"

DASHBOARD_PORT_START = 8501
DASHBOARD_PORT_END = 8510

_ON = {"1", "on", "true", "yes"}
_OFF = {"0", "off", "false", "no"}

# 서드파티만 세면 정작 이 저장소 자신이 빠진다. `.venv`에 의존성 200여 개가 다
# 있는데 프로젝트만 설치되지 않은 상태가 실제로 있었고, 그때 사전 점검은 "이상
# 없음"이라고 말한 뒤 앱이 import에서 죽었다.
DASHBOARD_IMPORTS = (
    "investment_agent", "streamlit", "plotly", "yfinance", "supabase", "dotenv",
)
HARNESS_IMPORTS = ("investment_agent", "supabase", "requests", "dotenv")

#: 모듈이 없을 때 알려줄 복구 명령. 프로젝트 자신과 서드파티의 고치는 법이 다르다.
REPAIR_HINTS = {
    "investment_agent": r"uv sync --group dev  (또는 .venv\Scripts\python.exe -m pip install -e . --no-deps)",
}
HARNESS_REQUIRED_ENV = (
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "AI_INVESTOR_BASE_URL",
    "AI_INVESTOR_MODEL",
    "AI_INVESTOR_TRADINGAGENTS_PROVIDER",
    "TOSS_CLIENT_ID",
    "TOSS_CLIENT_SECRET",
    "TOSS_ACCOUNT_SEQ",
    "DISCORD_APPROVAL_BOT_TOKEN",
    "DISCORD_GUILD_ID",
    "DISCORD_CHANNEL_AI_APPROVALS",
    "DISCORD_APPROVER_USER_IDS",
)
SHADOW_REQUIRED_ENV = (
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "AI_INVESTOR_BASE_URL",
    "AI_INVESTOR_MODEL",
    "AI_INVESTOR_TRADINGAGENTS_PROVIDER",
)

LaunchMode = Literal["dashboard", "harness", "shadow"]
HarnessMode = Literal["analysis_only", "approval_workflow"]


@dataclass(frozen=True)
class RuntimeProbe:
    """`.venv` Python과 필수 import의 읽기 전용 점검 결과."""

    version: tuple[int, int, int] | None
    missing_imports: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class PreflightReport:
    """실행 가능 여부와 사용자에게 보여줄 경고를 분리한다."""

    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def configure_console() -> None:
    """Windows 콘솔과 Python 표준 스트림을 UTF-8로 맞춘다."""
    if sys.platform != "win32":
        return
    try:
        os.system("chcp 65001 > nul")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def load_effective_environment(
    root: Path = ROOT,
    environ: Mapping[str, str] | None = None,
) -> tuple[dict[str, str], str | None]:
    """파일을 바꾸지 않고 `.env`와 현재 환경의 유효값을 합친다."""
    values: dict[str, str] = {}
    env_file = root / ".env"
    parse_error: str | None = None
    if env_file.is_file():
        try:
            from dotenv import dotenv_values

            parsed = dotenv_values(env_file)
            values.update({
                str(key): str(value)
                for key, value in parsed.items()
                if value is not None
            })
        except Exception as exc:  # noqa: BLE001 - preflight에서 오류를 사용자에게 전달한다.
            parse_error = f"{type(exc).__name__}: {exc}"

    source = os.environ if environ is None else environ
    values.update({str(key): str(value) for key, value in source.items()})
    return values, parse_error


def probe_venv_runtime(
    python_path: Path,
    modules: Sequence[str],
) -> RuntimeProbe:
    """`.venv` 프로세스에서 버전과 import 가용성만 확인한다."""
    if not python_path.is_file():
        return RuntimeProbe(None, error=f"가상환경 Python이 없습니다: {python_path}")

    code = (
        "import importlib.util,json,sys;"
        f"mods={tuple(modules)!r};"
        "missing=[m for m in mods if importlib.util.find_spec(m) is None];"
        "print(json.dumps({'version':list(sys.version_info[:3]),'missing':missing}))"
    )
    child_env = dict(os.environ)
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        result = subprocess.run(
            [str(python_path), "-c", code],
            cwd=ROOT,
            env=child_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return RuntimeProbe(None, error=f"{type(exc).__name__}: {exc}")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "알 수 없는 오류").strip()
        return RuntimeProbe(None, error=detail[-500:])
    try:
        payload = json.loads(result.stdout)
        version = tuple(int(item) for item in payload["version"])
        if len(version) != 3:
            raise ValueError("Python version length")
        missing = tuple(str(item) for item in payload.get("missing", ()))
        return RuntimeProbe(version, missing)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return RuntimeProbe(None, error=f"런타임 점검 응답 해석 실패: {exc}")


def build_preflight_report(
    mode: LaunchMode,
    *,
    root: Path,
    effective_env: Mapping[str, str],
    runtime: RuntimeProbe,
    env_parse_error: str | None = None,
) -> PreflightReport:
    """외부 호출 없이 파일·환경·런타임 점검 결과를 조립한다."""
    errors: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    venv_python = root / ".venv" / "Scripts" / "python.exe"
    venv_streamlit = root / ".venv" / "Scripts" / "streamlit.exe"
    dashboard_app = root / "src" / "investment_agent" / "dashboard" / "app.py"
    harness_entry = (
        root
        / "src"
        / "investment_agent"
        / "operations"
        / "commands"
        / "investment_harness.py"
    )
    state_path = root / "artifacts" / "ops" / "investment_harness" / "state.json"
    env_file = root / ".env"

    if not venv_python.is_file():
        errors.append(f".venv Python 실행 파일이 없습니다: {venv_python}")
    if runtime.error:
        errors.append(f".venv Python 점검 실패: {runtime.error}")
    elif runtime.version is not None and runtime.version < (3, 11, 0):
        shown = ".".join(str(item) for item in runtime.version)
        errors.append(f"Python 3.11 이상이 필요합니다. 현재 .venv: {shown}")
    if runtime.missing_imports:
        errors.append("필수 Python 모듈 누락: " + ", ".join(runtime.missing_imports))
        for name in runtime.missing_imports:
            hint = REPAIR_HINTS.get(name)
            if hint:
                errors.append(f"  → {name} 복구: {hint}")

    if env_parse_error:
        message = f".env 해석 실패: {env_parse_error}"
        (errors if mode == "harness" else warnings).append(message)

    if mode == "dashboard":
        if not dashboard_app.is_file():
            errors.append(f"대시보드 앱이 없습니다: {dashboard_app}")
        if not env_file.is_file():
            warnings.append(".env가 없습니다. 대시보드는 시작하지만 연결 데이터는 비어 있을 수 있습니다.")
        missing_supabase = [
            name for name in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY")
            if not str(effective_env.get(name, "")).strip()
        ]
        if missing_supabase:
            warnings.append(
                "Supabase 설정 누락: " + ", ".join(missing_supabase)
                + ". 앱은 시작하며 연결 실패 상태를 표시해야 합니다."
            )
    elif mode == "shadow":
        if not harness_entry.is_file():
            errors.append(f"하네스 진입점이 없습니다: {harness_entry}")
        if not env_file.is_file():
            warnings.append(
                ".env가 없습니다. 하네스는 프로세스 환경에 핵심 설정이 모두 있을 때만 시작합니다."
            )
        missing = [
            name for name in SHADOW_REQUIRED_ENV
            if not str(effective_env.get(name, "")).strip()
        ]
        if missing:
            errors.append("모의투자(Shadow) 핵심 환경변수 누락: " + ", ".join(missing))
    else:
        if not harness_entry.is_file():
            errors.append(f"하네스 진입점이 없습니다: {harness_entry}")
        if not env_file.is_file():
            warnings.append(
                ".env가 없습니다. 하네스는 프로세스 환경에 핵심 설정이 모두 있을 때만 시작합니다."
            )
        missing = [
            name for name in HARNESS_REQUIRED_ENV
            if not str(effective_env.get(name, "")).strip()
        ]
        if (
            "DISCORD_APPROVER_USER_IDS" in missing
            and str(effective_env.get("DISCORD_APPROVER_USER_ID", "")).strip()
        ):
            missing.remove("DISCORD_APPROVER_USER_IDS")
        if missing:
            errors.append("하네스 핵심 환경변수 누락: " + ", ".join(missing))

    if state_path.is_file():
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("최상위 값이 객체가 아닙니다")
            notes.append(f"하네스 상태 파일 확인: {state_path}")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            message = f"하네스 상태 파일을 읽을 수 없습니다: {type(exc).__name__}: {exc}"
            (errors if mode == "harness" else warnings).append(message)
    else:
        notes.append(f"하네스 상태 파일은 첫 실행 후 생성됩니다: {state_path}")

    return PreflightReport(tuple(errors), tuple(warnings), tuple(notes))


def run_preflight(mode: LaunchMode) -> tuple[PreflightReport, dict[str, str]]:
    effective_env, env_parse_error = load_effective_environment(ROOT)
    modules = DASHBOARD_IMPORTS if mode == "dashboard" else HARNESS_IMPORTS
    runtime = probe_venv_runtime(VENV_PYTHON, modules)
    report = build_preflight_report(
        mode,
        root=ROOT,
        effective_env=effective_env,
        runtime=runtime,
        env_parse_error=env_parse_error,
    )
    return report, effective_env


def print_preflight(report: PreflightReport) -> None:
    for note in report.notes:
        print(f"  [확인] {note}")
    for warning in report.warnings:
        print(f"  [경고] {warning}")
    for error in report.errors:
        print(f"  [오류] {error}")


def is_port_available(port: int, *, host: str = "127.0.0.1") -> bool:
    """로컬 바인드만 시도해 포트 가용성을 확인한다."""
    if not 1 <= port <= 65535:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def find_available_port(
    start: int = DASHBOARD_PORT_START,
    end: int = DASHBOARD_PORT_END,
    *,
    available: Callable[[int], bool] = is_port_available,
) -> int | None:
    """작은 고정 범위 안에서만 대시보드 포트를 선택한다."""
    if not 1 <= start <= end <= 65535:
        raise ValueError("포트 범위가 올바르지 않습니다")
    return next((port for port in range(start, end + 1) if available(port)), None)


def _safety_state(environ: Mapping[str, str]) -> tuple[str, str]:
    raw_kill = environ.get("TRADING_KILL_SWITCH")
    normalized_kill = "" if raw_kill is None else str(raw_kill).strip().lower()
    if not normalized_kill:
        kill_on = True
    elif normalized_kill in _ON:
        kill_on = True
    elif normalized_kill in _OFF:
        kill_on = False
    else:
        kill_on = True
    live_enabled = str(environ.get("TOSS_LIVE_ENABLED", "false")).strip().lower() == "true"
    kill_text = "ON — 신규 live 흐름 차단" if kill_on else "OFF — 안전 게이트 통과 시에만 진행"
    live_text = "true — 운영 활성화 요청값" if live_enabled else "false — 실주문 비활성"
    return kill_text, live_text


def harness_switch_command(mode: HarnessMode) -> list[str]:
    """하네스 기동을 중복 실행 가드가 있는 단일 진입점으로 보낸다."""

    return [
        str(VENV_PYTHON),
        "-m",
        "investment_agent.operations.commands.harness_switch",
        "--on",
        "--mode",
        mode,
    ]


def run_shadow_harness() -> int:
    clear_screen()
    print("=" * 70)
    print("  [AI 모의투자 하네스] Shadow 분석 & 가상 포트폴리오 관제를 시작합니다")
    print("=" * 70)
    print("  * 실주문 없음 / 계좌 손익 불변 / 순수 AI 분석 및 추천 포트폴리오 생성")
    print("  * 정해진 스케줄에 맞춰 시장 데이터를 분석하고 가상 투자 결정을 DB에 기록합니다.")
    print()

    report, effective_env = run_preflight("shadow")
    print_preflight(report)
    quick = effective_env.get('AI_INVESTOR_QUICK_MODEL', effective_env.get('AI_INVESTOR_MODEL', 'N/A'))
    deep = effective_env.get('AI_INVESTOR_DEEP_MODEL', effective_env.get('AI_INVESTOR_MODEL', 'N/A'))
    print(f"  * AI 듀얼 모델       : Quick={quick} / Deep={deep} ({effective_env.get('AI_INVESTOR_PROVIDER', 'N/A')})")
    print(f"  * 일일 분석 한도     : {effective_env.get('AI_INVESTOR_DAILY_LIMIT', '250')} 종목")
    if not report.ok:
        print("\n  하네스를 시작하지 않았습니다. 위 필수 조건을 먼저 수정하세요.")
        return 1

    command = harness_switch_command("analysis_only")
    print(f"\n  * 상태 경로: {HARNESS_STATE_PATH}")
    print("  * 중복 실행 가드를 확인한 뒤 백그라운드에서 시작합니다.")
    try:
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode:
            print(f"\n[오류] 하네스를 시작하지 못했습니다. 종료 코드: {result.returncode}")
        else:
            print("\n[완료] Shadow 하네스 시작 요청을 처리했습니다.")
        return int(result.returncode)
    except KeyboardInterrupt:
        print("\n\n[알림] 하네스가 사용자 요청으로 중단되었습니다.")
        return 130
    except OSError as exc:
        print(f"\n[오류] 하네스를 시작할 수 없습니다: {exc}")
        return 1


def run_harness() -> int:
    clear_screen()
    print("=" * 70)
    print("  [실계좌 운영 하네스] Discord 승인 워크플로를 시작합니다")
    print("=" * 70)
    print("  이 경로는 DB 기록·Discord 승인 요청·Toss 실행 경계를 포함합니다.")
    print("  기존 kill switch, 결정론적 risk gate, HMAC 승인을 그대로 적용합니다.")
    print()

    report, effective_env = run_preflight("harness")
    print_preflight(report)
    kill_text, live_text = _safety_state(effective_env)
    print(f"  * TRADING_KILL_SWITCH : {kill_text}")
    print(f"  * TOSS_LIVE_ENABLED   : {live_text}")
    if not report.ok:
        print("\n  하네스를 시작하지 않았습니다. 위 필수 조건을 먼저 수정하세요.")
        return 1

    command = harness_switch_command("approval_workflow")
    print(f"\n  * 상태 경로: {HARNESS_STATE_PATH}")
    print("  * 중복 실행 가드를 확인한 뒤 백그라운드에서 시작합니다.")
    try:
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode:
            print(f"\n[오류] 하네스를 시작하지 못했습니다. 종료 코드: {result.returncode}")
        else:
            print("\n[완료] 실계좌 승인 하네스 시작 요청을 처리했습니다.")
        return int(result.returncode)
    except KeyboardInterrupt:
        print("\n\n[알림] 하네스가 사용자 요청으로 중단되었습니다.")
        return 130
    except OSError as exc:
        print(f"\n[오류] 하네스를 시작할 수 없습니다: {exc}")
        return 1


def run_dashboard() -> int:
    clear_screen()
    print("=" * 70)
    print("  [읽기 전용 대시보드] ATLAS 투자 관제 화면을 시작합니다")
    print("=" * 70)
    print("  이 실행기는 주문·승인 요청·Discord 발송을 수행하지 않습니다.")
    print("  데이터 조회 실패 시 앱은 종료하지 않고 연결 상태를 표시합니다.")
    print()

    report, _effective_env = run_preflight("dashboard")
    print_preflight(report)
    if not report.ok:
        print("\n  대시보드를 시작하지 않았습니다. 위 필수 조건을 먼저 수정하세요.")
        print("  설치 명령: python -m pip install uv==0.12.10 && uv sync --group dashboard")
        return 1

    search_start = DASHBOARD_PORT_START
    while search_start <= DASHBOARD_PORT_END:
        port = find_available_port(search_start, DASHBOARD_PORT_END)
        if port is None:
            print(
                f"\n[오류] localhost:{DASHBOARD_PORT_START}-{DASHBOARD_PORT_END}가 모두 사용 중입니다."
            )
            print("사용 중인 Streamlit을 종료하거나 해당 포트를 비운 뒤 다시 실행하세요.")
            return 1
        if port != DASHBOARD_PORT_START:
            print(
                f"  [안내] 앞선 포트가 사용 중이어서 {port} 포트를 선택했습니다."
            )

        url = f"http://localhost:{port}"
        command = [
            str(VENV_PYTHON),
            "-m",
            "streamlit",
            "run",
            str(DASHBOARD_APP),
            "--server.address=127.0.0.1",
            f"--server.port={port}",
        ]
        print(f"  * 로컬 주소: {url}")
        print("  * 종료: Ctrl+C")
        try:
            result = subprocess.run(command, cwd=ROOT, check=False)
        except KeyboardInterrupt:
            print("\n\n[알림] 대시보드가 종료되었습니다.")
            return 130
        except OSError as exc:
            print(f"\n[오류] 대시보드를 시작할 수 없습니다: {exc}")
            return 1

        if result.returncode and not is_port_available(port):
            print(
                f"  [안내] 시작 직전에 {port} 포트가 선점되었습니다. 다음 포트로 재시도합니다."
            )
            search_start = port + 1
            continue
        if result.returncode:
            print(f"\n[오류] Streamlit이 종료 코드 {result.returncode}로 끝났습니다.")
            print("위 traceback과 .env/의존성/Supabase 경고를 확인하세요.")
        return int(result.returncode)

    return 1


def run_test_notify() -> int:
    clear_screen()
    print("=" * 70)
    print("  [Discord 외부 발송] 매크로 시황 카드 테스트")
    print("=" * 70)
    print("  이 작업은 실제 Discord 메시지를 발송합니다.")
    confirmation = input("  발송하려면 SEND를 입력하세요: ").strip()
    if confirmation != "SEND":
        print("\n[취소] Discord 메시지를 발송하지 않았습니다.")
        input("\n계속하려면 Enter 키를 누르세요...")
        return 0
    result = subprocess.run(
        [
            str(VENV_PYTHON),
            "-m",
            "investment_agent.operations.commands.notify",
            "--kind",
            "macro_core",
            "--force",
        ],
        cwd=ROOT,
        check=False,
    )
    if result.returncode == 0:
        print("\n[전송 완료] Discord #오늘의-시장 채널을 확인하세요.")
    else:
        print(f"\n[전송 실패] 종료 코드 {result.returncode}; Discord 설정과 traceback을 확인하세요.")
    input("\n계속하려면 Enter 키를 누르세요...")
    return int(result.returncode)


def run_ai_dry_run() -> int:
    """AAPL 데이터 번들을 저장 없이 한 번 검사한다."""

    clear_screen()
    print("[점검] AAPL 데이터 번들을 저장 없이 검사합니다.\n")
    result = subprocess.run(
        [
            str(VENV_PYTHON),
            "-m",
            "investment_agent.trading.decision.portfolio_shadow",
            "--ticker",
            "AAPL",
            "--dry-run",
        ],
        cwd=ROOT,
        check=False,
    )
    input("\n계속하려면 Enter 키를 누르세요...")
    return int(result.returncode)


def run_offline_tests() -> int:
    """저장소 표준 오프라인 단위 테스트를 실행한다."""

    clear_screen()
    print("[테스트] 전체 오프라인 단위 테스트를 실행합니다.\n")
    result = subprocess.run(
        [str(VENV_PYTHON), "-m", "unittest", "discover", "-s", "tests"],
        cwd=ROOT,
        check=False,
    )
    input("\n계속하려면 Enter 키를 누르세요...")
    return int(result.returncode)


def developer_tools_menu() -> None:
    """외부 발송을 포함한 점검 작업을 운영 제어와 분리한다."""

    while True:
        clear_screen()
        print("=" * 70)
        print("   점검·개발 도구")
        print("=" * 70)
        print()
        print("   [1] AI 1회 분석 점검 — AAPL dry-run / 저장 없음")
        print("   [2] 전체 오프라인 단위 테스트")
        print("   [3] Discord 알림 카드 테스트 — 실제 발송")
        print("   [0] 이전 메뉴")
        print()
        choice = input("실행할 번호 [1/2/3/0]: ").strip()

        if choice == "1":
            run_ai_dry_run()
        elif choice == "2":
            run_offline_tests()
        elif choice == "3":
            run_test_notify()
        elif choice == "0":
            return


def interactive_menu() -> int:
    while True:
        clear_screen()
        print("=" * 70)
        print("   인베스트먼트 에이전트 로컬 제어판")
        print("=" * 70)
        print()
        print("   [1] ATLAS 운영 제어센터 (권장)")
        print("       상태 · 모드 선택 · 시작 · 안전 정지 · 대시보드 시작/열기")
        print("   [2] 점검·개발 도구")
        print("       AAPL dry-run · 오프라인 테스트 · Discord 실제 테스트 발송")
        print("   [0] 종료")
        print()
        choice = input("실행할 번호 [1/2/0]: ").strip()

        if choice == "1":
            clear_screen()
            from investment_agent.operations.control_center import run_control_center

            result = run_control_center()
            if result:
                input("\n계속하려면 Enter 키를 누르세요...")
        elif choice == "2":
            developer_tools_menu()
        elif choice == "0":
            print("\n프로그램을 종료합니다.")
            return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="인베스트먼트 에이전트 로컬 실행기")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--dashboard", action="store_true", help="읽기 전용 Streamlit 대시보드 시작")
    action.add_argument("--harness", action="store_true", help="운영 approval_workflow 하네스 시작")
    action.add_argument("--shadow", action="store_true", help="AI 모의투자(Shadow) analysis_only 하네스 시작")
    action.add_argument("--switch", action="store_true", help="하네스 ON/OFF 스위치 제어판 시작")
    action.add_argument("--control-center", action="store_true", help="ATLAS 로컬 GUI 제어센터 시작")
    action.add_argument("--stop", "--off", action="store_true", help="실행 중인 하네스 프로세스 완전 정지")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    configure_console()
    args = parse_args(argv)
    if args.dashboard:
        return run_dashboard()
    if args.harness:
        return run_harness()
    if args.shadow:
        return run_shadow_harness()
    if args.switch:
        return subprocess.run(
            [str(VENV_PYTHON), "-m", "investment_agent.operations.commands.harness_switch", "--interactive"],
            cwd=ROOT,
            check=False,
        ).returncode
    if args.control_center:
        from investment_agent.operations.control_center import run_control_center

        return run_control_center()
    if args.stop:
        return subprocess.run(
            [str(VENV_PYTHON), "-m", "investment_agent.operations.commands.harness_switch", "--off"],
            cwd=ROOT,
            check=False,
        ).returncode
    return interactive_menu()


if __name__ == "__main__":
    raise SystemExit(main())
