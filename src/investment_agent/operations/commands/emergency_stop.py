"""투자 하네스 비상 긴급 정지(Emergency Stop) 및 재활성화(Re-arm) CLI 도구.

사용 예시:
    # 1. 상태 및 Durable Lockdown 조회
    python -m investment_agent.operations.commands.emergency_stop --status

    # 2. 즉시 비상 정지 (원자적 Durable Lockdown + 프로세스 kill + 잡 일시중지)
    python -m investment_agent.operations.commands.emergency_stop --kill

    # 3. 비상 정지 + .env 킬스위치까지 강제 ON 잠금
    python -m investment_agent.operations.commands.emergency_stop --kill --lockdown-env

    # 4. 비상 정지 해제 (Re-arm)
    python -m investment_agent.operations.commands.emergency_stop --rearm --confirm I_CONFIRM_REARM_TRADING
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from investment_agent.platform.serialization import canonical_json
from investment_agent.operations.harness.emergency import (
    REARM_CONFIRMATION_PHRASE,
    check_runtime_status,
    emergency_stop,
    rearm_execution,
)

from investment_agent.operations.paths import REPOSITORY_ROOT as _ROOT
from investment_agent.operations.paths import HARNESS_STATE_DIR as _DEFAULT_STATE_DIR


def _safe_print(text: str) -> None:
    data = (text + "\n").encode("utf-8", errors="replace")
    stream = getattr(sys.stdout, "buffer", None)
    if stream is not None:
        stream.write(data)
        stream.flush()
    else:
        try:
            sys.stdout.write(text + "\n")
        except UnicodeEncodeError:
            sys.stdout.write(text.encode("ascii", errors="replace").decode("ascii") + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="투자 하네스 비상 긴급 정지 및 잠금 관리 도구")
    parser.add_argument(
        "--state-dir",
        default=str(_DEFAULT_STATE_DIR),
        help="하네스 상태 파일 디렉터리 경로",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="현재 하네스 프로세스, Durable Lockdown 및 킬스위치 상태 조회",
    )
    parser.add_argument(
        "--kill",
        action="store_true",
        help="Durable Lockdown 설정 후 실행 중인 하네스 데몬 프로세스 즉시 종료",
    )
    parser.add_argument(
        "--lockdown-env",
        action="store_true",
        help=".env 파일의 TRADING_KILL_SWITCH=on 으로 강제 변경",
    )
    parser.add_argument(
        "--rearm",
        action="store_true",
        help="Durable Execution Lockdown 해제 (명시적 --confirm 필요)",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help=f"Re-arm 확인 문구 (정확히 '{REARM_CONFIRMATION_PHRASE}' 입력)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON 형식으로 출력",
    )
    args = parser.parse_args(argv)
    state_dir = Path(args.state_dir).expanduser().resolve()

    if args.rearm:
        if args.confirm != REARM_CONFIRMATION_PHRASE:
            _safe_print(f"❌ Re-arm 실패: --confirm '{REARM_CONFIRMATION_PHRASE}' 문구가 필요합니다.")
            return 1
        unlocked = rearm_execution(state_dir=state_dir, confirmation=args.confirm)
        if args.json:
            _safe_print(canonical_json({"rearm_success": unlocked, "lockdown_removed": unlocked}))
        else:
            _safe_print("=" * 60)
            _safe_print("  🔓 Durable Execution Lockdown 해제 완료 (Re-armed)")
            _safe_print("=" * 60)
            _safe_print("  주의: 실주문을 실행하려면 TRADING_KILL_SWITCH 및 TOSS_LIVE_ENABLED 설정도 확인하세요.")
            _safe_print("=" * 60)
        return 0

    if args.status or (not args.kill and not args.lockdown_env):
        status = check_runtime_status(state_dir=state_dir)
        if args.json:
            _safe_print(canonical_json(status))
        else:
            _safe_print("=" * 60)
            _safe_print("  🔍 ATLAS Investment Harness — 런타임 상태")
            _safe_print("=" * 60)
            _safe_print(f"  프로세스 ID: {status['process_id']}")
            _safe_print(f"  프로세스 생존: {'🟢 활성 (Running)' if status['process_alive'] else '⚪ 비활성 (Stopped)'}")
            _safe_print(f"  정상 종료 여부: {status['stopped_cleanly']}")
            _safe_print(f"  하트비트 시각: {status['heartbeat_at']}")
            _safe_print(f"  트레이딩 킬스위치: {status['trading_kill_switch'].upper()}")
            _safe_print(f"  Durable Lockdown: {'🚨 잠금 활성 (LOCKED)' if status['execution_lockdown'] else '🟢 정상 (UNLOCKED)'}")
            _safe_print(f"  활성 잡 개수: {status['active_jobs_count']}")
            _safe_print("=" * 60)
        return 0

    if args.kill or args.lockdown_env:
        result = emergency_stop(
            state_dir=state_dir,
            kill_process=args.kill,
            lockdown_env_file=args.lockdown_env,
            repository_root=_ROOT,
        )
        if args.json:
            _safe_print(canonical_json(result))
        else:
            _safe_print("=" * 60)
            _safe_print("  🛑 비상 긴급 정지(EMERGENCY STOP) 완료")
            _safe_print("=" * 60)
            _safe_print(f"  종합 성공: {result['success']}")
            _safe_print(f"  Durable Lockdown 설정: {result['durable_lockdown_set']}")
            _safe_print(f"  대상 프로세스 ID: {result['target_pid']}")
            _safe_print(f"  프로세스 강제 종료 여부: {result['process_killed']}")
            _safe_print(f"  상태 파일 갱신(Paused): {result['state_updated']}")
            _safe_print(f"  .env 킬스위치 잠금: {result['env_locked']}")
            _safe_print(f"  정지 시각: {result['timestamp']}")
            _safe_print("=" * 60)
        return 0 if result["success"] else 1

    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    sys.exit(main())
