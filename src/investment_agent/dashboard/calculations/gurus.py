"""대시보드 13F 구루 포트폴리오·지분 변화 계산."""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from investment_agent.dashboard.calculations._common import (
    _records,
    finite_number,
)

def _cusip_mapping(value: Any) -> dict[str, str | None]:
    """CUSIP 매핑 응답을 CUSIP→대문자 ticker 사전으로 정규화한다."""
    if isinstance(value, Mapping):
        return {
            str(cusip): str(ticker).upper() if ticker is not None and str(ticker).strip() else None
            for cusip, ticker in value.items()
            if str(cusip).strip()
        }
    return {
        str(row["cusip"]): str(row["ticker"]).upper() if row.get("ticker") else None
        for row in _records(value)
        if row.get("cusip")
    }


def _long_equity_book(rows: Any) -> dict[str, dict[str, Any]] | None:
    """한 공시의 SH 단위 long-equity 행만 CUSIP별로 합산한다."""
    records = _records(rows)
    if not records:
        return None
    accessions = {str(row.get("accession_no")) for row in records if row.get("accession_no")}
    if len(accessions) > 1:
        return None
    book: dict[str, dict[str, Any]] = {}
    for row in records:
        if str(row.get("position_kind") or "").upper() != "SHARES":
            continue
        if str(row.get("quantity_type") or "").upper() != "SH":
            continue
        cusip = str(row.get("cusip") or "").strip()
        quantity = finite_number(row.get("quantity"))
        if not cusip or quantity is None or quantity < 0.0:
            continue
        current = book.setdefault(cusip, {"quantity": 0.0, "issuer_name": None, "value_usd": 0.0})
        current["quantity"] += quantity
        if row.get("issuer_name"):
            current["issuer_name"] = str(row["issuer_name"])
        value_usd = finite_number(row.get("value_usd"))
        if value_usd is not None:
            current["value_usd"] += value_usd
    return book or None


def guru_position_changes(
    current_rows: Iterable[Mapping[str, Any]] | pd.DataFrame,
    previous_rows: Iterable[Mapping[str, Any]] | pd.DataFrame,
    cusip_map: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    *,
    quantity_threshold: float = 0.10,
) -> list[dict[str, Any]]:
    """비교 가능한 두 13F의 long equity 수량 변화만 반환한다.

    양쪽 공시의 long equity 행이 모두 있어야 계산한다. 이전 미보유는 ``new``, 현재
    미보유는 ``exit``, 양쪽 보유는 수량 변화율이 ``±quantity_threshold`` 이상일 때만
    ``increase`` 또는 ``decrease``로 반환한다. PUT/CALL·PRN과 임계값 안쪽 변화는 제외한다.
    """
    threshold = finite_number(quantity_threshold)
    if threshold is None or threshold <= 0.0 or threshold >= 1.0:
        return []
    current = _long_equity_book(current_rows)
    previous = _long_equity_book(previous_rows)
    if current is None or previous is None:
        return []
    tickers = _cusip_mapping(cusip_map)
    output: list[dict[str, Any]] = []
    for cusip in sorted(set(current) | set(previous)):
        current_position = current.get(cusip)
        previous_position = previous.get(cusip)
        current_quantity = current_position["quantity"] if current_position is not None else None
        previous_quantity = previous_position["quantity"] if previous_position is not None else None
        change: str | None = None
        change_fraction: float | None = None
        quantity_change: float | None = None
        if previous_position is None and current_quantity is not None and current_quantity > 0.0:
            change = "new"
        elif current_position is None and previous_quantity is not None and previous_quantity > 0.0:
            change = "exit"
            change_fraction = -1.0
        elif (
            current_quantity is not None
            and previous_quantity is not None
            and previous_quantity > 0.0
        ):
            quantity_change = current_quantity - previous_quantity
            change_fraction = quantity_change / previous_quantity
            if current_quantity <= 0.0:
                change = "exit"
            elif change_fraction >= threshold:
                change = "increase"
            elif change_fraction <= -threshold:
                change = "decrease"
        if change is None:
            continue
        source = current_position or previous_position or {}
        output.append({
            "cusip": cusip,
            "ticker": tickers.get(cusip),
            "issuer_name": source.get("issuer_name"),
            "change": change,
            "current_quantity": current_quantity,
            "previous_quantity": previous_quantity,
            "quantity_change": quantity_change,
            "change_fraction": change_fraction,
            "current_value_usd": current_position.get("value_usd") if current_position else None,
            "previous_value_usd": previous_position.get("value_usd") if previous_position else None,
        })
    order = {"new": 0, "increase": 1, "decrease": 2, "exit": 3}
    return sorted(output, key=lambda row: (order[row["change"]], row.get("ticker") or row["cusip"]))


