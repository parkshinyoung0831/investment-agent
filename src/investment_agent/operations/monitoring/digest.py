"""24시간치 실행 이력을 Discord 한 장짜리 요약으로 접는 순수 변환.

네트워크·DB를 건드리지 않으므로 픽스처만으로 검증할 수 있다.

## 이 카드가 답하는 질문

"조용한 게 정상이라 조용한 건가, 죽어서 조용한 건가."

지금까지 운영 알림은 실패했을 때만 울었다. 그래서 침묵이 두 가지를 동시에 뜻했고,
카드가 사흘 빠지는 동안 그게 정상인지 아닌지 알 방법이 없었다. 이 요약은 **매일
반드시 온다** — 안 오는 것 자체가 신호가 되도록.

## 네 가지를 본다

- **실패**: 구간 안에 코드·데이터가 깨진 결론(failure 등).
- **중단**: 취소·타임아웃. 실패와 색을 나누되 **묻지는 않는다** — 타임아웃이
  conclusion에 cancelled로 찍히는 탓에 한 번 놓쳐서 알림이 통째로 빠진 적이 있다.
  원인(인프라)과 대응이 다를 뿐, 카드가 안 나간 것은 똑같다.
- **미실행**: 돌았어야 하는데 실행 기록이 없나. 근거는 둘이다 — cron, 그리고 **상류
  성공**(`workflow_run`). cron만 보면 `notify_strategy`·`fundamentals_expectations`처럼 cron이
  아예 없는 워크플로는 한 달을 안 돌아도 아무 말도 못 한다.
- **채널 도착**: 워크플로가 초록이어도 카드가 채널에 없을 수 있다. 도착은 도착지에서만
  확인된다(`src/investment_agent/operations/discord.py`).

분류의 합은 항상 워크플로 총수와 같다 — '대상 아님'까지 세어야 **무엇을 안 보고
있는지**가 드러난다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from investment_agent.operations.palette import STATUS_DANGER, STATUS_INFO, STATUS_WARNING

# 결론이 이 둘이면 문제로 세지 않는다. skipped는 게이트가 정상 동작한 결과다.
_OK = {"success", "skipped"}
# 인프라가 끊은 것. 실패와 나누되 정상으로 치지는 않는다.
_STOPPED = {"cancelled", "timed_out"}
_KST = timezone(timedelta(hours=9))
_WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")
_MAX_LINES = 6


def _kst(moment: datetime) -> str:
    return moment.astimezone(_KST).strftime("%H:%M")


def _width(text: str) -> int:
    """한글·기호는 두 칸으로 센다 — 글자 수로 맞추면 표의 열이 어긋난다."""
    return sum(2 if ord(ch) > 0x1100 else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _width(text))


def _ago(moment: datetime | None, now: datetime) -> str:
    if moment is None:
        return "—"
    hours = (now - moment).total_seconds() / 3600
    if hours < 1:
        return f"{max(1, int(hours * 60))}분 전"
    if hours < 48:
        return f"{int(hours)}시간 전"
    return f"{int(hours / 24)}일 전"


def evaluate(
    workflows: list[dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
) -> dict[str, list[dict[str, Any]]]:
    """워크플로별 판정. workflows 각 항목: {name, crons, runs, expected}

    expected는 호출부가 cron으로 미리 계산해 넣는다(cron 해석을 여기 섞지 않는다).
    """
    failed: list[dict[str, Any]] = []
    stopped: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    healthy: list[dict[str, Any]] = []
    idle: list[dict[str, Any]] = []

    for wf in workflows:
        runs = wf.get("runs") or []
        done = [r for r in runs if r.get("status") == "completed"]
        bad = [r for r in done if r.get("conclusion") not in _OK]
        halted = [r for r in bad if r.get("conclusion") in _STOPPED]
        broken = [r for r in bad if r.get("conclusion") not in _STOPPED]
        running = [r for r in runs if r.get("status") != "completed"]

        def entry(rows: list[dict[str, Any]]) -> dict[str, Any]:
            worst = sorted(rows, key=lambda r: r["created_at"])[-1]
            # 그 뒤에 성공이 있었나. 고치고 다시 돌린 것과 지금도 깨져 있는 것을
            # 같은 줄로 읽으면, 이미 끝난 일을 매일 다시 확인하게 된다.
            recovered = any(
                r["created_at"] > worst["created_at"] and r.get("conclusion") in _OK
                for r in done
            )
            return {"name": wf["name"], "conclusion": worst.get("conclusion"),
                    "at": worst["created_at"], "url": worst.get("url"),
                    "count": len(rows), "recovered": recovered}

        # 실패와 중단이 같은 날 함께 있으면 **나쁜 쪽 하나로만** 센다. 두 칸에 모두
        # 넣으면 분류의 합이 워크플로 총수를 넘어, 합을 맞춘 의미가 사라진다.
        if broken:
            failed.append(entry(broken))
            continue
        if halted:
            stopped.append(entry(halted))
            continue
        if not runs and wf.get("expected"):
            missing.append({"name": wf["name"], "crons": wf.get("crons") or [],
                            "upstream": wf.get("expected_by")})
        elif runs:
            healthy.append({"name": wf["name"], "runs": len(runs),
                            "running": len(running)})
        else:
            # cron도 없고 실행도 없는 것(백필류). 문제는 아니지만 **세기는 한다** —
            # 합이 총수와 맞아야 카드가 무엇을 안 보고 있는지 드러난다.
            idle.append({"name": wf["name"]})

    return {"failed": failed, "stopped": stopped, "missing": missing,
            "healthy": healthy, "idle": idle}


# 상류가 끝나고 하류가 뜨기까지의 여유. 이 안이면 아직 '안 돈 것'이 아니다.
CHAIN_GRACE = timedelta(minutes=15)


def chain_expectations(
    workflows: list[dict[str, Any]], now: datetime, *, grace: timedelta = CHAIN_GRACE
) -> dict[str, str]:
    """상류가 성공했는데 그 뒤로 하류 실행이 없는 워크플로 -> 그렇게 판단한 근거.

    `workflow_run`으로만 이어지는 워크플로는 cron이 없어 '미실행' 판정 대상에서
    통째로 빠져 있었다. 체인이 끊기면 조용히 안 도는데 카드는 한 마디도 안 했다.

    유예를 두는 이유: 상류가 방금 끝났으면 하류는 아직 큐에 있을 수 있다.
    """
    by_name = {str(wf["name"]): wf for wf in workflows}
    out: dict[str, str] = {}
    for wf in workflows:
        latest: tuple[datetime, str] | None = None
        for upstream in wf.get("upstreams") or []:
            for run in (by_name.get(upstream, {}).get("runs") or []):
                if run.get("status") != "completed" or run.get("conclusion") != "success":
                    continue
                if latest is None or run["created_at"] > latest[0]:
                    latest = (run["created_at"], upstream)
        if latest is None or now - latest[0] < grace:
            continue
        if any(r["created_at"] >= latest[0] for r in (wf.get("runs") or [])):
            continue
        out[str(wf["name"])] = latest[1]
    return out


def failure_streak(runs: list[dict[str, Any]], *, stopped: bool = False) -> int:
    """같은 성격의 문제가 이어진 날 수(KST). 오늘 처음인지 사흘째 방치인지가 우선순위다.

    실패와 중단을 섞어 세면 안 된다 — 인프라 타임아웃 이틀 뒤에 코드가 깨진 것을
    '3일째 실패'라고 부르면, 고친 사람이 무엇을 고쳤는지 알 수 없게 된다.
    """
    days = {
        r["created_at"].astimezone(_KST).date()
        for r in runs
        if r.get("status") == "completed"
        and r.get("conclusion") not in _OK
        and ((r.get("conclusion") in _STOPPED) is stopped)
    }
    return len(days)


def judge_channels(
    rows: list[dict[str, Any]], now: datetime
) -> list[dict[str, Any]]:
    """채널별 판정. quiet_hours가 None이면 침묵을 문제로 보지 않는다."""
    out = []
    for row in rows:
        quiet = row.get("quiet_hours")
        last = row.get("last_at")
        if not row.get("configured"):
            verdict, alert = "채널 ID 없음", True
        elif row.get("error"):
            verdict, alert = "조회 실패", True
        elif quiet is None:
            verdict, alert = row.get("cadence") or "", False
        elif last is None:
            # 카드를 한 번도 못 받은 채널. 채널이 주기보다 어리면 아직 차례가 안 온 것이다.
            created = row.get("created_at")
            young = created is not None and (now - created) <= timedelta(hours=quiet)
            verdict, alert = ("첫 카드 대기" if young else "받은 적 없음"), not young
        elif (now - last) > timedelta(hours=quiet):
            verdict, alert = f"{row.get('cadence')} — 조용함", True
        else:
            verdict, alert = "", False
        out.append({**row, "verdict": verdict, "alert": alert})
    return out


def _section(title: str, items: list[dict[str, Any]], line) -> list[str]:
    if not items:
        return []
    out = [f"{title} {len(items)}"]
    for item in items[:_MAX_LINES]:
        out.append(line(item))
    if len(items) > _MAX_LINES:
        out.append(f"　… 외 {len(items) - _MAX_LINES}건")
    return out


# DESIGN-system.md는 카드 embed의 색 막대에 상승·하락 색을 금지한다(면적 채움이라).
# **운영 점검은 예외로 둔다** — 여기 색은 등락이 아니라 심각도이고, 이 카드는 시장이
# 아니라 시스템을 말한다. 파랑 하나로 칠하면 사고가 난 날과 조용한 날이 같아 보인다.
COLOR_OK = STATUS_INFO
COLOR_WARN = STATUS_WARNING
COLOR_FAIL = STATUS_DANGER


def severity_color(
    verdict: dict[str, list[dict[str, Any]]],
    channels: list[dict[str, Any]] | None = None,
) -> int:
    # 빨강은 "지금 깨져 있다"는 뜻이어야 한다. 아침에 깨졌다가 고쳐 다시 돌린 날까지
    # 빨강이면, 정말 깨진 날과 구분이 안 돼 색이 아무 말도 하지 않게 된다.
    if any(not item.get("recovered") for item in verdict["failed"]):
        return COLOR_FAIL
    if verdict["failed"] or verdict["stopped"] or verdict["missing"] or any(
        c["alert"] for c in (channels or [])
    ):
        return COLOR_WARN
    return COLOR_OK


def build_embed(
    verdict: dict[str, list[dict[str, Any]]],
    window_end: datetime,
    channels: list[dict[str, Any]] | None = None,
    counters: list[str] | None = None,
) -> dict[str, Any]:
    """발송용 embed. 평문 2000자 대신 4096자를 쓸 수 있고, 색이 심각도를 진다."""
    day = window_end.astimezone(_KST)
    body = render(verdict, window_end, channels, counters, head=False)
    return {
        "title": f"📋 파이프라인 일일 점검 · {day:%m-%d}({_WEEKDAYS[day.weekday()]}) "
                 f"{day:%H:%M} KST",
        "description": body[:4000],
        "color": severity_color(verdict, channels),
    }


def render(
    verdict: dict[str, list[dict[str, Any]]],
    window_end: datetime,
    channels: list[dict[str, Any]] | None = None,
    counters: list[str] | None = None,
    *,
    head: bool = True,
) -> str:
    """점검 본문. 평문으로 보낼 때는 2000자, embed 설명으로 쓸 때는 4096자가 한도다."""
    day = window_end.astimezone(_KST)
    headline = (f"📋 **일일 점검** · {day:%Y-%m-%d}({_WEEKDAYS[day.weekday()]}) "
                f"{day:%H:%M} KST")

    failed, stopped = verdict["failed"], verdict["stopped"]
    missing, healthy, idle = verdict["missing"], verdict["healthy"], verdict["idle"]
    total = len(failed) + len(stopped) + len(missing) + len(healthy) + len(idle)
    recovered = sum(1 for item in failed + stopped if item.get("recovered"))
    counts = (
        f"정상 {len(healthy)} · 실패 {len(failed)} · 중단 {len(stopped)} · "
        f"미실행 {len(missing)} · 대상 아님 {len(idle)}  (워크플로 {total})"
    )

    def run_line(item: dict[str, Any]) -> str:
        repeat = f" ×{item['count']}" if item["count"] > 1 else ""
        streak = f" ({item['streak']}일째)" if item.get("streak", 0) > 1 else ""
        # <>로 감싸 링크 미리보기를 막는다 — 카드 한 장에 미리보기가 여러 개 붙으면
        # 정작 읽어야 할 목록이 아래로 밀린다.
        link = f" · <{item['url']}>" if item.get("url") else ""
        mark = " ✅이후 성공" if item.get("recovered") else ""
        return (f"　`{item['name']}` {item['conclusion']}{repeat}{streak}{mark}"
                f" — {_kst(item['at'])} KST{link}")

    note = [f"그중 {recovered}건은 뒤이은 실행이 성공했다."] if recovered else []
    lines = ([headline] if head else []) + [counts] + note + [""]
    lines += _section("🔴 **실패**", failed, run_line)
    lines += _section("🟠 **중단**(타임아웃·취소)", stopped, run_line)
    def missing_line(item: dict[str, Any]) -> str:
        if item.get("upstream"):
            return f"　`{item['name']}` — 상류 `{item['upstream']}` 성공 뒤 실행 없음"
        return f"　`{item['name']}` — cron `{', '.join(item['crons'][:2])}`"

    lines += _section("⏸ **예정됐는데 실행 없음**", missing, missing_line)

    if counters:
        # 게이트가 '정상적으로' 0건을 내는 날을 잡는 유일한 줄이다.
        lines += ["", "🔢 **대기 상태**  " + " · ".join(counters)]

    if channels:
        alerts = [c for c in channels if c["alert"]]
        mark = "⚠️" if alerts else "✅"
        lines += ["", f"📡 **채널 도착** {mark}"]
        label_w = max(_width(str(c["label"])) for c in channels)
        rows = []
        for channel in channels:
            count = "—" if channel.get("count") is None else str(channel["count"])
            rows.append(
                f"{_pad(str(channel['label']), label_w)}  {count:>3}  "
                f"{_pad(_ago(channel.get('last_at'), window_end), 10)}"
                f"{channel['verdict']}".rstrip()
            )
        lines.append("```\n" + "\n".join(rows) + "\n```")

    if not (failed or stopped or missing) and not any(
        c["alert"] for c in (channels or [])
    ):
        lines.insert(2, "지난 24시간 이상 없습니다.")
    return "\n".join(lines)[:1900]
