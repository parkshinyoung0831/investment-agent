"""S&P500 원천 데이터의 표준화와 PIT snapshot 계산."""
from __future__ import annotations

import hashlib
import json
import re

import pandas as pd

from investment_agent.platform.logging import get_logger

log = get_logger(__name__)
_CANONICAL_TICKER = re.compile(r"^[A-Z0-9-]{1,12}$")


def norm_ticker(t) -> str:
    """종목코드 표기 통일. 예: 'BRK.B' → 'BRK-B'. 빈 값도 안전 처리."""
    if t is None or (isinstance(t, float) and pd.isna(t)):
        return ""
    return str(t).strip().upper().replace(".", "-")


def sic_division(sic_code) -> str | None:
    """4자리 SIC 코드 → 대분류(division) 명. SIC 표준 11개 대분류(10 division + 미분류).
    세부 분류(sicDescription)와 함께 상위 묶음으로 그룹핑할 때 쓴다. 매핑 안 되면 None.
    경계: https://www.sec.gov/corpfin/division-of-corporation-finance-standard-industrial-classification-sic-code-list 참고."""
    try:
        n = int(str(sic_code).strip())
    except (TypeError, ValueError):
        return None
    if    100 <= n <=  999: return "Agriculture, Forestry & Fishing"
    if   1000 <= n <= 1499: return "Mining"
    if   1500 <= n <= 1799: return "Construction"



    if   2000 <= n <= 3999: return "Manufacturing"
    if   4000 <= n <= 4999: return "Transportation & Public Utilities"
    if   5000 <= n <= 5199: return "Wholesale Trade"
    if   5200 <= n <= 5999: return "Retail Trade"
    if   6000 <= n <= 6799: return "Finance, Insurance & Real Estate"
    if   7000 <= n <= 8999: return "Services"
    if   9100 <= n <= 9729: return "Public Administration"
    if   9900 <= n <= 9999: return "Nonclassifiable"
    return None


def classify_security_type(
    security_title: str | None = None,
    ticker: str = "",
    *,
    is_etf: bool = False,
) -> str:
    """Classify security into data-driven security types.

    Allowed types: common_stock, preferred_stock, depositary_share, warrant, unit,
    note, etn, etf, right, other.
    """
    title = str(security_title or "").casefold()
    symbol = str(ticker or "").strip().upper()

    if is_etf:
        return "etf"
    if re.search(r"\b(preferred|preference|pfd|pref)\b", title):
        return "preferred_stock"
    if "depositary" in title or re.search(r"\b(ads|adr)\b", title):
        return "depositary_share"
    if re.search(r"\b(warrant|warrants|wt|wts)\b", title):
        return "warrant"
    if re.search(r"\b(units?)\b", title):
        return "unit"
    if "etn" in title or "exchange traded note" in title:
        return "etn"
    if re.search(r"\b(notes?|debentures?|bonds?|zones)\b", title):
        return "note"
    if re.search(r"\b(rights?)\b", title):
        return "right"

    # Ticker pattern fallbacks
    if "-P" in symbol or ".PR" in symbol:
        return "preferred_stock"
    if "-W" in symbol or ".WS" in symbol:
        return "warrant"
    if "-U" in symbol or ".UN" in symbol:
        return "unit"
    if "-R" in symbol:
        return "right"

    return "common_stock"



def build_reconcile_rows(members_df: pd.DataFrame, changes_df) -> dict:
    """현재 멤버 표 + 편입/탈락 기록 → 저장용 목록을 생성한다.
    반환:
      current_rows : 현재 S&P 500 종목 (~503개, is_tracked=True)
      past_rows    : 과거 멤버 ticker 행(is_tracked는 의도적으로 생략)
      current_set  : 현재 멤버 종목코드 집합
    """
    current_set = set(members_df["ticker"])

    # 현재 멤버는 최종 수집 게이트를 연다. 회사 정보는 CIK entity가 보유한다.
    current_rows = [
        {"ticker": r["ticker"], "is_tracked": True}
        for _, r in members_df.iterrows()
    ]

    # 탈락 기록 정리(과거 멤버 식별 + 회사명 보충용)
    removed_map: dict[str, str] = {}
    if changes_df is not None and not changes_df.empty:
        df = changes_df.copy()
        df["change_date"] = pd.to_datetime(df["change_date"]).dt.date.astype(str)
        for t, sub in df.groupby("ticker"):
            rms = sub[sub["action"] == "removed"]
            if len(rms):
                removed_map[t] = rms["change_date"].max()

    # 과거 멤버는 신규 ticker를 보존하되 기존 tracked 상태는 건드리지 않는다.
    past_rows = [
        {"ticker": t}
        for t in removed_map
        if t not in current_set and _CANONICAL_TICKER.fullmatch(t)
    ]

    return {
        "current_rows": current_rows,
        "past_rows": past_rows,
        "current_set": current_set,
    }

