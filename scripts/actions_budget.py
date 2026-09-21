"""GitHub Actions 월 사용량을 cron 빈도 × 실측 실행시간으로 추정한다.

무료 할당은 초과해도 경고가 오지 않고 그냥 잡이 돌지 않는다. 그래서 cron을 하나
늘리기 전에 "이게 한 달에 몇 분인가"를 답할 수 있어야 한다. 실행시간은 추측하지 않고
`gh run list`가 돌려준 실제 이력의 중앙값을 쓴다 — 이력이 없는 워크플로만 기본값으로
채우고 그 사실을 출력에 표시한다.

    python scripts/actions_budget.py                 # 이력 400건으로 추정
    python scripts/actions_budget.py --limit 800
    python scripts/actions_budget.py --allowance 2000

workflow_run 트리거는 자기 cron에 *더한다*. 상류가 끝날 때마다 러너가 한 번 더 뜨기
때문이다. 상류가 여럿이면 합으로 잡는다 — macro 알림 2종이 그렇게 양쪽을 듣는다.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

# 이력이 없는 워크플로에 쓰는 보수적 기본값(분).
DEFAULT_MINUTES = 2.0
DAYS_PER_MONTH = 30.44
WEEKS_PER_MONTH = DAYS_PER_MONTH / 7


def _runs_per_month(cron: str) -> float:
    """cron 한 줄이 한 달에 몇 번 도는지. 이 저장소가 쓰는 문법만 다룬다."""
    minute, hour, dom, month, dow = cron.split()
    if month != "*":
        raise ValueError(f"월 필드를 쓰는 cron은 지원하지 않는다: {cron}")

    def _count(field: str, span: int) -> float:
        if field == "*":
            return span
        if field.startswith("*/"):
            return span / int(field[2:])
        total = 0
        for part in field.split(","):
            if "-" in part:
                lo, hi = (int(x) for x in part.split("-"))
                total += hi - lo + 1
            else:
                total += 1
        return total

    per_day = _count(minute, 60) * _count(hour, 24)
    if dom != "*" and dow != "*":
        raise ValueError(f"day-of-month와 day-of-week를 동시에 쓰면 OR라 모호하다: {cron}")
    if dom != "*":
        return per_day * _count(dom, 31) * (DAYS_PER_MONTH / 31)
    if dow != "*":
        return per_day * _count(dow, 7) * WEEKS_PER_MONTH
    return per_day * DAYS_PER_MONTH


def _parse_workflows() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        crons = re.findall(r'^\s*-\s*cron:\s*["\']([^"\']+)["\']', text, re.M)
        upstream: list[str] = []
        match = re.search(r"^\s*workflows:\s*\[([^\]]*)\]", text, re.M)
        if match:
            upstream = [w.strip().strip("\"'") for w in match.group(1).split(",") if w.strip()]
        out[path.stem] = {"crons": crons, "upstream": upstream}
    return out


def _fetch_rows(limit: int) -> list[dict]:
    proc = subprocess.run(
        ["gh", "run", "list", "--limit", str(limit),
         "--json", "name,event,createdAt,startedAt,updatedAt"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    if proc.returncode != 0:
        print(f"경고: gh run list 실패 — 기본값으로만 추정한다\n{proc.stderr.strip()}", file=sys.stderr)
        return []
    return json.loads(proc.stdout or "[]")


def scheduled_rate_per_month(rows: list[dict]) -> dict[str, float]:
    """이력에서 본 워크플로별 **schedule 실행** 월 횟수.

    설계 빈도는 cron 문법으로 센 값이라, GitHub이 고빈도 cron을 큐에서 버리면 실제와 크게 다르다(15분 cron이
    한 달에 17번). 이력이 덮는 기간(가장 이른 실행~가장 늦은 실행)으로 나눠 월 값으로 환산한다.
    """
    stamps = [
        datetime.fromisoformat(str(row["createdAt"]).replace("Z", "+00:00"))
        for row in rows if row.get("createdAt")
    ]
    if len(stamps) < 2:
        return {}
    span_days = (max(stamps) - min(stamps)).total_seconds() / 86400
    if span_days < 1:
        return {}
    counts: dict[str, int] = {}
    for row in rows:
        if row.get("event") == "schedule":
            counts[row["name"]] = counts.get(row["name"], 0) + 1
    return {name: count / span_days * DAYS_PER_MONTH for name, count in counts.items()}


def _observed_minutes(limit: int) -> dict[str, float]:
    samples: dict[str, list[float]] = {}
    for row in _fetch_rows(limit):
        started, updated = row.get("startedAt"), row.get("updatedAt")
        if not started or not updated:
            continue
        begin = datetime.fromisoformat(started.replace("Z", "+00:00"))
        end = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        minutes = (end - begin).total_seconds() / 60
        # 취소된 채 매달린 실행은 실제 compute가 아니다.
        if 0 <= minutes <= 180:
            samples.setdefault(row["name"], []).append(minutes)
    # GitHub은 실행 시간을 분 단위로 올림 과금한다. 0.69분짜리도 1분이라, 중앙값을 그대로
    # 곱하면 짧은 잡이 잦은 워크플로가 실제보다 싸게 계산된다(올림은 단조라 중앙값에 바로 적용).
    return {name: float(math.ceil(statistics.median(v))) for name, v in samples.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts/actions_budget.py")
    parser.add_argument("--limit", type=int, default=400, help="조회할 실행 이력 수")
    parser.add_argument("--allowance", type=int, default=2000, help="월 할당(분)")
    args = parser.parse_args(argv)

    workflows = _parse_workflows()
    observed = _observed_minutes(args.limit)
    actual_rate = scheduled_rate_per_month(_fetch_rows(args.limit))

    frequency: dict[str, float] = {}
    for name, spec in workflows.items():
        frequency[name] = sum(_runs_per_month(c) for c in spec["crons"])
    # workflow_run은 cron과 더해진다. 상류가 끝날 때마다 러너가 한 번 더 뜨므로,
    # cron이 있다는 이유로 빼면 상류가 잦은 워크플로의 비용을 통째로 놓친다.
    cron_only = dict(frequency)
    for name, spec in workflows.items():
        frequency[name] += sum(cron_only.get(u, 0.0) for u in spec["upstream"])

    print(f"{'workflow':34s} {'runs/mo':>9s} {'min/run':>8s} {'min/mo':>9s}  source")
    total = 0.0
    estimated = 0.0
    for name in sorted(workflows, key=lambda n: -frequency[n] * observed.get(n, DEFAULT_MINUTES)):
        runs = frequency[name]
        if runs == 0:
            continue
        minutes = observed.get(name)
        source = "measured" if minutes is not None else "default"
        minutes = minutes if minutes is not None else DEFAULT_MINUTES
        monthly = runs * minutes
        total += monthly
        if source == "default":
            estimated += monthly
        print(f"{name:34s} {runs:9.1f} {minutes:8.2f} {monthly:9.1f}  {source}")

    # 설계대로 돌지 않는 cron. 분 예산은 설계 빈도로 재므로 이 워크플로들은 예산과 별개로 "안 도는" 문제다.
    dropped = [
        (name, cron_only[name], actual_rate.get(name, 0.0)) for name in sorted(workflows)
        if cron_only[name] >= 10 and actual_rate.get(name, 0.0) < cron_only[name] * 0.5
    ]
    if dropped:
        print("\n설계 빈도의 절반도 안 도는 schedule (GitHub이 고빈도 cron을 버림):")
        for name, designed, seen in dropped:
            print(f"  {name:32s} 설계 {designed:7.1f}/월  실측 {seen:6.1f}/월")
    manual = [n for n in sorted(workflows) if frequency[n] == 0]
    print(f"\n{'SCHEDULED TOTAL':34s} {'':9s} {'':8s} {total:9.1f} min/month")
    print(f"{'allowance':34s} {'':9s} {'':8s} {args.allowance:9d} min/month")
    headroom = args.allowance - total
    pct = total / args.allowance * 100 if args.allowance else 0
    print(f"{'headroom':34s} {'':9s} {'':8s} {headroom:9.1f} min/month  ({pct:.0f}% used)")
    if estimated:
        share = estimated / total * 100 if total else 0
        print(
            f"{'  of which unmeasured':34s} {'':9s} {'':8s} {estimated:9.1f} min/month"
            f"  ({share:.0f}%, 실행 이력이 없어 {DEFAULT_MINUTES}분 가정 - 한 번 돌린 뒤 다시 재라)"
        )
    print(f"\n수동/백필 전용({len(manual)}개): {', '.join(manual)}")

    if headroom < 0:
        print("\n초과다. cron을 줄이거나 워크플로를 합쳐야 한다.")
        return 1
    if pct > 70:
        print("\n여유가 30% 미만이다. retry·debug·수동 실행 몫이 부족하다.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
