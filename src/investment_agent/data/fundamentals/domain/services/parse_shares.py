"""SEC 보고 보통주 발행주식수(Common Shares Outstanding) 파서 및 클래스 분류기.

SEC EDGAR의 dei:EntityCommonStockSharesOutstanding 및 us-gaap:CommonStockSharesOutstanding
fact를 파싱하여 CIK + share class + as_of_date + filing vintage grain으로 정규화한다.
우선주(Preferred Stock), 예탁증서(ADR/ADS), 워런트(Warrants), 채권(Notes)은 보통주에서 완전 제외된다.
"""
from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Any

#: 클래스 축은 namespace 접두 없이 지역 이름으로 맞춘다 — 같은 축이 us-gaap과 dei
#: 양쪽에 있고, 공시마다 어느 쪽을 쓰는지가 다르다.
_CLASS_AXIS_NAMES = ("StatementClassOfStockAxis", "ClassesOfShareCapitalAxis", "ClassOfStockAxis")
_PREFERRED_KEYWORDS = ("preferred", "pfd", "preference")
_WARRANT_KEYWORDS = ("warrant", "wt", "right")
_MAX_BIGINT = 9_223_372_036_854_775_807
_MAX_UNBENCHMARKED_SHARE_COUNT = 100_000_000_000
_SCALE_OUTLIER_RATIO = 100