def build_membership_snapshots(
    members_df: pd.DataFrame,
    changes_df: pd.DataFrame,
) -> list[dict]:
    """현재 명단에서 변경 이력을 역재생해 날짜별 S&P 500 명단을 복원한다.

    가장 오래된 변경일 이전은 알 수 없으므로 행을 만들지 않는다. 백테스트는 이
    테이블보다 앞선 날짜를 요청할 때 반드시 실패해야 한다.
    """
    if changes_df is None or changes_df.empty:
        return []
    required = {"change_date", "ticker", "action"}
    if not required <= set(changes_df.columns):
        raise ValueError("S&P 500 changes are missing required columns")
    current = {norm_ticker(value) for value in members_df["ticker"]}
    current.discard("")
    if not 450 <= len(current) <= 520:
        raise ValueError("current S&P 500 membership count is outside the safety range")
    changes = changes_df.copy()
    changes["ticker"] = changes["ticker"].map(norm_ticker)
    changes["change_date"] = pd.to_datetime(changes["change_date"], errors="raise").dt.date
    if changes["ticker"].eq("").any() or not set(changes["action"]) <= {"added", "removed"}:
        raise ValueError("S&P 500 change history contains an invalid ticker or action")
    duplicate = changes.duplicated(subset=["change_date", "ticker", "action"])
    if duplicate.any():
        raise ValueError("S&P 500 change history contains duplicate events")
    # 구성종목 자격은 유지된 채 ticker만 바뀐 경우 historical 표에는 당시 ticker만
    # 남는다. 동일 회사명이 현재 표에서 유일하게 매칭되는 편입 행은 현재 canonical
    # ticker로 연결해 같은 증권을 두 종목으로 오인하지 않는다.
    if (
        "name" in members_df.columns
        and "date_added" in members_df.columns
        and "name" in changes.columns
    ):
        def name_key(value) -> str:
            return "".join(character for character in str(value).casefold() if character.isalnum())

        name_candidates: dict[tuple[str, object], list[str]] = {}
        for _, row in members_df.iterrows():
            key = name_key(row.get("name"))
            added = row.get("date_added")
            if key and not pd.isna(added):
                name_candidates.setdefault(
                    (key, pd.to_datetime(added).date()), []
                ).append(norm_ticker(row.get("ticker")))
        unique_names = {
            key: values[0]
            for key, values in name_candidates.items()
            if len(set(values)) == 1
        }
        # 사명까지 함께 바뀐 경우(Everest Re -> Everest Group)엔 이름이 정확히 맞지
        # 않는다. 편입일은 ticker·사명이 바뀌어도 남으므로 후보를 그 날짜로 좁힌 뒤
        # 사명 토큰이 겹치는 하나만 같은 증권으로 본다. 날짜만으로 고르면 같은 날
        # 편입된 무관한 종목까지 끌어온다.
        def name_tokens(value) -> set[str]:
            return {
                token
                for token in str(value).casefold().replace(".", " ").replace(",", " ").split()
                if len(token) >= 4
            }

        date_candidates: dict[object, list[tuple[str, set[str]]]] = {}
        for _, row in members_df.iterrows():
            added = row.get("date_added")
            if pd.isna(added):
                continue
            date_candidates.setdefault(pd.to_datetime(added).date(), []).append(
                (norm_ticker(row.get("ticker")), name_tokens(row.get("name")))
            )

        historical_tickers = set(changes["ticker"])
        for index, row in changes.iterrows():
            if row["action"] != "added" or row["ticker"] in current:
                continue
            canonical = unique_names.get((name_key(row.get("name")), row["change_date"]))
            if not canonical:
                wanted = name_tokens(row.get("name"))
                same_day = {
                    ticker
                    for ticker, tokens in date_candidates.get(row["change_date"], [])
                    if ticker not in historical_tickers and (tokens & wanted)
                }
                if len(same_day) == 1:
                    canonical = next(iter(same_day))
            # 새 ticker 자체가 변경 이력에 있으면 명시적 rename/add/remove 이벤트가
            # 있으므로 당시 ticker를 그대로 보존한다.
            if canonical and canonical not in historical_tickers:
                changes.at[index, "ticker"] = canonical
    snapshots: list[dict] = []
    ticker_identity_cutoff = False
    for effective_date in sorted(changes["change_date"].unique(), reverse=True):
        symbols = sorted(current)
        if not 450 <= len(symbols) <= 520:
            raise ValueError(
                f"historical S&P 500 membership count is unsafe on {effective_date}: {len(symbols)}"
            )
        digest = hashlib.sha256(
            json.dumps(symbols, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        snapshots.append({
            "effective_date": effective_date.isoformat(),
            "symbols": symbols,
            "member_count": len(symbols),
            "source": "wikipedia_selected_changes_ticker_safe_window",
            "source_hash": digest,
        })
        day = changes[changes["change_date"] == effective_date]
        # 해당 날짜 직전 상태로 되돌린다: 편입은 제거하고 탈락은 복원한다.
        for ticker in day.loc[day["action"] == "added", "ticker"]:
            if ticker not in current:
                # 무료 자료로는 개명 이력이 늘 남지 않는다. 가장 최근 변경일부터
                # 어긋나면 복원이 한 칸도 되지 않은 것이므로 자료가 깨졌다고 보고
                # 닫는다. 이미 되돌린 구간이 있으면 그 지점까지만 남긴다 — 틀린
                # 명단을 만드는 것보다 짧은 편이 낫다.
                if len(snapshots) <= 1:
                    raise ValueError(
                        f"cannot reverse S&P 500 addition for absent ticker {ticker}"
                        f" on {effective_date}"
                    )
                log.warning(
                    "S&P 500 이력 복원 중단: %s 편입을 %s 시점에서 되돌릴 수 없음"
                    " (개명 이력 누락) — 이 날짜 이후만 남긴다",
                    ticker,
                    effective_date,
                )
                ticker_identity_cutoff = True
                break
            current.remove(ticker)
        if ticker_identity_cutoff:
            break
        for ticker in day.loc[day["action"] == "removed", "ticker"]:
            if ticker in current:
                # 같은 ticker가 다른 법인에 재사용된 경계다. ticker만 있는 무료
                # 자료로 그 이전을 안전하게 식별할 수 없으므로 이 날짜 snapshot까지만
                # 남기고 더 과거 복원은 중단한다.
                ticker_identity_cutoff = True
                break
            current.add(ticker)
        if ticker_identity_cutoff:
            break
    return list(reversed(snapshots))
