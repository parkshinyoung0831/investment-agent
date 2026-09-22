"""투자 하네스 ON/OFF 스위치 및 제어판 CLI 진입점.

사용 예시:
    # 1. 종합 상태 조회
    python -m investment_agent.operations.commands.harness_switch --status

    # 2. 하네스 켜기 (기본: Shadow 모의투자, 백그라운드)
    python -m investment_agent.operations.commands.harness_switch --on
    python -m investment_agent.operations.commands.harness_switch --on --mode approval_workflow

    # 3. 하네스 끄기 (모든 프로세스 완전 정지 + 락 정리)
    python -m investment_agent.operations.commands.harness_switch --off

    # 4. 트레이딩 킬스위치 설정 (막는 쪽은 그냥, 허용하는 쪽은 확인 문구가 필요하다)
    python -m investment_agent.operations.commands.harness_switch --kill-switch on
    python -m investment_agent.operations.commands.harness_switch --kill-switch off \
        --confirm ALLOW_TRADING_ORDERS

    # 5. 토스 실주문 플래그 설정 (끄는 쪽은 그냥, 켜는 쪽은 확인 문구가 필요하다)
    python -m investment_agent.operations.commands.harness_switch --live-enabled false
    python -m investment_agent.operations.commands.harness_switch --live-enabled true \
        --confirm ENABLE_TOSS_LIVE

    # 6. 대화형 인터랙티브 메뉴 실행
    python -m investment_agent.operations.commands.harness_switch --interactive
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from investment_agent.platform.serialization import canonical_json
from investment_agent.operations.harness.maintenance import (
    clear_maintenance_hold,
    read_maintenance_hold,
    set_maintenance_hold,
)
from investment_agent.operations.harness.switch import (
    ALLOW_ORDERS_CONFIRMATION,
    ENABLE_LIVE_CONFIRMATION,
    get_harness_status,
    set_kill_switch,
    set_live_enabled,
    start_harness_service,
    stop_harness_service,
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


def _ask_confirmation(phrase: str, why: str) -> str:
    """확인 문구를 그대로 입력받는다. 틀리면 그 입력을 그대로 넘겨 setter가 거절한다.

    여기서 판정하지 않는 것이 중요하다 — 판정은 setter 하나가 한다(진입점마다
    다시 구현하면 한 곳이 느슨해진다).
    """
    _safe_print(f"\n⚠️  {why}")
    _safe_print(f"   계속하려면 다음을 그대로 입력하세요: {phrase}")
    return input("   확인 문구: ").strip()


def print_status_dashboard(status_dict: dict) -> None:
    _safe_print("=" * 65)
    _safe_print("   ⚡ ATLAS Investment Harness — 런타임 스위치 제어판")
    _safe_print("=" * 65)
    running_badge = "🟢 가동 중 (RUNNING)" if status_dict["is_running"] else "⚪ 정지됨 (STOPPED)"
    _safe_print(f"  * 하네스 실행 상태   : {running_badge}")
    _safe_print(f"  * 프로세스 ID (PID)  : {status_dict['process_id'] or 'N/A'}")
    _safe_print(f"  * 하트비트 시각      : {status_dict['heartbeat_at'] or 'N/A'}")
    _safe_print(f"  * 정상 종료 여부     : {status_dict['stopped_cleanly']}")
    _safe_print(f"  * 프로세스 락 파일   : {'존재 (Locked)' if status_dict['lock_file_exists'] else '없음'}")
    # `mode`는 실제로 그 프로세스가 떴을 때 기록한 값이다(감사 OP2-07) — `.env`에서 다시
    # 계산한 값이 아니라서, 돌고 있지 않으면 None이다.
    mode = status_dict.get("mode")
    _safe_print(f"  * 기동 모드          : {mode or ('N/A (정지됨)' if not status_dict['is_running'] else '알 수 없음')}")
    _safe_print("-" * 65)
    kill_badge = "🚨 ON (신규 주문 전역 차단)" if status_dict["trading_kill_switch"] in {"1", "on", "true", "yes"} else "🟢 OFF (게이트 통과 시 주문 허용)"
    live_badge = "🟢 TRUE (실매매 연동)" if status_dict["toss_live_enabled"] else "⚪ FALSE (실매매 비활성)"
    _safe_print(f"  * TRADING_KILL_SWITCH: {kill_badge}")
    _safe_print(f"  * TOSS_LIVE_ENABLED  : {live_badge}")
    _safe_print(f"  * AI_INVESTOR_MODE   : {status_dict['ai_investor_mode']}")
    _safe_print(f"  * Durable Lockdown   : {'🚨 잠금 활성 (LOCKED)' if status_dict['execution_lockdown'] else '🟢 정상 (UNLOCKED)'}")
    if status_dict.get("maintenance_hold"):
        reason = status_dict.get("maintenance_reason") or "-"
        _safe_print(f"  * 정비 보류          : 🛠 걸림 (기동 차단, reason={reason})")
    else:
        _safe_print("  * 정비 보류          : 🟢 없음 (기동 가능)")
    _safe_print("-" * 65)
    _safe_print(f"  * 등록된 잡 요약 ({status_dict['active_jobs_count']}개 활성):")
    for j_name, j_stat in status_dict.get("jobs_summary", {}).items():
        _safe_print(f"    - {j_name:<24}: {j_stat}")
    _safe_print("=" * 65)


def interactive_loop(state_dir: Path, root_dir: Path) -> int:
    while True:
        status = get_harness_status(state_dir=state_dir, root_dir=root_dir)
        print_status_dashboard(status.to_dict())
        _safe_print("")
        _safe_print("  [1] 하네스 켜기 (ON - AI 모의투자 / Shadow / analysis_only) ⭐ 추천")
        _safe_print("  [2] 하네스 켜기 (ON - 실계좌 승인 / approval_workflow)")
        _safe_print("  [3] 하네스 끄기 (OFF - 모든 프로세스 완전 정지 및 락 정리)")
        _safe_print("  [4] 킬스위치 토글 (TRADING_KILL_SWITCH on <-> off)")
        _safe_print("  [5] 실주문 토글 (TOSS_LIVE_ENABLED true <-> false)")
        _safe_print("  [6] 정비 보류 토글 (걸면 하네스가 아예 기동하지 않음) 🛠")
        _safe_print("  [R] 새로고침")
        _safe_print("  [0] 나가기")
        _safe_print("")
        try:
            choice = input("선택 [1/2/3/4/5/6/R/0]: ").strip()
        except (KeyboardInterrupt, EOFError):
            _safe_print("\n종료합니다.")
            return 0

        if choice == "1":
            _safe_print("\n[작업] Shadow 모의투자 하네스를 백그라운드에서 시작합니다...")
            res = start_harness_service(mode="analysis_only", state_dir=state_dir, root_dir=root_dir, background=True)
            _safe_print(f"결과: {res.get('message')}")
            input("\n계속하려면 Enter를 누르세요...")
        elif choice == "2":
            _safe_print("\n[작업] 실계좌 승인 하네스를 백그라운드에서 시작합니다...")
            res = start_harness_service(mode="approval_workflow", state_dir=state_dir, root_dir=root_dir, background=True)
            _safe_print(f"결과: {res.get('message')}")
            input("\n계속하려면 Enter를 누르세요...")
        elif choice == "3":
            _safe_print("\n[작업] 실행 중인 하네스 프로세스를 완전 정지합니다...")
            res = stop_harness_service(state_dir=state_dir, root_dir=root_dir)
            _safe_print(f"결과: {res.get('message')} (정지된 PID: {res.get('killed_pids')})")
            input("\n계속하려면 Enter를 누르세요...")
        elif choice == "4":
            # 토글이 아니라 목표 상태를 받는다 — 화면을 잘못 읽으면 끄려다 켜게 된다.
            blocked = status.trading_kill_switch in {"1", "on", "true", "yes"}
            _safe_print(f"\n현재 킬스위치: {'ON (주문 차단)' if blocked else 'OFF (주문 허용)'}")
            target = input("목표 상태를 입력하세요 (on=차단 / off=허용, 그 외는 취소): ").strip().lower()
            if target not in {"on", "off"}:
                _safe_print("취소했습니다. 바뀐 것이 없습니다.")
            else:
                res = set_kill_switch(
                    target, root_dir=root_dir,
                    confirm=_ask_confirmation(
                        ALLOW_ORDERS_CONFIRMATION,
                        "신규 주문을 허용하는 변경입니다.",
                    ) if target == "off" else None,
                )
                _safe_print(f"\n[변경] {res.get('message')}")
            input("\n계속하려면 Enter를 누르세요...")
        elif choice == "5":
            live = status.toss_live_enabled
            _safe_print(f"\n현재 실매매: {'TRUE (연동)' if live else 'FALSE (비활성)'}")
            target = input("목표 상태를 입력하세요 (true=연동 / false=비활성, 그 외는 취소): ").strip().lower()
            if target not in {"true", "false"}:
                _safe_print("취소했습니다. 바뀐 것이 없습니다.")
            else:
                res = set_live_enabled(
                    target == "true", root_dir=root_dir,
                    confirm=_ask_confirmation(
                        ENABLE_LIVE_CONFIRMATION,
                        "실제 돈으로 주문을 내는 경로를 켜는 변경입니다.",
                    ) if target == "true" else None,
                )
                _safe_print(f"\n[변경] {res.get('message')}")
            input("\n계속하려면 Enter를 누르세요...")
        elif choice == "6":
            if read_maintenance_hold(state_dir):
                clear_maintenance_hold(state_dir=state_dir)
                _safe_print("\n[변경] 정비 보류를 해제했습니다. 거래 킬스위치는 그대로입니다.")
            else:
                set_maintenance_hold(state_dir=state_dir, reason="interactive")
                _safe_print("\n[변경] 정비 보류를 걸었습니다. 하네스는 기동하지 않습니다.")
            input("\n계속하려면 Enter를 누르세요...")
        elif choice.lower() == "r":
            continue
        elif choice == "0":
            _safe_print("\n종료합니다.")
            return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="투자 하네스 ON/OFF 스위치 및 런타임 제어기")
    parser.add_argument(
        "--state-dir",
        default=str(_DEFAULT_STATE_DIR),
        help="하네스 상태 파일 디렉터리 경로",
    )
    parser.add_argument(
        "--root-dir",
        default=str(_ROOT),
        help="프로젝트 루트 디렉터리 경로",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="현재 하네스 실행 및 설정 상태 조회",
    )
    parser.add_argument(
        "--on",
        action="store_true",
        help="하네스 서비스 시작 (ON)",
    )
    parser.add_argument(
        "--off",
        action="store_true",
        help="하네스 서비스 정지 (OFF)",
    )
    parser.add_argument(
        "--mode",
        choices=["analysis_only", "approval_workflow"],
        default="analysis_only",
        help="하네스 가동 모드 (기본: analysis_only)",
    )
    parser.add_argument(
        "--no-background",
        action="store_true",
        help="포그라운드 모드로 준비",
    )
    parser.add_argument(
        "--kill-switch",
        choices=["on", "off"],
        help="TRADING_KILL_SWITCH 값 변경",
    )
    parser.add_argument(
        "--live-enabled",
        choices=["true", "false"],
        help="TOSS_LIVE_ENABLED 값 변경",
    )
    parser.add_argument(
        "--confirm",
        help=(
            "주문을 허용하는 방향으로 게이트를 바꿀 때 필요한 확인 문구. "
            f"--kill-switch off는 {ALLOW_ORDERS_CONFIRMATION}, "
            f"--live-enabled true는 {ENABLE_LIVE_CONFIRMATION}. "
            "막는 방향(on/false)은 문구 없이 즉시 적용된다"
        ),
    )
    parser.add_argument(
        "--maintenance",
        choices=["on", "off"],
        help="정비 보류. on이면 어떤 진입점으로도 하네스가 기동하지 않는다",
    )
    parser.add_argument(
        "--maintenance-reason",
        default="manual",
        help="정비 보류 사유 (기록용)",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="대화형 콘솔 메뉴 실행",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON 형식으로 출력",
    )
    args = parser.parse_args(argv)
    state_dir = Path(args.state_dir).expanduser().resolve()
    root_dir = Path(args.root_dir).expanduser().resolve()

    if args.interactive:
        return interactive_loop(state_dir, root_dir)

    if args.maintenance:
        if args.maintenance == "on":
            path = set_maintenance_hold(state_dir=state_dir, reason=args.maintenance_reason)
            # 보류는 "기동 금지"이지 "정지"가 아니다. 이미 도는 프로세스는 그대로라서, 성공 메시지만
            # 보고 안전해졌다고 믿지 않도록 실행 여부를 함께 알린다(감사 OP2-05).
            running = get_harness_status(state_dir=state_dir, root_dir=root_dir).is_running
            message = f"정비 보류를 걸었습니다. 하네스는 새로 기동하지 않습니다 ({path.name})."
            if running:
                message += (
                    " 지금 돌고 있는 하네스 프로세스는 멈추지 않았습니다 —"
                    " 코드를 고치기 전에 `--off`로 따로 정지하세요."
                )
            res = {
                "success": True,
                "maintenance_hold": True,
                "is_running": running,
                "message": message,
            }
        else:
            cleared = clear_maintenance_hold(state_dir=state_dir)
            res = {
                "success": True,
                "maintenance_hold": False,
                "message": (
                    "정비 보류를 해제했습니다. 거래 킬스위치는 그대로입니다."
                    if cleared else "걸려 있던 정비 보류가 없습니다."
                ),
            }
        if args.json:
            _safe_print(canonical_json(res))
        else:
            _safe_print(res["message"])
        return 0

    if args.kill_switch:
        res = set_kill_switch(args.kill_switch, root_dir=root_dir, confirm=args.confirm)
        if args.json:
            _safe_print(canonical_json(res))
        else:
            _safe_print(res.get("message", "완료"))
        return 0 if res.get("success") else 1

    if args.live_enabled:
        res = set_live_enabled(
            args.live_enabled == "true", root_dir=root_dir, confirm=args.confirm,
        )
        if args.json:
            _safe_print(canonical_json(res))
        else:
            _safe_print(res.get("message", "완료"))
        return 0 if res.get("success") else 1

    if args.on:
        res = start_harness_service(
            mode=args.mode,
            state_dir=state_dir,
            root_dir=root_dir,
            background=not args.no_background,
        )
        if args.json:
            _safe_print(canonical_json(res))
        else:
            _safe_print(res.get("message", "하네스 시작 시도 완료"))
        return 0 if res.get("success") else 1

    if args.off:
        res = stop_harness_service(state_dir=state_dir, root_dir=root_dir)
        if args.json:
            _safe_print(canonical_json(res))
        else:
            _safe_print(res.get("message", "하네스 정지 완료"))
            if res.get("killed_pids"):
                _safe_print(f"  - 정지된 프로세스 PID: {res['killed_pids']}")
        return 0 if res.get("success") else 1

    # 기본값: 상태 조회
    status = get_harness_status(state_dir=state_dir, root_dir=root_dir)
    if args.json:
        _safe_print(canonical_json(status.to_dict()))
    else:
        print_status_dashboard(status.to_dict())
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    sys.exit(main())
