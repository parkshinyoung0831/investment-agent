"""출처 함수들이 공통으로 쓰는 도우미 모음(성공값 + 실패목록 함께 반환)."""
from __future__ import annotations

import os
import time
from collections.abc import Callable
from logging import Logger

import pandas as pd

from investment_agent.data.macro.domain.quality import validate_series

# 소스 하나가 실행 전체를 잡아먹지 못하게 막는 벽시계 예산(초).
# ECOS는 지표 15종을 순차로 부르는데, 응답이 늦으면 요청당 30초 타임아웃에 재시도
# 4회가 곱해져 워크플로 캡(20분)을 넘긴다. 그러면 이미 받아둔 미국 지표까지 통째로
# 사라진다 — 예산을 넘긴 시점부터는 남은 지표를 호출하지 않고 실패로 적어 부분 성공을 남긴다.
# 네 소스는 병렬로 도니 전체 수집 시간은 대략 이 값 하나로 묶인다.
SOURCE_BUDGET_SEC = float(os.environ.get("MACRO_SOURCE_BUDGET_SEC", "360"))


def normalize_tz(s: pd.Series) -> pd.Series:
    """날짜의 timezone 정보를 떼어 형식 통일(yfinance 등 tz 표기 제각각 대응)."""
    if isinstance(s.index, pd.DatetimeIndex) and s.index.tz is not None:
        s = s.copy()
        s.index = s.index.tz_localize(None)
    return s


def safe_fetch(
    log: Logger,
    indicators: list[dict],
    fetch_per: Callable[[dict], pd.Series],
    *,
    budget_sec: float | None = None,
) -> tuple[dict[str, pd.Series], list[dict]]:
    """지표를 하나씩 fetch. 하나 실패해도 멈추지 않고 성공값+실패목록을 함께 반환.

    budget_sec를 넘기면 그 시점부터 남은 지표는 호출하지 않고 실패로 적는다(0 이하면 무제한).
    상한은 지표 사이에서만 보므로 마지막 한 건은 예산을 넘겨 끝날 수 있다.
    """
    budget = SOURCE_BUDGET_SEC if budget_sec is None else budget_sec
    deadline = time.monotonic() + budget if budget > 0 else None
    out: dict[str, pd.Series] = {}
    failures: list[dict] = []
    for ind in indicators:
        sid = ind["series_id"]
        try:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(f"source budget {budget:.0f}s exhausted before {sid}")
            s = fetch_per(ind)
            s = normalize_tz(s if s is not None else pd.Series(dtype=float))
            if s.dropna().empty:
                raise ValueError("data source returned an empty series")
            validate_series(ind, s)
            out[sid] = s
            log.info("  OK %s (%d rows)", sid, len(s))
        except Exception as e:  # noqa: BLE001 - 지표별 실패를 모아 부분 성공을 보존한다.
            log.warning("  FAIL %s: %s", sid, e)
            out[sid] = pd.Series(dtype=float)
            failures.append({"series_id": sid, "error": str(e), "type": type(e).__name__})
    return out, failures
