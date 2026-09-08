"""매일 한 번 파이프라인 상태를 Discord로 알린다.

    python -m investment_agent.operations.commands.heartbeat [--hours 24] [--dry-run] [--no-discord]

cron은 워크플로 파일에서 직접 읽는다 — 별도 목록을 두면 워크플로를 고칠 때 같이
고쳐야 하고, 그 동기화가 어긋나는 순간 이 점검 자체가 거짓말을 한다. `workflow_run`의
상류 목록도 같은 이유로 파일에서 읽는다.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import timedelta
from pathlib import Path

from investment_agent.operations.runtime import notify_ops
from investment_agent.platform.logging import configure_logging, get_logger
from investment_agent.operations.monitoring import channels, counters, cron, digest, discord
from investment_agent.operations.monitoring import github_actions
from investment_agent.platform.storage_paths import repository_root

log = get_logger(__name__)

_WORKFLOW_DIR = repository_root() / ".github" / "workflows"
_CRON_RE = re.compile(r"^\s*-\s*cron:\s*[\"']([^\"']+)[\"']", re.M)
# `workflows:`는 workflow_run 트리거 아래에만 나온다(test_workflow_wiring이 지킨다).
_UPSTREAM_RE = re.compile(r"workflows:\s*\[([^\]]*)\]")
# 연속 실패 일수를 세는 구간. 실패한 워크플로에만 추가로 조회한다.
_STREAK_DAYS = 7


def _uncommented(path: Path) -> str:
    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def crons_for(path: Path) -> list[str]:
    """워크플로 파일의 schedule cron 목록(주석 처리된 줄은 제외)."""
    return _CRON_RE.findall(_uncommented(path))


def upstreams_for(path: Path) -> list[str]:
    """workflow_run으로 이 워크플로를 깨우는 상류 워크플로 이름들."""
    names: list[str] = []
    for group in _UPSTREAM_RE.findall(_uncommented(path)):
        names += [n.strip().strip('"').strip("'") for n in group.split(",") if n.strip()]
    return names


def _emit(text: str) -> None:
    """카드 본문에 이모지가 들어가는데 Windows 콘솔 기본 코드페이지(cp949)로는
    인코딩이 터진다 — 미리보기가 개발자 기계에서 죽으면 쓸모가 없다."""
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        print(text)  # noqa: T201 - --dry-run은 사람이 눈으로 보라고 있는 옵션이다
        return
    stream.write(text.encode("utf-8", "replace") + b"\n")
    stream.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="파이프라인 일일 점검 알림")
    parser.add_argument("--hours", type=int, default=24, help="점검 구간(시간)")
    parser.add_argument("--dry-run", action="store_true", help="전송하지 않고 본문만 출력")
    parser.add_argument("--no-discord", action="store_true",
                        help="채널 도착·대기 상태 조회를 건너뛴다(토큰이 없을 때)")
    args = parser.parse_args()

    configure_logging()
    end = github_actions.now_utc()
    start = end - timedelta(hours=args.hours)

    entries = []
    for wf in github_actions.list_workflows():
        path = _WORKFLOW_DIR / Path(str(wf["path"])).name
        crons = crons_for(path) if path.exists() else []
        entries.append({
            "name": wf["name"],
            "id": int(wf["id"]),
            "crons": crons,
            "upstreams": upstreams_for(path) if path.exists() else [],
            "expected": any(cron.fires_between(expr, start, end) for expr in crons),
            "runs": github_actions.runs_since(int(wf["id"]), start),
        })

    # cron이 없어도 상류가 성공했으면 돌았어야 한다. cron만 보면 notify_strategy·
    # fundamentals_expectations처럼 cron이 없는 워크플로는 한 달을 안 돌아도 조용하다.
    by_name = {entry["name"]: entry for entry in entries}
    for name, upstream in digest.chain_expectations(entries, end).items():
        by_name[name]["expected"] = True
        by_name[name]["expected_by"] = upstream

    verdict = digest.evaluate(entries, start, end)

    # 실패한 것만 구간을 넓혀 다시 조회해 '며칠째인지'를 센다. 오늘 처음인지 사흘째
    # 방치인지가 대응 우선순위를 정한다.
    streak_since = end - timedelta(days=_STREAK_DAYS)
    for kind, items in (("failed", verdict["failed"]), ("stopped", verdict["stopped"])):
        for item in items:
            entry = by_name.get(item["name"])
            if entry is None:
                continue
            try:
                item["streak"] = digest.failure_streak(
                    github_actions.runs_since(entry["id"], streak_since, limit=100),
                    stopped=(kind == "stopped"),
                )
            except Exception:  # noqa: BLE001 - 부가 정보가 점검을 죽이면 안 된다
                log.warning("heartbeat: %s 연속 실패 조회 실패", item["name"],
                            exc_info=True)

    # 채널 도착 확인. 워크플로가 초록이어도 카드가 채널에 없을 수 있고, 그건 여기서만
    # 보인다. 조회가 통째로 실패해도 워크플로 점검은 나가야 하므로 잡아 둔다.
    judged: list = []
    counter_lines: list[str] = []
    if not args.no_discord:
        try:
            judged = digest.judge_channels(
                discord.collect(channels.WATCHED, start), end
            )
        except Exception:
            log.warning("heartbeat: 채널 도착 확인 실패 — 워크플로 점검만 보낸다", exc_info=True)
        # 게이트가 '정상적으로' 0건을 내는 날을 잡는 유일한 줄.
        counter_lines = counters.collect()

    body = digest.render(verdict, end, judged, counter_lines)
    log.info(
        "heartbeat: workflows=%d healthy=%d failed=%d stopped=%d missing=%d "
        "idle=%d channels=%d alerts=%d counters=%d",
        len(entries), len(verdict["healthy"]), len(verdict["failed"]),
        len(verdict["stopped"]), len(verdict["missing"]), len(verdict["idle"]),
        len(judged), sum(1 for c in judged if c["alert"]), len(counter_lines),
    )
    if args.dry_run:
        _emit(body)
        return 0

    sent = notify_ops(
        body,
        logger=log,
        embeds=[digest.build_embed(verdict, end, judged, counter_lines)],
    )
    if not sent:
        # 전달되지 않은 heartbeat를 외부 dead-man's switch에 정상으로 찍으면 감시가
        # 거꾸로 거짓말한다. 공통 실패 리포터가 이 비정상 종료를 한 번 더 알린다.
        log.error("heartbeat Discord delivery failed")
        return 1
    # 하트비트가 죽으면 이 저장소 안의 무엇도 그걸 못 알린다 — GitHub Actions가 멈추면
    # 감시자도 같이 멈춘다. 바깥에서 핑이 끊긴 걸 봐 주는 곳이 있어야 한다.
    counters.ping(os.environ.get("OPS_HEARTBEAT_PING_URL", "").strip())
    # 점검이 문제를 찾았다고 점검 잡을 실패시키지 않는다 — 실패로 칠하면 이 잡의
    # 실패 알림과 본문이 겹쳐 두 번 운다.
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
