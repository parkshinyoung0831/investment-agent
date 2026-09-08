"""거장 PNG 카드의 결정적 뷰 모델을 만든다."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from investment_agent.data.institutional.domain.managers import blind_spot_caveat
from . import format as fmt
from .palette import TOKENS

_CHANGE_LABEL = {
    "new": "신규",
    "increase": "확대",
    "decrease": "축소",
    "exit": "청산",
    "hold": "유지",
}

# 13F 자산 종류 라벨. 옵션·전환사채(PRN)를 주식과 구분해 표기한다.
_INSTRUMENT_LABEL = {
    "equity": "주식",
    "call": "콜옵션",
    "put": "풋옵션",
    "principal": "채권성(PRN)",
}


def _instrument_rows(breakdown: dict | None) -> list[dict]:
    """13F 보고 노출 구성(Equity/CALL/PUT/PRN)을 카드용 행으로 만든다.

    각 항목의 비중은 '13F 보고가치' 합 대비다(전체 포트폴리오가 아님).
    """
    breakdown = breakdown or {}
    total = sum(
        fmt.number((breakdown.get(key) or {}).get("value_usd"))
        for key in ("equity", "call", "put", "principal")
    )
    rows = []
    for key in ("equity", "call", "put", "principal"):
        bucket = breakdown.get(key) or {}
        count = int(bucket.get("count") or 0)
        if count <= 0:
            continue
        value = fmt.number(bucket.get("value_usd"))
        share = (value / total) if total else 0
        rows.append(
            {
                "key": key,
                "label": _INSTRUMENT_LABEL[key],
                "value": fmt.money(bucket.get("value_usd")),
                "count": count,
                "pct": fmt.pct(share),
                "width": round(min(share * 100, 100), 1),
            }
        )
    return rows


def _latest_period(data: dict[str, list[dict]]) -> str:
    active_ciks = {
        str(row["manager_cik"])
        for row in data["managers"]
        if row.get("is_active", True)
    }
    periods = [
        str(row.get("period_end") or "")
        for row in data["filings"]
        if str(row.get("manager_cik") or "") in active_ciks
    ]
    if not periods:
        raise RuntimeError("gurus filings is empty")
    return max(periods)


def _latest_filings(data: dict[str, list[dict]], period: str) -> list[dict]:
    managers = {
        row["manager_cik"]: row
        for row in data["managers"]
        if row.get("is_active", True)
    }
    best: dict[str, dict] = {}
    for row in data["filings"]:
        if str(row.get("period_end")) != period:
            continue
        manager_cik = row["manager_cik"]
        if manager_cik not in managers:
            continue
        key = (str(row.get("filing_date") or ""), str(row.get("accepted_at") or ""))
        old = best.get(manager_cik)
        if old is None or key > old["_sort"]:
            best[manager_cik] = {**row, "_sort": key}
    out = []
    for manager_cik, row in best.items():
        manager = managers.get(manager_cik, {})
        out.append({**row, **manager})
    return sorted(out, key=lambda x: x.get("name") or "")


def _manager_labels(data: dict[str, list[dict]]) -> dict[str, str]:
    return {
        str(row["name"]): str(row.get("name_ko") or row["name"])
        for row in data["managers"]
    }


def _security_labels(data: dict[str, list[dict]]) -> dict[str, dict]:
    return {
        str(row["ticker"]): {
            "name_en": str(row.get("name") or ""),
            "name_ko": str(row.get("name_ko") or row.get("name") or ""),
        }
        for row in data.get("tickers", [])
    }


def _security_names(ticker: str, labels: dict[str, dict]) -> tuple[str, str]:
    """(한글명, 영문명). 영문명은 한글명과 다를 때만 채워 중복 표기를 막는다."""
    label = labels.get(ticker, {})
    name_ko = str(label.get("name_ko") or "")
    name_en = str(label.get("name_en") or "")
    return name_ko, ("" if name_en == name_ko else name_en)


def _signal_rows(
    rows: list[dict],
    manager_labels: dict[str, str],
    security_labels: dict[str, dict],
    *,
    min_managers: int = 2,
    limit: int = 3,
) -> list[dict]:
    filtered = [r for r in rows if int(r.get("manager_count") or 0) >= min_managers]
    filtered.sort(
        key=lambda r: (
            int(r.get("manager_count") or 0),
            fmt.number(r.get("conviction_score")),
        ),
        reverse=True,
    )
    top = filtered[:limit]
    scale = max((fmt.number(r.get("conviction_score")) for r in top), default=1) or 1
    result = []
    for rank, row in enumerate(top, start=1):
        score = fmt.number(row.get("conviction_score"))
        ticker = row.get("ticker") or row.get("cusip") or "UNKNOWN"
        name_ko, name_en = _security_names(str(ticker), security_labels)
        result.append(
            {
                **row,
                "rank": rank,
                "ticker": ticker,
                "company_name": name_ko,
                "company_name_en": name_en,
                "manager_count": int(row.get("manager_count") or 0),
                "score_label": fmt.pct(score),
                "bar_width": round(max(10, score / scale * 100), 1),
                "manager_badges": [
                    {
                        "name": manager_labels.get(str(name), str(name)),
                        "initials": fmt.initials(str(name)),
                    }
                    for name in row.get("managers") or []
                ],
            }
        )
    return result


def _conflicts(
    buys: list[dict],
    sells: list[dict],
    manager_labels: dict[str, str],
    security_labels: dict[str, dict],
    limit: int = 5,
) -> list[dict]:
    buy_map = {r.get("ticker"): r for r in buys if r.get("ticker")}
    sell_map = {r.get("ticker"): r for r in sells if r.get("ticker")}
    rows = []
    for ticker in set(buy_map) & set(sell_map):
        buy = buy_map[ticker]
        sell = sell_map[ticker]
        buy_score = fmt.number(buy.get("conviction_score"))
        sell_score = fmt.number(sell.get("conviction_score"))
        total = buy_score + sell_score or 1
        name_ko, name_en = _security_names(str(ticker), security_labels)
        rows.append(
            {
                "ticker": ticker,
                "company_name": name_ko,
                "company_name_en": name_en,
                "buy_names": [
                    manager_labels.get(str(name), str(name))
                    for name in buy.get("managers") or []
                ],
                "sell_names": [
                    manager_labels.get(str(name), str(name))
                    for name in sell.get("managers") or []
                ],
                "buy_count": int(buy.get("manager_count") or 0),
                "sell_count": int(sell.get("manager_count") or 0),
                "buy_width": round(buy_score / total * 100, 1),
                "sell_width": round(sell_score / total * 100, 1),
                "buy_score": fmt.pct(buy_score),
                "sell_score": fmt.pct(sell_score),
                "_importance": max(
                    int(buy.get("manager_count") or 0),
                    int(sell.get("manager_count") or 0),
                )
                * 10
                + total,
            }
        )
    rows.sort(key=lambda r: r["_importance"], reverse=True)
    return rows[:limit]


def _activity_rows(changes: list[dict], filings: list[dict]) -> list[dict]:
    filing_by_cik = {r["manager_cik"]: r for r in filings}
    by_manager: dict[str, list[dict]] = {}
    for row in changes:
        if row.get("put_call") != "SH":
            continue
        by_manager.setdefault(row["manager_cik"], []).append(row)

    result = []
    for manager_cik, rows in by_manager.items():
        counts = Counter(r.get("change_type") for r in rows)
        changed = sum(counts[k] for k in ("new", "increase", "decrease", "exit"))
        filing = filing_by_cik.get(manager_cik, {})
        result.append(
            {
                "name": filing.get("name_ko") or rows[0]["manager"],
                "name_en": rows[0]["manager"],
                "fund_name": filing.get("fund_name_ko") or rows[0]["fund_name"],
                "initials": fmt.initials(rows[0]["manager"]),
                "aum": fmt.money(filing.get("portfolio_value_usd")),
                "holding_count": int(filing.get("position_count") or 0),
                "changed": changed,
                "total": len(rows),
                "change_rate": round(changed / len(rows) * 100) if rows else 0,
                "new": counts["new"],
                "increase": counts["increase"],
                "decrease": counts["decrease"],
                "exit": counts["exit"],
            }
        )
    result.sort(key=lambda r: (r["change_rate"], r["changed"]), reverse=True)
    max_changed = max((r["changed"] for r in result), default=1)
    for row in result:
        total = row["changed"] or 1
        row["width"] = round(row["changed"] / max_changed * 100, 1)
        for key in ("new", "increase", "decrease", "exit"):
            row[f"{key}_width"] = round(row[key] / total * 100, 1)
    return result


def _radar_status(manager_groups: list[dict], filed_ciks: set) -> list[dict]:
    """7인 레이더 상태판: signal_role 그룹별 제출(filed)/전체 수와 멤버 상태."""
    board = []
    for group in manager_groups:
        members = group.get("managers", [])
        rows = [
            {
                "name": m.get("name"),
                "filed": str(m.get("manager_cik")) in filed_ciks,
            }
            for m in members
        ]
        board.append(
            {
                "signal_role": group["signal_role"],
                "label": group["label"],
                "filed": sum(1 for r in rows if r["filed"]),
                "total": len(members),
                "managers": rows,
            }
        )
    return board


def _co_held(
    holdings: list[dict],
    period: str,
    security_labels: dict[str, dict],
    *,
    limit: int = 6,
    min_managers: int = 2,
) -> list[dict]:
    """공동 보유 TOP: 최신 분기 13F Long Equity를 2명 이상 보유한 종목."""
    holders: dict[str, set] = defaultdict(set)
    weight_sum: dict[str, float] = defaultdict(float)
    for h in holdings:
        if str(h.get("period_end")) != period:
            continue
        key = str(h.get("ticker") or h.get("cusip"))
        holders[key].add(str(h.get("manager_cik")))
        weight_sum[key] += float(h.get("pct_of_13f_long_equity") or 0)
    rows = []
    for key, ciks in holders.items():
        if len(ciks) < min_managers:
            continue
        name_ko, name_en = _security_names(key, security_labels)
        rows.append(
            {
                "ticker": key,
                "company_name": name_ko,
                "company_name_en": name_en,
                "manager_count": len(ciks),
                "avg_weight": fmt.pct(weight_sum[key] / len(ciks)),
            }
        )
    rows.sort(key=lambda r: (r["manager_count"], r["ticker"]), reverse=True)
    return rows[:limit]


def build_quarterly(data: dict[str, list[dict]]) -> dict:
    period = _latest_period(data)
    filings = _latest_filings(data, period)
    active = [m for m in data["managers"] if m.get("is_active")]
    changes = [
        r for r in data["changes"]
        if str(r.get("period_end")) == period
    ]
    buys = [
        r for r in data["buys"]
        if str(r.get("period_end")) == period
    ]
    sells = [
        r for r in data["sells"]
        if str(r.get("period_end")) == period
    ]
    manager_labels = _manager_labels(data)
    security_labels = _security_labels(data)
    consensus_buys = _signal_rows(
        buys,
        manager_labels,
        security_labels,
    )
    consensus_sells = _signal_rows(
        sells,
        manager_labels,
        security_labels,
    )
    conflicts = _conflicts(
        buys,
        sells,
        manager_labels,
        security_labels,
    )
    filed_ciks = {row["manager_cik"] for row in filings}
    missing_names = sorted(
        str(row.get("name_ko") or row["name"])
        for row in active
        if row["manager_cik"] not in filed_ciks
    )
    buy_signal_total = sum(
        int(row.get("manager_count") or 0) >= 2 for row in buys
    )
    sell_signal_total = sum(
        int(row.get("manager_count") or 0) >= 2 for row in sells
    )
    radar_status = _radar_status(data.get("manager_groups", []), filed_ciks)
    co_held = _co_held(data.get("holdings", []), period, security_labels)

    return {
        "tokens": TOKENS,
        "period": period,
        "quarter": fmt.quarter(period),
        "generated_on": datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat(),
        "radar_status": radar_status,
        "co_held": co_held,
        "filed_count": len(filings),
        "active_count": len(active),
        "completion_pct": round(len(filings) / len(active) * 100) if active else 0,
        "latest_filing_date": max(
            (str(r.get("filing_date") or "") for r in filings),
            default="",
        ),
        "provisional": bool(missing_names),
        "missing_names": missing_names,
        "buy_signal_total": buy_signal_total,
        "sell_signal_total": sell_signal_total,
        "consensus_count": buy_signal_total + sell_signal_total,
        "conflict_count": len(conflicts),
        "material_move_count": sum(
            1 for r in changes if r.get("change_type") != "hold"
        ),
        "buys": consensus_buys,
        "sells": consensus_sells,
        "conflicts": conflicts,
        "activities": _activity_rows(changes, filings),
    }


# 변화 목록에 세울 최소 크기. 1%/20%로 두면 회전이 적은 운용사(버크셔·TCI)는 칸이 통째로
# 비었다. 0.5%/10%면 대부분 채워지고, 많은 쪽은 표시 개수 제한이 대신 잘라 준다.
_MIN_WEIGHT = 0.005        # 편입 비중 하한
_MIN_SHARE_DELTA = 0.10    # 주식 수 변동 하한


def _material_changes(
    rows: list[dict],
    kind: str,
    security_labels: dict[str, dict],
    limit: int = 5,
) -> list[dict]:
    candidates = []
    for row in rows:
        if row.get("change_type") != kind:
            continue
        curr = fmt.number(row.get("pct_of_13f_long_equity"))
        prev = fmt.number(row.get("prev_pct_long_equity"))
        delta = fmt.share_delta(row)
        if kind == "new" and curr < _MIN_WEIGHT:
            continue
        if kind == "exit" and prev < _MIN_WEIGHT:
            continue
        if kind in ("increase", "decrease"):
            if max(curr, prev) < _MIN_WEIGHT:
                continue
            if delta is None or abs(delta) < _MIN_SHARE_DELTA:
                continue
        candidates.append(row)

    def importance(row: dict) -> float:
        return max(
            fmt.number(row.get("pct_of_13f_long_equity")),
            fmt.number(row.get("prev_pct_long_equity")),
        )

    candidates.sort(key=importance, reverse=True)
    out = []
    for row in candidates[:limit]:
        curr = fmt.number(row.get("pct_of_13f_long_equity"))
        prev = fmt.number(row.get("prev_pct_long_equity"))
        delta = fmt.share_delta(row)
        ticker = row.get("ticker") or row.get("cusip") or "UNKNOWN"
        name_ko, name_en = _security_names(str(ticker), security_labels)
        out.append(
            {
                "ticker": ticker,
                "company_name": name_ko,
                "company_name_en": name_en,
                "kind": kind,
                "kind_label": _CHANGE_LABEL[kind],
                "prev_pct": fmt.pct(prev),
                "curr_pct": fmt.pct(curr),
                "prev_width": round(min(prev * 400, 100), 1),
                "curr_width": round(min(curr * 400, 100), 1),
                "share_delta": (
                    "신규" if kind == "new"
                    else "전량" if kind == "exit"
                    else fmt.signed_pct(delta) if delta is not None
                    else "—"
                ),
                "weight_delta": fmt.percentage_point(curr, prev),
            }
        )
    return out


def _top_holdings(
    rows: list[dict],
    security_labels: dict[str, dict],
    limit: int = 5,
) -> list[dict]:
    current = [row for row in rows if row.get("shares") is not None]
    current.sort(
        key=lambda row: fmt.number(row.get("pct_of_13f_long_equity")),
        reverse=True,
    )
    scale = max(
        (fmt.number(row.get("pct_of_13f_long_equity")) for row in current[:limit]),
        default=1,
    ) or 1
    result = []
    for rank, row in enumerate(current[:limit], start=1):
        curr = fmt.number(row.get("pct_of_13f_long_equity"))
        prev = fmt.number(row.get("prev_pct_long_equity"))
        ticker = row.get("ticker") or row.get("cusip") or "UNKNOWN"
        name_ko, name_en = _security_names(str(ticker), security_labels)
        result.append(
            {
                "rank": rank,
                "ticker": ticker,
                "company_name": name_ko,
                "company_name_en": name_en,
                "weight": fmt.pct(curr),
                "weight_delta": fmt.percentage_point(curr, prev),
                "bar_width": round(curr / scale * 100, 1),
            }
        )
    return result


def build_filing(
    data: dict[str, list[dict]],
    manager_name: str | None = None,
    *,
    holdings_limit: int = 5,
    changes_limit: int = 5,
) -> dict:
    period = _latest_period(data)
    filings = _latest_filings(data, period)
    if not filings:
        raise RuntimeError(f"no filings for {period}")
    if manager_name is None:
        filing = filings[0]
    else:
        filing = next(
            (r for r in filings if r.get("name") == manager_name), None
        )
        if filing is None:
            # fallback 금지: 못 찾으면 다른 운용사 카드로 대체하지 않고 에러.
            raise RuntimeError(
                f"manager not found in {period} filings: {manager_name!r}"
            )
    rows = [
        r for r in data["changes"]
        if r.get("manager_cik") == filing["manager_cik"]
        and str(r.get("period_end")) == period
        and r.get("put_call") == "SH"
    ]
    counts = Counter(r.get("change_type") for r in rows)
    security_labels = _security_labels(data)
    sections = [
        {
            "kind": kind,
            "label": _CHANGE_LABEL[kind],
            "rows": _material_changes(rows, kind, security_labels, changes_limit),
        }
        for kind in ("new", "increase", "decrease", "exit")
    ]
    sections = [s for s in sections if s["rows"]]
    top_holdings = _top_holdings(rows, security_labels, holdings_limit)
    # 상위 보유 + 기타 도넛(13F Long Equity 기준). 각 슬라이스는 long equity 비중.
    # '기타'는 실제로 그린 조각 수를 기준으로 뺀다 — top5로 고정하면 조각을 늘렸을 때
    # 합이 100%를 넘는다.
    shown_weight = sum(
        fmt.number(row.get("pct_of_13f_long_equity"))
        for row in sorted(
            (row for row in rows if row.get("shares") is not None),
            key=lambda row: fmt.number(row.get("pct_of_13f_long_equity")),
            reverse=True,
        )[:holdings_limit]
    )
    donut = [
        {"label": h["ticker"], "pct": h["weight"], "value": float(
            fmt.number(
                next(
                    (r.get("pct_of_13f_long_equity") for r in rows
                     if (r.get("ticker") or r.get("cusip")) == h["ticker"]),
                    0,
                )
            )
        )}
        for h in top_holdings
    ]
    other_weight = max(0.0, 1.0 - float(shown_weight))
    if other_weight > 0.0001:
        donut.append({"label": "기타", "pct": fmt.pct(other_weight),
                      "value": round(other_weight, 6)})
    changed_count = sum(
        counts[kind] for kind in ("new", "increase", "decrease", "exit")
    )
    shown_count = sum(len(section["rows"]) for section in sections)
    top5_concentration = sum(
        fmt.number(row.get("pct_of_13f_long_equity"))
        for row in sorted(
            (row for row in rows if row.get("shares") is not None),
            key=lambda row: fmt.number(row.get("pct_of_13f_long_equity")),
            reverse=True,
        )[:5]
    )
    coverage_status = str(filing.get("coverage_status") or "unknown")
    coverage_warning = coverage_status != "full"
    coverage_notes = {
        "notice": "보유 전량이 타 운용사 공시에 포함",
        "partial": "일부 보유가 타 운용사 공시에 포함",
        "confidential": "일부 보유 비공개",
        "unknown": "공시 범위 확인 필요",
    }
    return {
        "tokens": TOKENS,
        "quarter": fmt.quarter(period),
        "period": period,
        "name": filing.get("name_ko") or filing["name"],
        "name_en": filing["name"],
        "fund_name": filing.get("fund_name_ko") or filing["fund_name"],
        "fund_name_en": filing["fund_name"],
        "initials": fmt.initials(filing["name"]),
        "filing_date": filing.get("filing_date"),
        "accession_no": filing.get("accession_no"),
        "manager_cik": filing.get("manager_cik"),
        "aum": fmt.money(filing.get("portfolio_value_usd")),
        "reported_13f_value": fmt.money(filing.get("reported_13f_value_usd")),
        "long_equity_value": fmt.money(filing.get("long_equity_value_usd")),
        "long_equity_count": int(filing.get("long_equity_count") or 0),
        "holding_count": int(filing.get("position_count") or 0),
        "position_count": int(filing.get("equity_position_count") or 0),
        "confidential_omitted": bool(filing.get("confidential_omitted")),
        "coverage_warning": coverage_warning,
        "coverage_note": (
            coverage_notes.get(coverage_status, "SEC 보고 기준")
        ),
        "signal_role": filing.get("signal_role"),
        "blind_spot_caveat": blind_spot_caveat(filing.get("blind_spots")),
        "instruments": _instrument_rows(filing.get("instrument_breakdown")),
        "changed_count": changed_count,
        "comparable_count": len(rows),
        "change_rate": round(changed_count / len(rows) * 100) if rows else 0,
        "shown_count": shown_count,
        "top5_concentration": fmt.pct(top5_concentration),
        "largest_holding": top_holdings[0] if top_holdings else None,
        "top_holdings": top_holdings,
        "donut": donut,
        "source_url": filing.get("source_url") or "",
        "counts": {
            "new": counts["new"],
            "increase": counts["increase"],
            "decrease": counts["decrease"],
            "exit": counts["exit"],
        },
        "sections": sections,
    }