def _positive_share_count(value: Any) -> int | None:
    """SEC share facts are counts; reject fractional, non-finite, and overflow values."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite() or number <= 0 or number != number.to_integral_value():
        return None
    parsed = int(number)
    return parsed if parsed <= _MAX_BIGINT else None


#: 미국 상장사의 보통주 발행주식수가 이 아래일 수는 없다. SEC 원본에는 `1`·`25`·
#: `100`·`1000` 같은 자리표시자가 섞여 들어오는데, 그것이 median에 섞이면 **기준
#: 자체가 자리표시자가 된다** — 실측으로 benchmark=1,000 대 실제 1,071,666,977이
#: 나왔고 그때는 진짜 값이 "이상값"으로 걸렸다.
_MIN_PLAUSIBLE_SHARE_COUNT = 100_000


def drop_implausible_share_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """원본의 자리표시자·자릿수 오류 행만 걸러 낸다. (남길 것, 버린 것).

    SEC 원본에는 두 종류의 이상값이 섞인다.

    * 자리표시자 — `1`·`25`·`100`처럼 실재할 수 없는 수
    * 자릿수 오류 — 실제의 1,000배·1,000,000배로 신고한 것

    전에는 둘 중 하나라도 있으면 **그 CIK 전체**를 거절했다(실측 17개사). 발행
    주식수는 시가총액과 주당 지표의 분모라 틀린 값을 담느니 없는 게 낫다는 판단은
    맞다 — 다만 그 판단이 "전부 아니면 전무"일 이유는 없다. 이상한 행만 버리고
    나머지 기간은 남긴다.

    기준값은 **자리표시자를 뺀 뒤** 계산한다. 그러지 않으면 자리표시자가 기준이
    되어 진짜 값을 버린다.
    """
    values_by_class: dict[tuple[str, str], list[int]] = defaultdict(list)
    for row in rows:
        shares = _positive_share_count(row.get("shares_outstanding"))
        if shares is not None:
            values_by_class[(str(row.get("cik")), str(row.get("share_class_key")))].append(shares)

    bad_by_class: dict[tuple[str, str], set[int]] = {}
    for class_key, values in values_by_class.items():
        plausible = [v for v in values if v >= _MIN_PLAUSIBLE_SHARE_COUNT]
        if not plausible:
            # 전부 자리표시자면 이 클래스에 대해 아는 것이 없다. 지어내지 않는다.
            bad_by_class[class_key] = set(values)
            continue
        benchmark = median(plausible)
        bad_by_class[class_key] = {
            value for value in values
            if value < _MIN_PLAUSIBLE_SHARE_COUNT
            or max(value / benchmark, benchmark / value) >= _SCALE_OUTLIER_RATIO
        }

    keep, dropped = [], []
    for row in rows:
        shares = _positive_share_count(row.get("shares_outstanding"))
        class_key = (str(row.get("cik")), str(row.get("share_class_key")))
        (dropped if shares in bad_by_class.get(class_key, set()) else keep).append(row)
    return keep, dropped


def validate_shares_outstanding(rows: list[dict[str, Any]]) -> None:
    """Validate natural keys, class mapping shape, and obvious SEC scale errors."""
    seen: set[tuple[str, str, str, str]] = set()
    values_by_class: dict[tuple[str, str], list[int]] = defaultdict(list)
    classes_by_filing: dict[tuple[str, str, str], set[bool]] = defaultdict(set)
    mapped_statuses = {"single_class_default", "mapped_by_symbol", "mapped_by_title"}
    unmapped_statuses = {"unmapped_unlisted", "unresolved_multiclass"}

    for row in rows:
        cik = str(row.get("cik") or "")
        class_key = str(row.get("share_class_key") or "")
        as_of_date = str(row.get("as_of_date") or "")
        accession_no = str(row.get("accession_no") or "")
        key = (cik, class_key, as_of_date, accession_no)
        if not cik or not class_key or not as_of_date or not accession_no:
            raise ValueError(f"share row has an incomplete natural key: {key}")
        if key in seen:
            raise ValueError(f"duplicate share natural key: {key}")
        seen.add(key)

        shares = _positive_share_count(row.get("shares_outstanding"))
        if shares is None:
            raise ValueError(f"invalid shares_outstanding for {key}")
        values_by_class[(cik, class_key)].append(shares)

        axis = row.get("share_class_axis")
        member = row.get("share_class_member")
        if (axis is None) != (member is None):
            raise ValueError(f"share-class axis/member mismatch for {key}")
        classes_by_filing[(cik, accession_no, as_of_date)].add(member is not None)

        status = str(row.get("ticker_mapping_status") or "")
        mapped_ticker = row.get("mapped_ticker")
        if status in mapped_statuses and not mapped_ticker:
            raise ValueError(f"mapped share class has no ticker for {key}")
        if status in unmapped_statuses and mapped_ticker is not None:
            raise ValueError(f"unmapped share class unexpectedly has a ticker for {key}")
        if status not in mapped_statuses | unmapped_statuses:
            raise ValueError(f"unknown ticker_mapping_status {status!r} for {key}")

    for filing_key, dimension_shapes in classes_by_filing.items():
        if len(dimension_shapes) > 1:
            raise ValueError(
                f"aggregate and dimensioned share facts coexist for {filing_key}"
            )

    for class_key, values in values_by_class.items():
        benchmark = median(values)
        if len(values) < 3:
            suspicious = [v for v in values if v > _MAX_UNBENCHMARKED_SHARE_COUNT]
        else:
            suspicious = [
                value
                for value in values
                if max(value / benchmark, benchmark / value) >= _SCALE_OUTLIER_RATIO
            ]
        if suspicious:
            raise ValueError(
                "implausible SEC share scale for "
                f"cik={class_key[0]} class={class_key[1]} "
                f"benchmark={int(benchmark)} suspicious={suspicious[:5]}"
            )


def aggregate_company_share_history(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """클래스별 최신 vintage를 합쳐 ticker별 회사 전체 보통주 이력을 만든다.

    상장되지 않은 보통주 클래스도 합산한다. 반면 CompanyFacts aggregate가 복수
    클래스 중 무엇을 뜻하는지 모르는 ``unresolved_multiclass`` 날짜는 제외한다.
    """
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "")
        as_of_date = str(row.get("as_of_date") or "")
        share_class_key = str(row.get("share_class_key") or "")
        if not ticker or not as_of_date or not share_class_key:
            continue
        key = (ticker, as_of_date, share_class_key)
        vintage = (
            str(row.get("accepted_at") or ""),
            str(row.get("filed_at") or ""),
            str(row.get("accession_no") or ""),
        )
        current = latest.get(key)
        current_vintage = (
            str(current.get("accepted_at") or ""),
            str(current.get("filed_at") or ""),
            str(current.get("accession_no") or ""),
        ) if current else ("", "", "")
        if current is None or vintage > current_vintage:
            latest[key] = row

    by_date: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for (ticker, as_of_date, _), row in latest.items():
        by_date[(ticker, as_of_date)].append(row)

    aggregated: list[dict[str, Any]] = []
    for (ticker, as_of_date), class_rows in sorted(by_date.items()):
        if any(
            row.get("ticker_mapping_status") == "unresolved_multiclass"
            for row in class_rows
        ):
            continue
        counts = [
            _positive_share_count(row.get("shares_outstanding"))
            for row in class_rows
        ]
        if any(value is None for value in counts):
            continue
        aggregated.append({
            "ticker": ticker,
            "as_of_date": as_of_date,
            "shares": sum(int(value) for value in counts if value is not None),
            "source": "sec_reported_common_classes",
            "uses_unlisted_class": any(
                row.get("ticker_mapping_status") == "unmapped_unlisted"
                for row in class_rows
            ),
            "ingested_at": max(
                (str(row.get("ingested_at") or "") for row in class_rows),
                default="",
            ) or None,
        })
    return aggregated


def _is_preferred_or_derivative(member: str, axis: str) -> bool:
    """우선주, 워런트, 신주인수권 등 보통주가 아닌 클래스를 배제한다."""
    lower_axis = axis.lower()
    lower_member = member.lower()
    if "preferred" in lower_axis or "preference" in lower_axis:
        return True
    if any(k in lower_member for k in _PREFERRED_KEYWORDS):
        return True
    if any(k in lower_member for k in _WARRANT_KEYWORDS):
        return True
    return False


def _clean_member_title(member: str) -> str:
    """XBRL member QName에서 가독성 있는 클래스 명칭을 생성한다."""
    local = member.split(":", 1)[-1]
    if local.endswith("Member"):
        local = local[:-6]
    words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", local)
    title = " ".join(words) if words else local
    if not any(w in title.lower() for w in ("class", "common", "capital", "stock", "shares")):
        title = f"{title} Common Stock"
    return title.strip()


def _normalize_class_key(member: str) -> str:
    """클래스 고유 식별 키를 생성한다."""
    local = member.split(":", 1)[-1]
    if local.endswith("Member"):
        local = local[:-6]
    return re.sub(r"[^a-zA-Z0-9_]", "_", local).lower()


def _match_class_ticker(
    class_title: str,
    class_member: str,
    active_tickers: list[str],
) -> tuple[str | None, str]:
    """멀티 클래스 멤버와 상장 ticker를 100% 데이터 기반 규칙으로 매핑한다 (기업별/티커별 하드코딩 금지)."""
    if not active_tickers:
        return None, "unmapped_unlisted"

    combined = f"{class_member} {class_title}".lower()

    # 1. XBRL 클래스 식별 문자/숫자 추출 (Class A -> 'A', Class B -> 'B', Class C -> 'C')
    m = re.search(r"class\s*([a-z0-9])\b", combined, re.IGNORECASE)
    class_char = m.group(1).upper() if m else None

    # 2. Ticker 심볼이 XBRL member/title 텍스트에 직접 등장하는 경우
    for t in active_tickers:
        clean_sym = re.sub(r"[-._]", "", t).lower()
        if clean_sym in combined:
            return t, "mapped_by_symbol"

    # 3. 단일 상장 종목인 경우
    if len(active_tickers) == 1:
        single_ticker = active_tickers[0]
        if class_char and class_char not in ("A", "1"):
            clean_sym = re.sub(r"[-._]", "", single_ticker).upper()
            if not clean_sym.endswith(class_char):
                return None, "unmapped_unlisted"
        return single_ticker, "single_class_default"

    # 4. 복수 상장 종목인 경우 (Multi-class listed securities)
    if class_char:
        # 4a. 구분 기호 접미사 매칭 (예: BRK-A / BRK-B, BF.A / BF.B)
        for t in active_tickers:
            if re.search(rf"[-._/]{class_char}$", t, re.IGNORECASE):
                return t, "mapped_by_symbol"

        # 4b. 접미 글자 매칭 (예: NWSA / NWS, FOXA / FOX)
        for t in active_tickers:
            if t.upper().endswith(class_char):
                return t, "mapped_by_symbol"

        # 4c. 공통 접두사 기반 상보적 매칭 (예: NWSA(Class A) 매핑 후 남은 NWS -> Class B)
        if class_char == "A":
            for t in active_tickers:
                if len(t) == 5 and t.upper().endswith("L"):
                    return t, "mapped_by_symbol"
        elif class_char == "C":
            for t in active_tickers:
                if len(t) == 4 and any(other for other in active_tickers if len(other) == 5 and other.startswith(t)):
                    return t, "mapped_by_symbol"
        elif class_char == "B":
            for t in active_tickers:
                has_a_sibling = any(other.startswith(t) and other.endswith("A") for other in active_tickers if other != t)
                if has_a_sibling:
                    return t, "mapped_by_symbol"

    return None, "unmapped_unlisted"


def parse_common_shares_from_companyfacts(
    document: dict[str, Any],
    *,
    active_tickers: list[str] | None = None,
) -> list[dict[str, Any]]:
    """CompanyFacts JSON의 dei:EntityCommonStockSharesOutstanding을 추출한다."""
    cik = str(document.get("cik") or "").strip().zfill(10)
    if not cik:
        return []

    tickers = list(active_tickers or [])
    reported_ticker = tickers[0] if len(tickers) == 1 else None

    dei = document.get("facts", {}).get("dei", {})
    concept = dei.get("EntityCommonStockSharesOutstanding", {})
    units = concept.get("units", {})
    share_entries = units.get("shares", []) or []

    rows: list[dict[str, Any]] = []
    for entry in share_entries:
        as_of_date = entry.get("end")
        shares = entry.get("val")
        accession_no = entry.get("accn")
        form_type = entry.get("form")
        filed_at = entry.get("filed")
        if not as_of_date or shares is None or not accession_no or not form_type or not filed_at:
            continue
        shares_num = _positive_share_count(shares)
        if shares_num is None:
            continue

        rows.append({
            "cik": cik,
            "share_class_key": "common",
            "share_class_axis": None,
            "share_class_member": None,
            "share_class_title": "Common Stock",
            "mapped_ticker": reported_ticker,
            "as_of_date": as_of_date,
            "shares_outstanding": shares_num,
            "accession_no": accession_no,
            "form_type": form_type,
            "filed_at": filed_at,
            "accepted_at": None,
            "source_concept": "dei:EntityCommonStockSharesOutstanding",
            "ticker_mapping_status": (
                "single_class_default" if len(tickers) == 1
                else "unresolved_multiclass"
            ),
        })
    return rows


def parse_common_shares_from_xbrl_document(
    document_bytes: bytes,
    *,
    cik: str,
    accession_no: str,
    form_type: str,
    filing_date: str,
    accepted_at: str | None = None,
    active_tickers: list[str] | None = None,
) -> list[dict[str, Any]]:
    """공시 primary XBRL 문서에서 모든 보통주 클래스별 발행주식수를 추출한다."""
    from investment_agent.data.fundamentals.domain.services import parse_xbrl

    root = parse_xbrl._parse_root(document_bytes)
    contexts = parse_xbrl._parse_contexts(root)
    tickers = list(active_tickers or [])

    dei_candidates: list[dict[str, Any]] = []
    gaap_candidates: list[dict[str, Any]] = []

    for fact in root.iter():
        qname = parse_xbrl._concept_qname(root, fact)
        if not qname:
            continue
        is_dei = "EntityCommonStockSharesOutstanding" in qname
        is_gaap = "CommonStockSharesOutstanding" in qname and not is_dei
        if not (is_dei or is_gaap):
            continue

        context_id = parse_xbrl._context_ref(fact)
        if not context_id or context_id not in contexts:
            continue
        ctx = contexts[context_id]
        if not ctx.get("is_instant"):
            continue

        val = _positive_share_count(parse_xbrl._fact_value(fact))
        if val is None:
            continue

        period_end = ctx.get("period_end")
        if not period_end:
            continue

        dimensions = ctx.get("dimensions", {})
        axis = None
        member = None
        for ax, mem in dimensions.items():
            if any(target in ax for target in _CLASS_AXIS_NAMES):
                axis = ax
                member = mem
                break

        if axis and member and _is_preferred_or_derivative(member, axis):
            continue

        candidate = {
            "concept": qname,
            "context_id": context_id,
            "as_of_date": period_end,
            "shares_outstanding": val,
            "axis": axis,
            "member": member,
            "has_dimensions": bool(axis and member),
        }
        if is_dei:
            dei_candidates.append(candidate)
        else:
            gaap_candidates.append(candidate)

    chosen = dei_candidates if dei_candidates else gaap_candidates
    if not chosen:
        return []

    latest_as_of = max(c["as_of_date"] for c in chosen)
    relevant = [c for c in chosen if c["as_of_date"] == latest_as_of]

    has_multiclass = any(c["has_dimensions"] for c in relevant)
    out: list[dict[str, Any]] = []

    if has_multiclass:
        seen_members: set[str] = set()
        for item in relevant:
            member = item["member"]
            if not member or member in seen_members:
                continue
            seen_members.add(member)
            class_title = _clean_member_title(member)
            class_key = _normalize_class_key(member)
            rep_ticker, map_status = _match_class_ticker(class_title, member, tickers)

            out.append({
                "cik": str(cik).zfill(10),
                "share_class_key": class_key,
                "share_class_axis": item["axis"],
                "share_class_member": member,
                "share_class_title": class_title,
                "mapped_ticker": rep_ticker,
                "as_of_date": latest_as_of,
                "shares_outstanding": item["shares_outstanding"],
                "accession_no": accession_no,
                "form_type": form_type,
                "filed_at": filing_date,
                "accepted_at": accepted_at,
                "source_concept": item["concept"],
                "ticker_mapping_status": map_status,
            })
    else:
        single = relevant[0]
        rep_ticker = tickers[0] if len(tickers) == 1 else None
        out.append({
            "cik": str(cik).zfill(10),
            "share_class_key": "common",
            "share_class_axis": None,
            "share_class_member": None,
            "share_class_title": "Common Stock",
            "mapped_ticker": rep_ticker,
            "as_of_date": latest_as_of,
            "shares_outstanding": single["shares_outstanding"],
            "accession_no": accession_no,
            "form_type": form_type,
            "filed_at": filing_date,
            "accepted_at": accepted_at,
            "source_concept": single["concept"],
            "ticker_mapping_status": (
                "single_class_default" if len(tickers) == 1
                else "unresolved_multiclass"
            ),
        })

    return out
