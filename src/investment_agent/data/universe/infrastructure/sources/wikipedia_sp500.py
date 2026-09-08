"""wikipedia.py — 위키 S&P 500 문서에서 현재 멤버 + 편입/탈락 기록 수집.
User-Agent로 신원을 밝혀 차단 회피, 실패 시 재시도, 받은 페이지는 캐싱.
표 구조가 예상과 다르면 즉시 오류 → 잘못된 데이터 유입 방지."""
from __future__ import annotations

from functools import lru_cache
from io import StringIO

import pandas as pd
import requests

from investment_agent.data.universe.domain.normalization import norm_ticker
from investment_agent.platform.logging import get_logger
from investment_agent.platform.retry import network_retry

SP500_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

log = get_logger(__name__)

# User-Agent: 접속자 신원 (없으면 차단될 수 있음)
_HEADERS = {
    "User-Agent": "investment-agent/1.0 (+https://github.com/parkshinyoung0831/investment-agent)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

_HISTORICAL_COMPONENTS_URL = (
    "https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500"
)

# 종목코드가 아닌 빈 값·플레이스홀더 (걸러냄)
_INVALID_TICKERS = {"", "NAN", "NONE", "TBA", "TBD", "—", "-", "N/A"}


@lru_cache(maxsize=1)
@network_retry()
def _fetch_html() -> str:
    """위키 S&P 500 페이지 HTML 다운로드. 실행당 1회만 호출(캐싱)."""
    r = requests.get(SP500_WIKI_URL, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


@lru_cache(maxsize=1)
@network_retry()
def _fetch_changes_html() -> str:
    """2026-08에 본문에서 분리된 historical components 문서를 받는다."""
    r = requests.get(_HISTORICAL_COMPONENTS_URL, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def fetch_current_members() -> pd.DataFrame:
    """현재 S&P 500 종목 목록(~503개): ticker + name(영문명 fallback).
    컬럼 이름으로 올바른 표 선택(표 위치 바뀌어도 동작). 종목 수가 비정상이면 오류(예상 ~503개).
    영문명은 SEC(edgar)가 전 종목을 채우지만, 거래소 마스터에 없는 멤버(SEC exchange JSON 누락)는
    INSERT 시 name이 필요하므로 위키 Security를 fallback으로 함께 받는다. 섹터·CIK는 위키에서 안 읽음."""
    tables = pd.read_html(StringIO(_fetch_html()))
    candidates = [
        df for df in tables
        if {"Symbol", "Security", "GICS Sector"}.issubset(df.columns)
    ]
    if not candidates:
        raise RuntimeError("Wikipedia 스키마 변경: 현재 멤버 표를 찾지 못함")
    df = max(candidates, key=len)

    out = pd.DataFrame({
        "ticker": df["Symbol"].map(norm_ticker),
        "name":   df["Security"].astype(str).str.strip(),
        # historical components의 당시 ticker를 현재 canonical ticker와 안전하게
        # 연결할 때 회사명만으로는 부족하므로 최초 편입일도 함께 보존한다.
        "date_added": pd.to_datetime(df["Date added"], errors="coerce").dt.date,
    })
    out = out[~out["ticker"].isin(_INVALID_TICKERS)]
    out = out.drop_duplicates(subset=["ticker"]).reset_index(drop=True)

    # 안전 점검: 450~520 범위 벗어나면 잘못 읽은 것으로 보고 중단
    if not (450 <= len(out) <= 520):
        raise RuntimeError(f"current members 행 수 이상: {len(out)} (예상 ~503)")
    log.info("  current members: %d", len(out))
    return out


_CHANGES_COLUMNS = ("change_date", "ticker", "action", "name")


def _flatten_columns(columns) -> list[str]:
    """2단 컬럼 제목을 'Added.Ticker'처럼 한 줄로 평탄화."""
    return [".".join(s for s in col if s and "Unnamed" not in str(s)).strip(".")
            if isinstance(col, tuple) else str(col)
            for col in columns]


def fetch_selected_changes() -> pd.DataFrame:
    """편입/탈락 기록을 한 줄씩 정리(날짜·종목코드·구분·회사명). 회사명은 과거 멤버 이름 보충용.

    위키는 이 표의 위치를 바꾸거나 문서에서 통째로 내리기도 한다. 그래서 표 순번이
    아니라 컬럼 이름으로 찾고, 어느 표에도 없으면 경고만 남기고 빈 결과를 돌려준다.
    현재 멤버 표와 달리 이 기록은 과거 멤버 이름을 채우는 부가 정보라, 없다고 월간
    갱신 전체를 막으면 안 된다(현재 멤버 반영은 그대로 진행돼야 한다).
    """
    raw = None
    for table in pd.read_html(StringIO(_fetch_changes_html())):
        table = table.copy()
        table.columns = _flatten_columns(table.columns)
        cols = list(table.columns)
        if (
            any("Date" in c and "Ticker" not in c for c in cols)
            and any("Added" in c and "Ticker" in c for c in cols)
            and any("Removed" in c and "Ticker" in c for c in cols)
        ):
            raw = table
            break
    if raw is None:
        log.warning("  selected changes 표 없음 — 과거 멤버 이름 보충 생략")
        return pd.DataFrame(columns=list(_CHANGES_COLUMNS))

    date_col = next(c for c in raw.columns if "Date" in c and "Ticker" not in c)
    add_t    = next(c for c in raw.columns if "Added"   in c and "Ticker"   in c)
    add_s    = next((c for c in raw.columns if "Added"   in c and "Security" in c), None)
    rm_t     = next(c for c in raw.columns if "Removed" in c and "Ticker"   in c)
    rm_s     = next((c for c in raw.columns if "Removed" in c and "Security" in c), None)
    rows = []
    for _, r in raw.iterrows():
        d = pd.to_datetime(r[date_col], errors="coerce")
        if pd.isna(d):
            continue
        d = d.date()
        for action, t_col, s_col in (("added", add_t, add_s), ("removed", rm_t, rm_s)):
            t = norm_ticker(r[t_col])
            if not t or t in _INVALID_TICKERS:
                continue
            nm = r.get(s_col) if s_col else None
            name = str(nm).strip() if (nm is not None and not pd.isna(nm)) else ""
            rows.append({"change_date": d, "ticker": t, "action": action, "name": name or t})
    log.info(f"  selected changes: {len(rows)}")
    return pd.DataFrame(rows, columns=list(_CHANGES_COLUMNS))
