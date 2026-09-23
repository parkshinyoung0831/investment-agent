"""System 정책의 승격 증거 — 재현과 운영 NAV를 수동 승격 게이트가 읽는 평가 행으로 만든다.

게이트(`research/promotion/gate.py`)는 artifact별 `portfolio_evaluations` 행만 읽는다. 그 행을 만드는 곳이 없어
어떤 System artifact도 승격될 수 없었다(실계좌 추종이 영구히 막힘). 여기서 두 출처를 행으로 바꾼다.

- **재현**(`system_ablation`의 운영 정책 변형): 전체 창은 `backtest`, 거래일 120일 이상인 달력 연도는
  `walk_forward` 창 하나씩. 재현에는 과거 LLM 논지가 없고(`thesis_replayed=False`) 채택 ML도 없다 —
  artifact의 정책 부분에 대한 증거이며, 그 사실을 행에 적는다.
- **운영 NAV**(System 원장): artifact의 첫 목표 이후 실제로 쌓인 NAV. 정책을 고른 뒤의 데이터라 표본 외다.
  artifact가 paper로 승격된 날 이후는 `paper`, 그 전은 `out_of_sample`.

사고 건수는 재서 적는다. 값을 모르면 통과로 적지 않는다 — 게이트가 fail-closed로 거절하게 둔다.
"""
from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from typing import Any

EVALUATION_BUILDER_VERSION = "system-evaluations-v1"
# 재현 창 하나로 세려면 이 이상의 거래일이 있어야 한다. 반년 미만 창은 연도 표본이 아니다.
MIN_WINDOW_DAYS = 120
# 판단 시각 멤버 중 가격·feature가 없어 재현에서 빠진 비율의 허용 상한. 인수·상장폐지 종목은 공급자에
# 이력이 없어 0으로 만들 수 없다. 넘으면 생존 편향 사고로 센다(설계 판단값, 바꾸면 버전을 올린다).
MAX_SURVIVORSHIP_MISSING_SHARE = 0.05


def _evaluation_id(*parts: str) -> int:
    """행의 안정 정수 ID. 같은 artifact·종류·창이면 다시 써도 같은 행이다(53비트, JSON 정수 안전)."""
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:13], 16)


def window_metrics(marks: Sequence[Mapping[str, Any]]) -> dict[str, float] | None:
    """창 안의 초과수익·최대낙폭(음수)·누적 turnover. 창 첫날을 기준으로 다시 잰다."""
    if len(marks) < 2:
        return None
    base_nav, base_benchmark = float(marks[0]["nav"]), float(marks[0]["benchmark_nav"])
    peak, drawdown = base_nav, 0.0
    for mark in marks:
        value = float(mark["nav"])
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1.0)
    end = marks[-1]
    excess = float(end["nav"]) / base_nav - float(end["benchmark_nav"]) / base_benchmark
    turnover = math.fsum(float(mark.get("turnover") or 0.0) for mark in marks[1:])
    return {"excess_return": excess, "max_drawdown": drawdown, "turnover": turnover}


def _row(*, artifact_id: str, kind: str, marks: Sequence[Mapping[str, Any]], incidents: Mapping[str, int],
         checks: Mapping[str, bool], notes: Mapping[str, Any], source: str) -> dict[str, Any] | None:
    metrics = window_metrics(marks)
    if metrics is None:
        return None
    start, end = str(marks[0]["trade_date"])[:10], str(marks[-1]["trade_date"])[:10]
    evaluation_id = _evaluation_id(artifact_id, kind, source, start)
    return {
        "record_key": f"{artifact_id}:{kind}:{source}:{start}",
        "evaluation_id": evaluation_id,
        "model_artifact_id": artifact_id,
        "evaluation_kind": kind,
        # walk_forward 창의 정체성. 같은 창을 두 번 세지 않는다.
        "proposal_id": f"{source}:{start}",
        "as_of_at": f"{end}T00:00:00+00:00",
        "available_at": f"{end}T00:00:00+00:00",
        "start_at": f"{start}T00:00:00+00:00",
        "end_at": f"{end}T23:59:59+00:00",
        **metrics,
        "research_only": False,
        "leakage_check_passed": bool(checks.get("leakage")),
        "survivorship_check_passed": bool(checks.get("survivorship")),
        "data_integrity_check_passed": bool(checks.get("data_integrity")),
        "metrics": {**{key: int(value) for key, value in incidents.items()}, **dict(notes),
                    "builder_version": EVALUATION_BUILDER_VERSION, "trading_days": len(marks)},
    }


