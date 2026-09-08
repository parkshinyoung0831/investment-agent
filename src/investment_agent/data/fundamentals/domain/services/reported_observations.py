"""표준 SEC fact를 영구 저장 가능한 기업 전체 wide 행으로 조립한다."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from investment_agent.data.fundamentals.domain.services.balance_identity import (
    non_liability_claims,
    source_scope,
)
from investment_agent.data.fundamentals.domain.taxonomy import gaap_concepts as concepts
from investment_agent.data.fundamentals.domain.taxonomy.financial_columns import (
    BALANCE_COLUMNS,
    CORE_COLUMNS,
)

_QUARTERS = {"Q1", "Q2", "Q3", "Q4"}
_AVERAGE_SHARE_COLUMNS = {"shares_average", "shares_fully_diluted_average"}
_DERIVED_NCI_CONCEPT = "DerivedNoncontrollingInterestFromTotalEquity"
_DERIVED_MEZZANINE_TOTALS = "DerivedMezzanineEquityFromBalanceTotals"
_DERIVED_MEZZANINE_COMPONENTS = "DerivedMezzanineEquityFromComponents"
_DERIVED_MEZZANINE_SPAC = "DerivedMezzanineEquityFromSpacTrust"
_BALANCE_IDENTITY_TOLERANCE = 0.01
_PARENT_EQUITY_TAGS = frozenset({
    "CommonStockholdersEquity",
    "StockholdersEquity",
})
_TOTAL_EQUITY_TAGS = frozenset({
    "PartnersCapitalIncludingPortionAttributableToNoncontrollingInterest",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    "LimitedLiabilityCompanyLlcMembersEquityIncludingPortionAttributableToNoncontrollingInterest",
})
_TOTAL_MEZZANINE_TAGS = frozenset({
    "TemporaryEquityCarryingAmount",
    "TemporaryEquityCarryingAmountIncludingPortionAttributableToNoncontrollingInterests",
})
_PARENT_MEZZANINE_TAGS = frozenset({
    "TemporaryEquityCarryingAmountAttributableToParent",
})
_NCI_MEZZANINE_TOTAL_TAGS = frozenset({
    "RedeemableNoncontrollingInterestEquityCarryingAmount",
    "TemporaryEquityCarryingAmountAttributableToNoncontrollingInterest",
    "RedeemableNoncontrollingInterestEquityFairValue",
})
_NCI_MEZZANINE_COMPONENT_TAGS = frozenset({
    "RedeemableNoncontrollingInterestEquityCommonCarryingAmount",
    "RedeemableNoncontrollingInterestEquityPreferredCarryingAmount",
    "RedeemableNoncontrollingInterestEquityOtherCarryingAmount",
    "RedeemableNoncontrollingInterestEquityCommonFairValue",
    "RedeemableNoncontrollingInterestEquityOtherFairValue",
})


def _parse_date(value) -> date | None:
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _date_s(value) -> str | None:
    d = _parse_date(value)
    return d.isoformat() if d else None


def _sub_months(d: date, months: int) -> date:
    y, m = d.year, d.month - months
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _same_unit(a: dict, b: dict) -> bool:
    return a.get("unit") == b.get("unit")


def _entity_key(row: dict) -> str:
    cik = str(row.get("cik") or "")
    if len(cik) != 10 or not cik.isdigit():
        raise ValueError("fundamental fact must have a zero-padded 10-digit CIK")
    return cik


def _semantic_group(row: dict) -> tuple:
    """같은 보고기간의 사전 후보를 하나의 의미 선택 단위로 묶는다."""
    return (
        _entity_key(row),
        row["column_key"],
        row["fiscal_year"],
        row["fiscal_period"],
        int(row.get("qtrs") or 0),
        _date_s(row.get("period_end")),
    )


def _filing_instant_group(row: dict) -> tuple:
    return (
        _entity_key(row),
        row["fiscal_year"],
        row["fiscal_period"],
        _date_s(row.get("filed_at")),
        str(row.get("accession_no") or ""),
        row.get("unit"),
    )


def _policy_candidate(rows: list[dict], column_key: str) -> dict | None:
    if not rows:
        return None
    return min(
        rows,
        key=lambda row: (
            concepts.policy_priority(row["concept"], column_key),
            str(row["concept"]),
        ),
    )


def _credible_total_equity(
    total: dict | None,
    parent: dict | None,
    assets: dict | None,
) -> bool:
    """Reject dimension-collapsed note facts masquerading as total equity.

    CompanyFacts omits XBRL dimensions. Some issuers consequently expose a
    statement-of-equity component under the standard total-equity concept. A
    consolidated total materially below an explicitly reported parent balance
    cannot safely anchor a residual mezzanine calculation.
    """
    if total is None or assets is None or assets["value"] <= 0:
        return False
    if parent is None:
        return True
    return (
        total["value"] + assets["value"] * _BALANCE_IDENTITY_TOLERANCE
        >= parent["value"]
    )


def _filter_off_anchor_balance_instants(facts: list[dict]) -> list[dict]:
    """공시 기준일과 다른 point-in-time 잔액 fact를 제외한다.

    IPO 전환일 같은 주석 시점도 같은 FY/FP로 들어온다. 자산(없으면 부채)의 가장
    최근 instant 날짜를 그 공시의 대차대조표 기준일로 삼아, 다른 날짜의 잔액이
    분기말 값으로 병합되는 것을 막는다.
    """
    candidates: dict[tuple, dict[str, list[date]]] = {}
    for row in facts:
        if row.get("period_start") or int(row.get("qtrs") or 0) != 0:
            continue
        column_key = row.get("column_key")
        if column_key not in {"assets", "liabilities"}:
            continue
        period_end = _parse_date(row.get("period_end"))
        if period_end is None:
            continue
        candidates.setdefault(
            _filing_instant_group(row), {"assets": [], "liabilities": []}
        )[column_key].append(period_end)

    anchors = {
        key: max(group["assets"] or group["liabilities"])
        for key, group in candidates.items()
        if group["assets"] or group["liabilities"]
    }
    filtered: list[dict] = []
    for row in facts:
        is_balance_instant = (
            row.get("column_key") in BALANCE_COLUMNS
            and not row.get("period_start")
            and int(row.get("qtrs") or 0) == 0
        )
        anchor = anchors.get(_filing_instant_group(row))
        if (
            is_balance_instant
            and anchor is not None
            and _parse_date(row.get("period_end")) != anchor
        ):
            continue
        filtered.append(row)
    return filtered


def _derive_mezzanine_from_components(facts: list[dict]) -> list[dict]:
    """총 임시자본이 없을 때 모회사·비지배 구성요소를 합산한다."""
    all_tags = (
        _TOTAL_MEZZANINE_TAGS
        | _PARENT_MEZZANINE_TAGS
        | _NCI_MEZZANINE_TOTAL_TAGS
        | _NCI_MEZZANINE_COMPONENT_TAGS
    )
    grouped: dict[tuple, list[dict]] = {}
    for row in facts:
        if (
            row.get("concept") not in all_tags
            or row.get("period_start")
            or int(row.get("qtrs") or 0) != 0
        ):
            continue
        grouped.setdefault(_filing_instant_group(row) + (
            _date_s(row.get("period_end")),
        ), []).append(row)

    derived: list[dict] = []
    for rows in grouped.values():
        if any(row["concept"] in _TOTAL_MEZZANINE_TAGS for row in rows):
            continue
        parent = _policy_candidate(
            [row for row in rows if row["concept"] in _PARENT_MEZZANINE_TAGS],
            "mezzanine_equity",
        )
        nci_total = _policy_candidate(
            [row for row in rows if row["concept"] in _NCI_MEZZANINE_TOTAL_TAGS],
            "mezzanine_equity",
        )
        nci_components = [
            _policy_candidate(
                [row for row in rows if row["concept"] == tag],
                "mezzanine_equity",
            )
            for tag in sorted(_NCI_MEZZANINE_COMPONENT_TAGS)
        ]
        nci_components = [row for row in nci_components if row is not None]
        components = [row for row in [parent, nci_total] if row is not None]
        if nci_total is None:
            components.extend(nci_components)
        # 같은 증권을 parent temporary equity와 redeemable NCI 양쪽 태그로
        # 반복 보고하는 발행인이 있다. 같은 공시·기준일·단위의 동일 금액은
        # 별도 구성요소가 아니라 alias로 보아 한 번만 합산한다.
        distinct_components: list[dict] = []
        seen_values: set[float] = set()
        for row in components:
            value = row["value"]
            if value in seen_values:
                continue
            seen_values.add(value)
            distinct_components.append(row)
        components = distinct_components
        if len(components) < 2:
            continue
        value = sum(row["value"] for row in components)
        if value <= 0:
            continue
        exemplar = parent or nci_total or components[0]
        derived.append(_clone(
            exemplar,
            column_key="mezzanine_equity",
            concept=_DERIVED_MEZZANINE_COMPONENTS,
            standard_tag="mezzanine_equity",
            value=value,
            is_derived=True,
            derivation={
                "formula": "sum(non_overlapping_temporary_equity_components)",
                "source_concepts": [row["concept"] for row in components],
                "source_accessions": sorted({
                    str(row.get("accession_no") or "") for row in components
                }),
            },
        ))
    return [*facts, *derived]


def _filter_mezzanine_against_balance_totals(facts: list[dict]) -> list[dict]:
    """총 영구자본으로 교차 검증되지 않는 임시자본 후보를 제외한다.

    일부 주석의 TemporaryEquity fact는 연결 재무상태표 총계에 추가되는 청구권이
    아니다. 같은 공시의 자산·부채·비지배 포함 총 영구자본이 있으면 그 잔여값과
    자산의 1% 안에서 맞는 총계 후보만 남긴다. 구성요소 합계는 앞 단계가 만든
    파생 총계로 검증한다.
    """
    grouped: dict[tuple, dict[str, list[dict]]] = {}
    relevant = {"assets", "liabilities", "common_equity", "mezzanine_equity"}
    for row in facts:
        column_key = row.get("column_key")
        if (
            column_key not in relevant
            or row.get("period_start")
            or int(row.get("qtrs") or 0) != 0
        ):
            continue
        key = _filing_instant_group(row) + (_date_s(row.get("period_end")),)
        grouped.setdefault(key, {name: [] for name in relevant})[column_key].append(row)

    rejected: set[int] = set()
    for candidates in grouped.values():
        assets = _policy_candidate(candidates["assets"], "assets")
        liabilities = _policy_candidate(candidates["liabilities"], "liabilities")
        total = _policy_candidate(
            [
                row for row in candidates["common_equity"]
                if row["concept"] in _TOTAL_EQUITY_TAGS
            ],
            "common_equity",
        )
        parent = _policy_candidate(
            [
                row for row in candidates["common_equity"]
                if row["concept"] in _PARENT_EQUITY_TAGS
            ],
            "common_equity",
        )
        if (
            not all((assets, liabilities))
            or not _credible_total_equity(total, parent, assets)
            or assets["value"] <= 0
            or not candidates["mezzanine_equity"]
        ):
            continue
        expected = assets["value"] - liabilities["value"] - total["value"]
        for row in candidates["mezzanine_equity"]:
            if (
                abs(row["value"] - expected) / assets["value"]
                > _BALANCE_IDENTITY_TOLERANCE
            ):
                rejected.add(id(row))
    return [row for row in facts if id(row) not in rejected]


def _derive_mezzanine_from_balance_totals(facts: list[dict]) -> list[dict]:
    """명시적 총계 사이에 빠진 임시자본만 복원한다.

    같은 공시·기준일의 자산, 부채, 비지배 포함 총 영구자본이 모두 보고됐지만
    임시자본 태그가 없는 경우 ``자산 - 부채 - 총 영구자본``을 사용한다. 모회사
    자본만 있는 행에는 적용하지 않아 일반적인 회계항등식 잔여값 메우기가 되지 않는다.
    """
    grouped: dict[tuple, dict[str, list[dict]]] = {}
    relevant = {"assets", "liabilities", "common_equity", "mezzanine_equity"}
    for row in facts:
        column_key = row.get("column_key")
        if (
            column_key not in relevant
            or row.get("period_start")
            or int(row.get("qtrs") or 0) != 0
        ):
            continue
        key = _filing_instant_group(row) + (_date_s(row.get("period_end")),)
        grouped.setdefault(key, {name: [] for name in relevant})[column_key].append(row)

    derived: list[dict] = []
    for candidates in grouped.values():
        if candidates["mezzanine_equity"]:
            continue
        assets = _policy_candidate(candidates["assets"], "assets")
        liabilities = _policy_candidate(candidates["liabilities"], "liabilities")
        total = _policy_candidate(
            [
                row for row in candidates["common_equity"]
                if row["concept"] in _TOTAL_EQUITY_TAGS
            ],
            "common_equity",
        )
        parent = _policy_candidate(
            [
                row for row in candidates["common_equity"]
                if row["concept"] in _PARENT_EQUITY_TAGS
            ],
            "common_equity",
        )
        if (
            not all((assets, liabilities))
            or not _credible_total_equity(total, parent, assets)
        ):
            continue
        residual = assets["value"] - liabilities["value"] - total["value"]
        if residual / assets["value"] <= _BALANCE_IDENTITY_TOLERANCE:
            continue
        source_rows = [assets, liabilities, total]
        derived.append(_clone(
            total,
            column_key="mezzanine_equity",
            concept=_DERIVED_MEZZANINE_TOTALS,
            standard_tag="mezzanine_equity",
            value=residual,
            is_derived=True,
            derivation={
                "formula": (
                    "assets - liabilities - total_equity_including_nci"
                ),
                "source_concepts": [row["concept"] for row in source_rows],
                "source_accessions": sorted({
                    str(row.get("accession_no") or "") for row in source_rows
                }),
            },
        ))
    return [*facts, *derived]


def _derive_spac_mezzanine_from_trust(facts: list[dict]) -> list[dict]:
    """신탁자산이 확인된 blank-check 회사의 미보고 상환가능 주식을 복원한다."""
    grouped: dict[tuple, dict[str, list[dict]]] = {}
    relevant = {
        "assets", "liabilities", "common_equity", "minority_interest_balance",
        "preferred_stock", "mezzanine_equity", "assets_held_in_trust",
    }
    for row in facts:
        column_key = row.get("column_key")
        if (
            column_key not in relevant
            or row.get("period_start")
            or int(row.get("qtrs") or 0) != 0
        ):
            continue
        key = _filing_instant_group(row) + (_date_s(row.get("period_end")),)
        grouped.setdefault(key, {name: [] for name in relevant})[column_key].append(row)

    derived: list[dict] = []
    for candidates in grouped.values():
        if candidates["mezzanine_equity"]:
            continue
        assets = _policy_candidate(candidates["assets"], "assets")
        liabilities = _policy_candidate(candidates["liabilities"], "liabilities")
        common = _policy_candidate(candidates["common_equity"], "common_equity")
        trust = _policy_candidate(
            candidates["assets_held_in_trust"], "assets_held_in_trust"
        )
        if not all((assets, liabilities, common, trust)):
            continue
        if common["concept"] in _TOTAL_EQUITY_TAGS:
            continue

        residual = assets["value"] - liabilities["value"] - common["value"]
        minority = _policy_candidate(
            candidates["minority_interest_balance"], "minority_interest_balance"
        )
        if minority is not None:
            residual -= minority["value"]
        if common["concept"] == "CommonStockholdersEquity":
            preferred = _policy_candidate(
                candidates["preferred_stock"], "preferred_stock"
            )
            if preferred is not None:
                residual -= preferred["value"]

        asset_value = assets["value"]
        trust_value = trust["value"]
        if asset_value <= 0 or trust_value <= 0 or residual <= 0:
            continue
        if trust_value / asset_value < 0.80 or residual / asset_value < 0.50:
            continue
        if abs(trust_value - residual) / asset_value > 0.10:
            continue
        if abs(common["value"]) / asset_value > 0.15:
            continue

        source_rows = [assets, liabilities, common, trust]
        if minority is not None:
            source_rows.append(minority)
        derived.append(_clone(
            assets,
            column_key="mezzanine_equity",
            concept=_DERIVED_MEZZANINE_SPAC,
            standard_tag="mezzanine_equity",
            value=residual,
            is_derived=True,
            derivation={
                "formula": (
                    "assets - liabilities - permanent_equity; "
                    "guarded_by_assets_held_in_trust"
                ),
                "source_concepts": [row["concept"] for row in source_rows],
                "source_accessions": sorted({
                    str(row.get("accession_no") or "") for row in source_rows
                }),
            },
        ))
    return [*facts, *derived]


def _derive_minority_interest_from_total_equity(facts: list[dict]) -> list[dict]:
    """같은 공시의 총 영구자본과 모회사 자본 차이를 비지배지분으로 만든다.

    SEC는 비지배지분을 여러 구성 태그로 나누기도 한다. 구성 태그 하나를 총액처럼
    고르면 BX·BXP처럼 일부만 저장된다. 총 영구자본은 임시자본을 제외하므로,
    ``총 영구자본 - 모회사 자본``이 가장 완전한 비지배지분 잔액이다.
    """
    grouped: dict[tuple, dict[str, list[dict]]] = {}
    for row in facts:
        concept = str(row.get("concept") or "")
        column_key = str(row.get("column_key") or "")
        if (
            concept not in _PARENT_EQUITY_TAGS | _TOTAL_EQUITY_TAGS
            and column_key not in {"assets", "liabilities", "mezzanine_equity"}
        ):
            continue
        if row.get("period_start") or int(row.get("qtrs") or 0) != 0:
            continue
        key = (
            _entity_key(row),
            row["fiscal_year"],
            row["fiscal_period"],
            _date_s(row.get("period_end")),
            _date_s(row.get("filed_at")),
            str(row.get("accession_no") or ""),
            row.get("unit"),
        )
        if concept in _PARENT_EQUITY_TAGS:
            kind = "parent"
        elif concept in _TOTAL_EQUITY_TAGS:
            kind = "total"
        else:
            kind = column_key
        grouped.setdefault(
            key,
            {"parent": [], "total": [], "assets": [], "liabilities": [], "mezzanine_equity": []},
        )[kind].append(row)

    derived: list[dict] = []
    for candidates in grouped.values():
        if not all((
            candidates["parent"], candidates["total"],
            candidates["assets"], candidates["liabilities"],
        )):
            continue
        parent = _policy_candidate(candidates["parent"], "common_equity")
        total = _policy_candidate(candidates["total"], "common_equity")
        assets = _policy_candidate(candidates["assets"], "assets")
        liabilities = _policy_candidate(candidates["liabilities"], "liabilities")
        mezzanine = _policy_candidate(
            candidates["mezzanine_equity"], "mezzanine_equity"
        )
        if not all((parent, total, assets, liabilities)):
            continue
        expected_total = (
            assets["value"] - liabilities["value"]
            - (mezzanine["value"] if mezzanine is not None else 0)
        )
        if (
            abs(total["value"] - expected_total)
            / max(abs(assets["value"]), 1)
            > _BALANCE_IDENTITY_TOLERANCE
        ):
            continue
        value = total["value"] - parent["value"]
        if value <= 0:
            continue
        derived.append(_clone(
            total,
            column_key="minority_interest_balance",
            concept=_DERIVED_NCI_CONCEPT,
            standard_tag="minority_interest_balance",
            value=value,
            is_derived=True,
            derivation={
                "formula": "total_equity_including_nci - parent_equity",
                "corroboration": "total_equity = assets - liabilities - mezzanine_equity",
                "source_concepts": [total["concept"], parent["concept"]],
                "source_accessions": sorted({
                    str(total.get("accession_no") or ""),
                    str(parent.get("accession_no") or ""),
                }),
            },
        ))
    return [*facts, *derived]


def select_semantic_candidates(facts: list[dict]) -> tuple[list[dict], list[dict]]:
    """사전 후보 중 최신 filing의 명시적 정책 우선순위 값을 선택한다."""
    groups: dict[tuple, list[dict]] = {}
    for row in facts:
        groups.setdefault(_semantic_group(row), []).append(row)

    selected: list[dict] = []
    anomalies: list[dict] = []
    for candidates in groups.values():
        latest_filing = max(
            (str(row.get("filed_at") or ""), str(row.get("accession_no") or ""))
            for row in candidates
        )
        latest = [
            row for row in candidates
            if (str(row.get("filed_at") or ""), str(row.get("accession_no") or ""))
            == latest_filing
        ]
        priority = min(
            concepts.policy_priority(row["concept"], row["column_key"])
            for row in latest
        )
        finalists = [
            row for row in latest
            if concepts.policy_priority(row["concept"], row["column_key"]) == priority
        ]
        distinct_tags = sorted({str(row["concept"]) for row in finalists})
        if len(distinct_tags) > 1:
            exemplar = finalists[0]
            anomalies.append({
                "cik": _entity_key(exemplar),
                "fiscal_year": exemplar["fiscal_year"],
                "fiscal_period": exemplar["fiscal_period"],
                "reason": "mapping_conflict",
                "detail": {
                    "column_key": exemplar["column_key"],
                    "tags": distinct_tags,
                    "accession_no": exemplar.get("accession_no"),
                    "unit": exemplar.get("unit"),
                },
                "filed_at": exemplar.get("filed_at"),
            })
            if concepts.policy_rejects_conflict(exemplar["column_key"]):
                continue
        selected.append(min(finalists, key=lambda row: str(row["concept"])))
    return selected, anomalies


def _is_better(candidate: dict, current: dict | None) -> bool:
    if current is None:
        return True
    if bool(candidate.get("is_derived")) != bool(current.get("is_derived")):
        return not bool(candidate.get("is_derived"))
    return (
        str(candidate.get("filed_at") or ""),
        str(candidate.get("accession_no") or ""),
    ) > (
        str(current.get("filed_at") or ""),
        str(current.get("accession_no") or ""),
    )


def _prefer(candidate: dict, current: dict | None) -> bool:
    """normalized 병합 우선순위.

    대차대조표(BALANCE_COLUMNS) 컬럼은 시점(instant=period_start 없음)값을 기간값보다
    우선한다. edgartools 매핑이 자본의 구성·변동·AOCI 항목까지 잔액 컬럼으로 뭉뚱그려,
    분기 10-Q에서 이런 기간 항목이 진짜 잔액(예: StockholdersEquity)을 덮어쓰는 오염을
    막기 위함이다. 그 외에는 기존 _is_better 규칙(원본 우선·최신 공시 우선)을 따른다.
    """
    if current is None:
        return True
    if candidate["column_key"] in BALANCE_COLUMNS:
        cand_instant = not candidate.get("period_start")
        cur_instant = not current.get("period_start")
        if cand_instant != cur_instant:
            return cand_instant
    return _is_better(candidate, current)


def _clone(row: dict, **updates) -> dict:
    out = dict(row)
    out.update(updates)
    if "period_end" in out:
        out["period_end"] = _date_s(out["period_end"])
    if "period_start" in out:
        out["period_start"] = _date_s(out["period_start"])
    return out


def _duration_days(row: dict) -> int | None:
    """SEC duration context의 양 끝을 포함한 일수를 돌려준다."""
    start = _parse_date(row.get("period_start"))
    end = _parse_date(row.get("period_end"))
    if start is None or end is None or end < start:
        return None
    return (end - start).days + 1


def _standalone_duration_value(current: dict, previous: dict) -> float | None:
    """누적 duration 값에서 마지막 단독 분기 값을 복원한다.

    손익·현금흐름은 누적 합계라 단순 차감한다. 평균주식수는 기간 가중평균이므로
    ``(누적평균×누적일수 - 이전평균×이전일수) / 추가일수``로 계산한다.
    """
    if current["column_key"] not in _AVERAGE_SHARE_COLUMNS:
        return current["value"] - previous["value"]

    current_days = _duration_days(current)
    previous_days = _duration_days(previous)
    if current_days and previous_days and current_days > previous_days:
        value = (
            current["value"] * current_days - previous["value"] * previous_days
        ) / (current_days - previous_days)
    else:
        current_qtrs = int(current.get("qtrs") or 0)
        previous_qtrs = int(previous.get("qtrs") or 0)
        if current_qtrs <= previous_qtrs:
            return None
        value = (
            current["value"] * current_qtrs - previous["value"] * previous_qtrs
        ) / (current_qtrs - previous_qtrs)
    return value if value > 0 else None


def _q4_duration_value(fy: dict, quarters: list[dict]) -> float | None:
    """FY와 Q1~Q3에서 Q4 단독 값을 복원한다."""
    if fy["column_key"] not in _AVERAGE_SHARE_COLUMNS:
        return fy["value"] - sum(row["value"] for row in quarters)

    fy_days = _duration_days(fy)
    quarter_days = [_duration_days(row) for row in quarters]
    if fy_days and all(quarter_days):
        q123_days = sum(int(days) for days in quarter_days)
        q4_days = fy_days - q123_days
        if q4_days <= 0:
            return None
        value = (
            fy["value"] * fy_days
            - sum(row["value"] * int(days) for row, days in zip(quarters, quarter_days))
        ) / q4_days
    else:
        value = fy["value"] * 4 - sum(row["value"] for row in quarters)
    return value if value > 0 else None


def periodize(facts: list[dict]) -> list[dict]:
    """원시 기간 형태를 FY와 독립 분기 fact로 정규화한다."""
    latest: dict[tuple, dict] = {}
    for row in facts:
        key = (
            _entity_key(row),
            row["column_key"],
            row["fiscal_year"],
            row["fiscal_period"],
            int(row.get("qtrs") or 0),
        )
        if _is_better(row, latest.get(key)):
            latest[key] = row

    fy_rows = [r for r in latest.values() if r["fiscal_period"] == "FY"]

    duration_qtd_candidates: list[dict] = []
    by_qtrs: dict[tuple, list[dict]] = {}
    for row in latest.values():
        by_qtrs.setdefault(
            (_entity_key(row), row["column_key"], row["fiscal_year"], int(row.get("qtrs") or 0)),
            [],
        ).append(row)

        fp = row["fiscal_period"]
        qtrs = int(row.get("qtrs") or 0)
        if fp in _QUARTERS and (qtrs == 1 or (qtrs == 0 and row.get("period_start"))):
            duration_qtd_candidates.append(_clone(row, qtrs=1))

    for cur in latest.values():
        fp = cur["fiscal_period"]
        qtrs = int(cur.get("qtrs") or 0)
        if fp not in ("Q2", "Q3") or qtrs not in (2, 3):
            continue

        cur_end = _parse_date(cur.get("period_end"))
        if cur_end is None:
            continue

        prev_rows = by_qtrs.get((_entity_key(cur), cur["column_key"], cur["fiscal_year"], qtrs - 1), [])
        prev = None
        for candidate in prev_rows:
            prev_end = _parse_date(candidate.get("period_end"))
            if prev_end is None or prev_end >= cur_end or not _same_unit(cur, candidate):
                continue
            if prev is None or prev_end > _parse_date(prev.get("period_end")):
                prev = candidate

        if prev is None:
            continue

        derived_value = _standalone_duration_value(cur, prev)
        if derived_value is None:
            continue
        prev_end = _parse_date(prev.get("period_end"))
        if prev_end is None:
            continue
        duration_qtd_candidates.append(_clone(
            cur,
            qtrs=1,
            period_start=prev_end + timedelta(days=1),
            value=derived_value,
            is_derived=True,
            derivation={
                "formula": (
                    "weighted_average_qtd_current - weighted_average_qtd_previous"
                    if cur["column_key"] in _AVERAGE_SHARE_COLUMNS
                    else "qtd_current - qtd_previous"
                ),
                "source_accessions": [cur.get("accession_no"), prev.get("accession_no")],
            },
        ))

    duration_qtd: dict[tuple, dict] = {}
    for row in duration_qtd_candidates:
        key = (_entity_key(row), row["column_key"], row["fiscal_year"], row["fiscal_period"])
        if _is_better(row, duration_qtd.get(key)):
            duration_qtd[key] = row

    # Q1~Q3 분기값을 (CIK, column_key, unit)별 시계열로 모은다. fiscal_year
    # 라벨로 묶지 않는 이유: 비-12월 결산사는 SEC가 FY(10-K)와 분기(10-Q)에
    # 1년 어긋난 fy를 붙여서, fiscal_year로 묶으면 엉뚱한 해의 분기를 빼게 된다
    # (예: NVDA Q4 = FY2023 4,368 − 2021년 분기합 6,750 = −2,382). 대신 FY 종료
    # 직전 12개월 안의 Q1·Q2·Q3를 period_end 날짜로 매칭해 Q4 = FY − (Q1+Q2+Q3).
    q123_by_series: dict[tuple, list[dict]] = {}
    for row in duration_qtd.values():
        if row["fiscal_period"] not in ("Q1", "Q2", "Q3"):
            continue
        pe = _parse_date(row.get("period_end"))
        if pe is None:
            continue
        q123_by_series.setdefault(
            (_entity_key(row), row["column_key"], row.get("unit")), []
        ).append(row)

    q4_from_fy: list[dict] = []
    for fy in fy_rows:
        qtrs = int(fy.get("qtrs") or 0)
        if qtrs != 4 and not fy.get("period_start"):
            continue
        fy_end = _parse_date(fy.get("period_end"))
        if fy_end is None:
            continue
        window_start = _sub_months(fy_end, 12)
        latest_by_fp: dict[str, dict] = {}
        for candidate in q123_by_series.get(
            (_entity_key(fy), fy["column_key"], fy.get("unit")), []
        ):
            pe = _parse_date(candidate.get("period_end"))
            if pe is None:
                continue
            fp = candidate["fiscal_period"]
            if not window_start < pe < fy_end:
                continue
            if fp not in latest_by_fp or pe > _parse_date(latest_by_fp[fp]["period_end"]):
                latest_by_fp[fp] = candidate
        if len(latest_by_fp) != 3:  # Q1·Q2·Q3가 모두 있어야 Q4 역산 가능
            continue
        quarters = [latest_by_fp[period] for period in ("Q1", "Q2", "Q3")]
        q4_value = _q4_duration_value(fy, quarters)
        if q4_value is None:
            continue
        q4_start = max(
            _parse_date(row.get("period_end")) for row in quarters
        ) + timedelta(days=1)
        q4_from_fy.append(_clone(
            fy,
            fiscal_period="Q4",
            qtrs=1,
            period_start=q4_start,
            value=q4_value,
            is_derived=True,
            derivation={
                "formula": (
                    "weighted_average_fy - weighted_average_q1_q2_q3"
                    if fy["column_key"] in _AVERAGE_SHARE_COLUMNS
                    else "fy - q1 - q2 - q3"
                ),
                "source_accessions": [
                    fy.get("accession_no"),
                    *[
                        latest_by_fp[period].get("accession_no")
                        for period in ("Q1", "Q2", "Q3")
                    ],
                ],
            },
        ))

    instant_quarters = [
        _clone(row)
        for row in latest.values()
        if row["fiscal_period"] in _QUARTERS
        and int(row.get("qtrs") or 0) == 0
        and not row.get("period_start")
    ]
    instant_q4_from_fy = [
        _clone(row, fiscal_period="Q4", qtrs=0, period_start=None, is_derived=True)
        for row in fy_rows
        if int(row.get("qtrs") or 0) == 0 and not row.get("period_start")
    ]

    normalized: dict[tuple, dict] = {}
    for row in [*fy_rows, *duration_qtd.values(), *q4_from_fy, *instant_quarters, *instant_q4_from_fy]:
        key = (_entity_key(row), row["column_key"], row["fiscal_year"], row["fiscal_period"])
        if _prefer(row, normalized.get(key)):
            normalized[key] = row

    return list(normalized.values())


def _manifest(row: dict) -> dict:
    """wide 값 하나를 재현할 수 있는 최소 출처 정보를 직렬화한다."""
    return {
        "raw_tag": row.get("concept"),
        "standard_tag": row.get("standard_tag"),
        "unit": row.get("unit"),
        "accession_no": row.get("accession_no"),
        "filed_at": _date_s(row.get("filed_at")),
        "period_start": _date_s(row.get("period_start")),
        "period_end": _date_s(row.get("period_end")),
        "is_derived": bool(row.get("is_derived")),
        "derivation": row.get("derivation"),
    }


def _pivot(rows: list[dict], columns: tuple[str, ...]) -> list[dict]:
    column_set = set(columns)
    groups: dict[tuple, dict] = {}

    for row in rows:
        col = row["column_key"]
        if col not in column_set:
            continue

        entity = _entity_key(row)
        key = (entity, row["fiscal_year"], row["fiscal_period"])
        out = groups.get(key)
        if out is None:
            out = {
                "cik": entity,
                "fiscal_year": row["fiscal_year"],
                "fiscal_period": row["fiscal_period"],
                "accession_no": None,
                "form_type": None,
                "period_end": None,
                "filed_at": None,
                "mapping_version": concepts.SEMANTIC_POLICY_VERSION,
                "common_equity_scope": "unknown",
                "is_liabilities_derived": False,
                "source_manifest": {},
                **{name: None for name in columns},
            }
            groups[key] = out

        period_end = _date_s(row.get("period_end"))
        filed_at = _date_s(row.get("filed_at"))
        if period_end and (out["period_end"] is None or period_end > out["period_end"]):
            out["period_end"] = period_end
        if filed_at and (out["filed_at"] is None or filed_at > out["filed_at"]):
            out["filed_at"] = filed_at
            out["accession_no"] = row.get("accession_no")
            out["form_type"] = row.get("form_type")
        elif filed_at and filed_at == out["filed_at"]:
            accession_no = str(row.get("accession_no") or "")
            if accession_no > str(out.get("accession_no") or ""):
                out["accession_no"] = accession_no
                out["form_type"] = row.get("form_type")
        out[col] = row["value"]
        out["source_manifest"][col] = _manifest(row)

    return [
        row for row in groups.values()
        if any(row.get(name) is not None for name in columns)
    ]


def _derive_missing_liabilities(rows: list[dict]) -> list[dict]:
    """정확한 총부채 태그가 없을 때만 회계항등식 잔여값을 채운다.

    부분 부채 태그를 총부채로 승격하지 않는다. 총자산과 보통주자본이 모두
    보고됐고 잔여값이 음수가 아닐 때만 파생하며, 저장 행의 boolean과 변환 중
    manifest가 직접 보고값과 파생값을 구분한다.
    """
    for row in rows:
        row["common_equity_scope"] = source_scope(row)
        row["is_liabilities_derived"] = False
        if row.get("liabilities") is not None:
            continue
        assets = row.get("assets")
        claims = non_liability_claims(row)
        if assets is None or claims is None:
            continue
        residual = assets - claims
        if residual < 0:
            continue
        row["liabilities"] = residual
        row["is_liabilities_derived"] = True
        manifests = row.get("source_manifest") or {}
        source_accessions = sorted({
            str(manifest["accession_no"])
            for column in (
                "assets",
                "common_equity",
                "minority_interest_balance",
                "mezzanine_equity",
            )
            if (manifest := manifests.get(column))
            and manifest.get("accession_no")
        })
        manifests["liabilities"] = {
            "raw_tag": None,
            "standard_tag": None,
            "unit": "USD",
            "accession_no": row.get("accession_no"),
            "filed_at": row.get("filed_at"),
            "period_start": None,
            "period_end": row.get("period_end"),
            "is_derived": True,
            "derivation": {
                "formula": "assets - non_liability_claims(common_equity_scope)",
                "common_equity_scope": row["common_equity_scope"],
                "source_accessions": source_accessions,
            },
        }
        row["source_manifest"] = manifests
    return rows


def to_wide_tables(facts: list[dict]) -> tuple[list[dict], list[dict]]:
    """core wide 행과 매핑 이상 행을 반환한다.

    FY는 저장하지 않는다. `periodize`가 이미 FY에서 Q4 단독값을 복원했으므로 FY는
    그 복원의 입력일 뿐이고, 저장하면 대차대조표가 Q4와 그대로 중복된다(실측
    4,802행 중 4,794행이 Q4와 `assets`가 동일했다). 연간 손익은 Q4 시점의
    최근 4개 분기 원장 행의 합으로 계산한다.
    """
    anchored = _filter_off_anchor_balance_instants(facts)
    with_components = _derive_mezzanine_from_components(anchored)
    corroborated = _filter_mezzanine_against_balance_totals(with_components)
    with_totals = _derive_mezzanine_from_balance_totals(corroborated)
    with_spac_mezzanine = _derive_spac_mezzanine_from_trust(with_totals)
    selected, anomalies = select_semantic_candidates(
        _derive_minority_interest_from_total_equity(with_spac_mezzanine)
    )
    quarters = [
        row for row in periodize(selected)
        if str(row.get("fiscal_period") or "") != "FY"
    ]
    return _derive_missing_liabilities(_pivot(quarters, CORE_COLUMNS)), anomalies
