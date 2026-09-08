"""저장된 13F 공시를 포트폴리오·변화·컨센서스 데이터로 변환한다."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal

from investment_agent.data.institutional.domain.managers import SIGNAL_GROUP_LABELS


def _number(value: object) -> Decimal:
    if value in (None, ""):
        return Decimal(0)
    return Decimal(str(value))


def _filing_order(row: dict) -> tuple[str, str, str]:
    return (
        str(row.get("filing_date") or ""),
        str(row.get("accepted_at") or ""),
        str(row.get("accession_no") or ""),
    )


def _coverage_status(filings: Iterable[dict]) -> str:
    rows = list(filings)
    report_types = {
        str(row.get("report_type") or "").upper()
        for row in rows
    }
    if any("NOTICE" in report_type for report_type in report_types):
        return "notice"
    if any("COMBINATION" in report_type for report_type in report_types):
        return "partial"
    if any(bool(row.get("confidential_omitted")) for row in rows):
        return "confidential"
    if report_types and all(
        "HOLDINGS REPORT" in report_type for report_type in report_types
    ):
        return "full"
    return "unknown"


def _authoritative_filings(rows: list[dict]) -> list[dict]:
    """기준 공시와 이후 NEW HOLDINGS 수정공시를 최종 포트폴리오로 결합한다."""
    base_candidates = [
        row
        for row in rows
        if row.get("form_type") == "13F-HR"
        or row.get("amendment_type") == "RESTATEMENT"
    ]
    if not base_candidates:
        return []

    base = max(base_candidates, key=_filing_order)
    base_order = _filing_order(base)
    additions = [
        row
        for row in rows
        if row.get("amendment_type") == "NEW HOLDINGS"
        and _filing_order(row) >= base_order
    ]
    return [base, *sorted(additions, key=_filing_order)]


def _combined_positions(
    authoritative: list[dict],
    positions_by_accession: dict[str, list[dict]],
) -> list[dict]:
    grouped: dict[tuple[str, str, str], dict[str, object]] = defaultdict(
        lambda: {
            "issuer_name": "",
            "value_usd": Decimal(0),
            "quantity": 0,
        }
    )
    for filing in authoritative:
        accession_no = str(filing["accession_no"])
        for position in positions_by_accession.get(accession_no, []):
            key = (
                str(position["cusip"]),
                str(position["position_kind"]),
                str(position["quantity_type"]),
            )
            item = grouped[key]
            if not item["issuer_name"]:
                item["issuer_name"] = str(position.get("issuer_name") or "")
            item["value_usd"] = _number(item["value_usd"]) + _number(
                position.get("value_usd")
            )
            item["quantity"] = int(item["quantity"]) + int(
                position.get("quantity") or 0
            )

    return [
        {
            "issuer_name": values["issuer_name"],
            "cusip": cusip,
            "value_usd": values["value_usd"],
            "quantity": values["quantity"],
            "quantity_type": quantity_type,
            "position_kind": position_kind,
        }
        for (cusip, position_kind, quantity_type), values in sorted(grouped.items())
    ]


def _instrument(row: dict) -> str:
    """13F 포지션을 자산 종류로 분류한다.

    13F가 보고하는 비주식 노출(상장 옵션·전환사채/원금)을 주식과 분리한다.
    - principal : sshPrnamtType=PRN (전환사채·노트 등 채권성)
    - call/put  : 상장 콜·풋 옵션
    - equity    : 보통주(SHARES + SH)
    숏·해외 상장주·장외파생·비상장은 13F에 아예 보이지 않는다(managers.blind_spots).
    """
    if str(row.get("quantity_type")) == "PRN":
        return "principal"
    kind = str(row.get("position_kind"))
    if kind == "CALL":
        return "call"
    if kind == "PUT":
        return "put"
    return "equity"


def _portfolio_rows(
    managers: list[dict],
    filings: list[dict],
    positions: list[dict],
    cusip_map: dict[str, str | None],
) -> tuple[list[dict], list[dict], list[dict]]:
    positions_by_accession: dict[str, list[dict]] = defaultdict(list)
    for position in positions:
        positions_by_accession[str(position["accession_no"])].append(position)

    filings_by_period: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for filing in filings:
        filings_by_period[
            (str(filing["manager_cik"]), str(filing["period_end"]))
        ].append(filing)

    manager_ciks = {
        str(row["manager_cik"])
        for row in managers
        if row.get("is_active", True)
    }
    summaries: list[dict] = []
    holdings: list[dict] = []
    instruments: list[dict] = []

    for (manager_cik, period_end), period_filings in sorted(
        filings_by_period.items()
    ):
        if manager_cik not in manager_ciks:
            continue
        authoritative = _authoritative_filings(period_filings)
        if not authoritative:
            continue

        latest = max(authoritative, key=_filing_order)
        combined = _combined_positions(authoritative, positions_by_accession)
        status = _coverage_status(authoritative)
        portfolio_value = sum(
            (_number(row["value_usd"]) for row in combined),
            start=Decimal(0),
        )
        equity_positions = [
            row
            for row in combined
            if row["quantity_type"] == "SH"
            and row["position_kind"] == "SHARES"
        ]
        # 자산 종류별 노출(주식/콜/풋/원금). 옵션·전환사채를 버리지 않고 분리 집계한다.
        breakdown: dict[str, dict] = {
            bucket: {"value_usd": Decimal(0), "count": 0}
            for bucket in ("equity", "call", "put", "principal")
        }
        for row in combined:
            bucket = breakdown[_instrument(row)]
            bucket["value_usd"] += _number(row["value_usd"])
            bucket["count"] += 1
            if _instrument(row) != "equity":
                instruments.append(
                    {
                        "manager_cik": manager_cik,
                        "period_end": period_end,
                        "cusip": row["cusip"],
                        "ticker": cusip_map.get(str(row["cusip"])),
                        "issuer_name": row["issuer_name"],
                        "instrument": _instrument(row),
                        "position_kind": row["position_kind"],
                        "quantity_type": row["quantity_type"],
                        "value_usd": row["value_usd"],
                        "quantity": row["quantity"],
                    }
                )
        summaries.append(
            {
                "manager_cik": manager_cik,
                "period_end": period_end,
                "accession_no": latest["accession_no"],
                "filing_date": latest["filing_date"],
                "accepted_at": latest.get("accepted_at"),
                "form_type": latest["form_type"],
                "amendment_type": latest.get("amendment_type"),
                "report_type": latest.get("report_type"),
                "source_url": latest.get("source_url"),
                # 13F 보고가치(모든 노출 합) — '전체 포트폴리오'가 아니라 13F 공개분.
                "reported_13f_value_usd": portfolio_value,
                # 13F Long Equity = position_kind=SHARES AND quantity_type=SH.
                "long_equity_value_usd": breakdown["equity"]["value_usd"],
                "call_value_usd": breakdown["call"]["value_usd"],
                "put_value_usd": breakdown["put"]["value_usd"],
                "principal_value_usd": breakdown["principal"]["value_usd"],
                "long_equity_count": breakdown["equity"]["count"],
                "call_count": breakdown["call"]["count"],
                "put_count": breakdown["put"]["count"],
                "principal_count": breakdown["principal"]["count"],
                # portfolio_value_usd는 13F 보고가치 총액이다.
                "portfolio_value_usd": portfolio_value,
                "position_count": len(combined),
                "equity_position_count": breakdown["equity"]["count"],
                "instrument_breakdown": breakdown,
                "pct_denominator": "13f_long_equity",
                "visibility_scope": "visible_13f_only",
                "confidential_omitted": any(
                    bool(row.get("confidential_omitted"))
                    for row in authoritative
                ),
                "coverage_status": status,
                "analysis_eligible": status == "full",
            }
        )

        # holdings는 13F Long Equity(보통주 long)만 담는다. CALL/PUT/PRN은 섞지 않고
        # summary.instrument_breakdown / snapshot.instruments로만 분리 노출한다.
        long_equity_total = breakdown["equity"]["value_usd"]
        for position in equity_positions:
            pct = (
                float(_number(position["value_usd"]) / long_equity_total)
                if long_equity_total
                else None
            )
            holdings.append(
                {
                    "manager_cik": manager_cik,
                    "period_end": period_end,
                    "cusip": position["cusip"],
                    "issuer_name": position["issuer_name"],
                    "put_call": "SH",
                    "ticker": cusip_map.get(str(position["cusip"])),
                    "shares": position["quantity"],
                    "market_value": position["value_usd"],
                    # 분모 = 13F Long Equity. '전체 포트폴리오 비중'이 아니다.
                    "pct_of_13f_long_equity": pct,
                    "pct_denominator": "13f_long_equity",
                    "visibility_scope": "visible_13f_only",
                    "pct_of_portfolio": pct,
                }
            )

    return summaries, holdings, instruments


def _change_rows(
    managers: list[dict],
    summaries: list[dict],
    holdings: list[dict],
) -> list[dict]:
    manager_by_cik = {
        str(row["manager_cik"]): row
        for row in managers
    }
    summaries_by_manager: dict[str, list[dict]] = defaultdict(list)
    for summary in summaries:
        summaries_by_manager[str(summary["manager_cik"])].append(summary)

    holdings_by_period: dict[tuple[str, str], dict[tuple[str, str], dict]] = (
        defaultdict(dict)
    )
    for holding in holdings:
        holdings_by_period[
            (str(holding["manager_cik"]), str(holding["period_end"]))
        ][(str(holding["cusip"]), str(holding["put_call"]))] = holding

    changes: list[dict] = []
    for manager_cik, manager_summaries in summaries_by_manager.items():
        ordered = sorted(
            manager_summaries,
            key=lambda row: str(row["period_end"]),
        )
        manager = manager_by_cik.get(manager_cik, {})
        for index, current in enumerate(ordered):
            previous = ordered[index - 1] if index else None
            if not current.get("analysis_eligible"):
                continue
            # 최초 적재분은 비교 기준선일 뿐 매매 변화가 아니다. 여기서 모든
            # 보유를 신규 매수로 만들면 신규 매니저/새 DB가 컨센서스를 오염시킨다.
            if previous is None:
                continue
            if not previous.get("analysis_eligible"):
                continue
            current_rows = holdings_by_period[
                (manager_cik, str(current["period_end"]))
            ]
            previous_rows = (
                holdings_by_period[
                    (manager_cik, str(previous["period_end"]))
                ]
                if previous is not None
                else {}
            )
            for key in sorted(current_rows.keys() | previous_rows.keys()):
                current_holding = current_rows.get(key)
                previous_holding = previous_rows.get(key)
                shares = (
                    int(current_holding["shares"])
                    if current_holding is not None
                    else None
                )
                previous_shares = (
                    int(previous_holding["shares"])
                    if previous_holding is not None
                    else None
                )
                if previous_holding is None:
                    change_type = "new"
                elif current_holding is None:
                    change_type = "exit"
                elif shares > previous_shares * 1.10:
                    change_type = "increase"
                elif shares < previous_shares * 0.90:
                    change_type = "decrease"
                else:
                    change_type = "hold"

                changes.append(
                    {
                        "manager": manager.get("name") or manager_cik,
                        "fund_name": manager.get("fund_name") or "",
                        "manager_cik": manager_cik,
                        "period_end": current["period_end"],
                        "cusip": key[0],
                        "ticker": (
                            (current_holding or {}).get("ticker")
                            or (previous_holding or {}).get("ticker")
                        ),
                        "put_call": key[1],
                        "shares": shares,
                        "prev_shares": previous_shares,
                        "market_value": (
                            current_holding.get("market_value")
                            if current_holding
                            else None
                        ),
                        "prev_market_value": (
                            previous_holding.get("market_value")
                            if previous_holding
                            else None
                        ),
                        "pct_of_13f_long_equity": (
                            current_holding.get("pct_of_13f_long_equity")
                            if current_holding
                            else None
                        ),
                        "prev_pct_long_equity": (
                            previous_holding.get("pct_of_13f_long_equity")
                            if previous_holding
                            else None
                        ),
                        "pct_denominator": "13f_long_equity",
                        "pct_of_portfolio": (
                            current_holding.get("pct_of_portfolio")
                            if current_holding
                            else None
                        ),
                        "prev_pct": (
                            previous_holding.get("pct_of_portfolio")
                            if previous_holding
                            else None
                        ),
                        "change_type": change_type,
                    }
                )
    return changes


def _consensus_rows(
    managers: list[dict],
    summaries: list[dict],
    changes: list[dict],
    *,
    side: str,
) -> list[dict]:
    active_ciks = {
        str(row["manager_cik"])
        for row in managers
        if row.get("is_active")
    }
    latest_summary: dict[str, dict] = {}
    for summary in summaries:
        manager_cik = str(summary["manager_cik"])
        current = latest_summary.get(manager_cik)
        if current is None or str(summary["period_end"]) > str(
            current["period_end"]
        ):
            latest_summary[manager_cik] = summary

    if side == "buy":
        accepted_types = {"new", "increase"}
        weight_column = "pct_of_portfolio"
        value_column = "market_value"
    else:
        accepted_types = {"exit", "decrease"}
        weight_column = "prev_pct"
        value_column = "prev_market_value"

    groups: dict[tuple[str, str, str | None], list[dict]] = defaultdict(list)
    for change in changes:
        manager_cik = str(change["manager_cik"])
        latest = latest_summary.get(manager_cik)
        if (
            manager_cik not in active_ciks
            or latest is None
            or not latest.get("analysis_eligible")
            or str(change["period_end"]) != str(latest["period_end"])
            or change.get("put_call") != "SH"
            or change.get("change_type") not in accepted_types
            or float(change.get(weight_column) or 0) < 0.01
        ):
            continue
        groups[
            (
                str(change["period_end"]),
                str(change["cusip"]),
                change.get("ticker"),
            )
        ].append(change)

    output: list[dict] = []
    for (period_end, cusip, ticker), rows in groups.items():
        weights = [float(row.get(weight_column) or 0) for row in rows]
        ordered_managers = [
            str(row["manager"])
            for row in sorted(
                rows,
                key=lambda row: (
                    -float(row.get(weight_column) or 0),
                    str(row["manager"]),
                ),
            )
        ]
        common = {
            "period_end": period_end,
            "cusip": cusip,
            "ticker": ticker,
            "manager_count": len(rows),
            "conviction_score": round(sum(weights), 6),
            "managers": ordered_managers,
        }
        if side == "buy":
            common.update(
                {
                    "new_count": sum(
                        row["change_type"] == "new" for row in rows
                    ),
                    "increase_count": sum(
                        row["change_type"] == "increase" for row in rows
                    ),
                    "market_value": sum(
                        (
                            _number(row.get(value_column))
                            for row in rows
                        ),
                        start=Decimal(0),
                    ),
                    "avg_pct_of_portfolio": round(
                        sum(weights) / len(weights),
                        6,
                    ),
                    "max_pct_of_portfolio": max(weights),
                }
            )
        else:
            common.update(
                {
                    "exit_count": sum(
                        row["change_type"] == "exit" for row in rows
                    ),
                    "decrease_count": sum(
                        row["change_type"] == "decrease" for row in rows
                    ),
                    "prev_market_value": sum(
                        (
                            _number(row.get(value_column))
                            for row in rows
                        ),
                        start=Decimal(0),
                    ),
                    "avg_prev_pct": round(
                        sum(weights) / len(weights),
                        6,
                    ),
                    "max_prev_pct": max(weights),
                }
            )
        output.append(common)

    return sorted(
        output,
        key=lambda row: (
            float(row["conviction_score"]),
            int(row["manager_count"]),
            str(row.get("ticker") or ""),
            str(row["cusip"]),
        ),
        reverse=True,
    )


def _manager_groups(managers: list[dict]) -> list[dict]:
    """active manager를 signal_role 그룹으로 묶어 display_order 순으로 정렬한다.

    카드/알림이 '7인 레이더'를 역할별로 다르게 해석해 표시할 수 있도록 한다.
    비활성 manager는 그룹에 포함하지 않는다.
    """
    active = [row for row in managers if row.get("is_active")]

    def _order_key(row: dict) -> tuple[bool, int, str]:
        order = row.get("display_order")
        return (order is None, int(order) if order is not None else 0,
                str(row.get("name") or ""))

    groups: list[dict] = []
    for role, label in SIGNAL_GROUP_LABELS:
        members = sorted(
            (row for row in active if row.get("signal_role") == role),
            key=_order_key,
        )
        if not members:
            continue
        groups.append(
            {
                "signal_role": role,
                "label": label,
                "managers": [
                    {
                        "manager_cik": str(row["manager_cik"]),
                        "name": row.get("name"),
                        "name_ko": row.get("name_ko"),
                        "strategy_group": row.get("strategy_group"),
                        "copyability": row.get("copyability"),
                        "thesis_ko": row.get("thesis_ko"),
                        "display_order": row.get("display_order"),
                    }
                    for row in members
                ],
            }
        )
    return groups


def build_snapshot(source: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """DB 원본 데이터를 알림과 분석에서 사용하는 결정적 스냅샷으로 변환한다."""
    managers = source.get("managers", [])
    cusip_map = {
        str(row["cusip"]): (
            str(row["ticker"]) if row.get("ticker") else None
        )
        for row in source.get("cusip_map", [])
    }
    summaries, holdings, instruments = _portfolio_rows(
        managers,
        source.get("filings", []),
        source.get("positions", []),
        cusip_map,
    )
    changes = _change_rows(managers, summaries, holdings)
    return {
        "managers": managers,
        "manager_groups": _manager_groups(managers),
        "filings": summaries,
        "holdings": holdings,
        "instruments": instruments,
        "changes": changes,
        "buys": _consensus_rows(
            managers,
            summaries,
            changes,
            side="buy",
        ),
        "sells": _consensus_rows(
            managers,
            summaries,
            changes,
            side="sell",
        ),
        "tickers": source.get("tickers", []),
    }