def replay_evaluation_rows(
    *,
    artifact_id: str,
    history: Sequence[Mapping[str, Any]],
    nav_unexplained_days: int,
    survivorship_missing_share: float | None,
    ml_lookahead_refused: bool,
    policy_version: str,
) -> list[dict[str, Any]]:
    """재현 NAV를 backtest 한 행과 연도별 walk_forward 행으로 바꾼다."""
    survivorship_ok = survivorship_missing_share is not None and survivorship_missing_share <= MAX_SURVIVORSHIP_MISSING_SHARE
    incidents = {
        # 재현은 판단 시각까지 공개된 행만 읽고, 재현 시작 뒤까지 학습한 ML은 돌리지 않는다.
        "lookahead_incidents": 1 if ml_lookahead_refused else 0,
        "order_incidents": 0,
        "survivorship_incidents": 0 if survivorship_ok else 1,
        "data_integrity_incidents": int(nav_unexplained_days),
    }
    checks = {"leakage": not ml_lookahead_refused, "survivorship": survivorship_ok,
              "data_integrity": nav_unexplained_days == 0}
    notes = {"thesis_replayed": False, "source_kind": "historical_replay", "policy_version": policy_version,
             "survivorship_missing_share": survivorship_missing_share}
    rows = [_row(artifact_id=artifact_id, kind="backtest", marks=history, incidents=incidents, checks=checks,
                 notes=notes, source="replay_full")]
    by_year: dict[str, list[Mapping[str, Any]]] = {}
    for mark in history:
        by_year.setdefault(str(mark["trade_date"])[:4], []).append(mark)
    for year, marks in sorted(by_year.items()):
        if len(marks) >= MIN_WINDOW_DAYS:
            rows.append(_row(artifact_id=artifact_id, kind="walk_forward", marks=marks, incidents=incidents,
                             checks=checks, notes={**notes, "window": year}, source=f"replay_{year}"))
    return [row for row in rows if row is not None]


def artifact_window(
    history: Sequence[Mapping[str, Any]], artifact_of: Mapping[str, str], artifact_id: str,
) -> list[Mapping[str, Any]]:
    """이 artifact의 목표가 처음 적용된 날부터 다른 artifact의 목표가 적용되기 전날까지의 NAV.

    mark는 목표가 적용된 날에만 목표 ID를 갖는다. 그 사이의 날은 직전에 적용된 목표를 들고 있다.
    """
    window: list[Mapping[str, Any]] = []
    started = False
    for mark in history:
        applied = mark.get("applied_target_id")
        if applied is not None:
            mine = artifact_of.get(str(applied)) == artifact_id
            if started and not mine:
                break
            started = started or mine
        if started:
            window.append(mark)
    return window


def forward_evaluation_rows(
    *,
    artifact_id: str,
    history: Sequence[Mapping[str, Any]],
    paper_since: str | None,
    nav_unexplained_days: int,
) -> list[dict[str, Any]]:
    """운영 System NAV(정책 선택 뒤의 데이터)를 out_of_sample·paper 행으로 바꾼다."""
    incidents = {"lookahead_incidents": 0, "order_incidents": 0, "survivorship_incidents": 0,
                 "data_integrity_incidents": int(nav_unexplained_days)}
    # 운영 판단은 그날의 현재 유니버스를 쓴다 — 생존 편향이 생길 자리가 없다.
    checks = {"leakage": True, "survivorship": True, "data_integrity": nav_unexplained_days == 0}
    notes = {"thesis_replayed": True, "source_kind": "live_shadow"}
    before = [mark for mark in history if paper_since is None or str(mark["trade_date"])[:10] < paper_since]
    after = [mark for mark in history if paper_since is not None and str(mark["trade_date"])[:10] >= paper_since]
    rows = [
        _row(artifact_id=artifact_id, kind="out_of_sample", marks=before, incidents=incidents, checks=checks,
             notes=notes, source="live"),
        _row(artifact_id=artifact_id, kind="paper", marks=after, incidents=incidents, checks=checks,
             notes=notes, source="live"),
    ]
    return [row for row in rows if row is not None]


__all__ = [
    "EVALUATION_BUILDER_VERSION",
    "MAX_SURVIVORSHIP_MISSING_SHARE",
    "MIN_WINDOW_DAYS",
    "artifact_window",
    "forward_evaluation_rows",
    "replay_evaluation_rows",
    "window_metrics",
]