# ── 13F 포트폴리오 구성 ──────────────────────────────────────────────────
# 13F는 **long equity만** 담는다. 숏·파생·채권·해외·비상장은 애초에 들어오지 않으므로
# 여기서 만드는 비중은 '보고된 장부 안에서의 비중'이지 매니저 자산 전체의 비중이 아니다.


def guru_portfolio(
    positions: Iterable[Mapping[str, Any]] | pd.DataFrame,
    cusip_map: Mapping[str, Any] | Iterable[Mapping[str, Any]] | None = None,
    *,
    top_n: int = 12,
) -> dict[str, Any]:
    """한 공시의 long equity 보유를 금액 비중으로 정리한다.

    반환 키: ``holdings``(비중 내림차순 전체), ``top``(상위 top_n + 기타 집계),
    ``total_value``, ``position_count``, ``top5_share``, ``top10_share``,
    ``excluded``(금액을 못 읽어 비중에서 뺀 행 수).
    가치가 없는 행은 0으로 채우지 않고 비중 계산에서 제외한다.
    """
    book = _long_equity_book(positions)
    tickers = _cusip_mapping(cusip_map or {})
    blank: dict[str, Any] = {
        "holdings": [],
        "top": [],
        "total_value": None,
        "position_count": 0,
        "top5_share": None,
        "top10_share": None,
        "excluded": 0,
    }
    if not book:
        return blank

    raw_items: list[dict[str, Any]] = []
    excluded = 0
    for cusip, position in book.items():
        value = finite_number(position.get("value_usd"))
        if value is None or value <= 0.0:
            excluded += 1
            continue
        raw_items.append(
            {
                "cusip": cusip,
                "ticker": tickers.get(cusip),
                "issuer_name": position.get("issuer_name"),
                "value_usd": value,
                "quantity": finite_number(position.get("quantity")),
            }
        )
    if not raw_items:
        return {**blank, "position_count": len(book), "excluded": excluded}

    total = math.fsum(item["value_usd"] for item in raw_items)
    if total <= 0.0:
        return {**blank, "position_count": len(book), "excluded": excluded}

    # 동일 발행사(issuer_name) 또는 CUSIP 접두사 기준으로 기업 단위 그룹화
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in raw_items:
        issuer = str(item.get("issuer_name") or "").strip()
        if issuer:
            group_key = f"ISSUER:{issuer.upper()}"
        else:
            cusip = str(item.get("cusip") or "").strip()
            group_key = f"CUSIP:{cusip[:6].upper() if len(cusip) >= 6 else cusip.upper()}"
        groups.setdefault(group_key, []).append(item)

    rows: list[dict[str, Any]] = []
    for items in groups.values():
        items.sort(key=lambda x: -x["value_usd"])
        sum_value = math.fsum(x["value_usd"] for x in items)
        quantities = [x["quantity"] for x in items if x["quantity"] is not None]
        sum_qty = math.fsum(quantities) if quantities else None

        issuer_name = next((x["issuer_name"] for x in items if x.get("issuer_name")), None)

        seen_tickers: set[str] = set()
        ordered_tickers: list[str] = []
        for x in items:
            t = x.get("ticker")
            if t and t not in seen_tickers:
                seen_tickers.add(t)
                ordered_tickers.append(t)
        ticker_str = ", ".join(ordered_tickers) if ordered_tickers else None

        cusip_list = [x["cusip"] for x in items if x.get("cusip")]
        cusip_str = ", ".join(cusip_list) if cusip_list else None

        label = issuer_name or ticker_str or cusip_str or "—"

        sub_holdings = [
            {
                "cusip": x["cusip"],
                "ticker": x["ticker"],
                "issuer_name": x["issuer_name"],
                "value_usd": x["value_usd"],
                "quantity": x["quantity"],
                "weight": x["value_usd"] / total,
            }
            for x in items
        ]

        rows.append(
            {
                "cusip": cusip_str,
                "ticker": ticker_str,
                "issuer_name": issuer_name,
                "value_usd": sum_value,
                "quantity": sum_qty,
                "weight": sum_value / total,
                "label": label,
                "sub_holdings": sub_holdings,
            }
        )

    rows.sort(key=lambda row: -row["value_usd"])

    limit = max(int(top_n), 1)
    top = [dict(row) for row in rows[:limit]]
    remainder = rows[limit:]
    if remainder:
        top.append(
            {
                "cusip": None,
                "ticker": None,
                "issuer_name": f"기타 {len(remainder)}종목",
                "label": f"기타 {len(remainder)}종목",
                "value_usd": math.fsum(row["value_usd"] for row in remainder),
                "quantity": None,
                "weight": math.fsum(row["weight"] for row in remainder),
                "sub_holdings": [],
            }
        )
    return {
        "holdings": rows,
        "top": top,
        "total_value": total,
        "position_count": len(rows),
        "top5_share": math.fsum(row["weight"] for row in rows[:5]),
        "top10_share": math.fsum(row["weight"] for row in rows[:10]),
        "excluded": excluded,
    }
