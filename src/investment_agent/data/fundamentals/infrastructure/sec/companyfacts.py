"""SEC Company Facts와 전사 재무 공시 탐색 어댑터.

Company-wide daily and backfill jobs share CompanyFacts. Segment backfills use
the quarterly Financial Statement Data Sets because CompanyFacts omits dimensions.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from datetime import date, timedelta
from typing import Any

from investment_agent.data.universe.infrastructure.sources import sec
from investment_agent.data.fundamentals.domain.filings import FilingRef
from investment_agent.platform.logging import get_logger
from investment_agent.data.fundamentals.domain.filing import (
    SUPPORTED_FORMS as FORMS,
)
from investment_agent.data.fundamentals.domain.filing import (
    SUPPORTED_STATEMENTS as STATEMENTS,
)
from investment_agent.data.fundamentals.domain.filing import (
    normalize_form,
)
from investment_agent.data.fundamentals.domain.taxonomy import gaap_concepts as concepts

log = get_logger(__name__)

_BASE = sec.DATA_BASE
_ARCHIVES = "https://www.sec.gov/Archives/edgar/daily-index"
_MASTER_INDEX_RE = re.compile(r"^master\.(\d{8})\.idx$")
# 정정 8-K/A는 원 속보의 보정이지 새 실적 발표가 아니다. accession이 달라 중복
# Flash가 나갈 수 있으므로, 실시간 속보 대상은 최초 8-K만 허용한다.
EARNINGS_8K_FORMS = ("8-K",)
_FISCAL_QUARTERS = ("Q1", "Q2", "Q3", "Q4")
Filing = FilingRef


def _get_json(url: str) -> dict[str, Any]:
    return sec.get_json(url)


def _get_text(url: str) -> str | None:
    """Fetch SEC archive text, returning None for weekends/holidays."""
    return sec.get_text_optional(url)


def _padded_cik(cik: str | int) -> str:
    return sec.padded_cik(cik)


def submissions(cik: str | int) -> dict[str, Any]:
    """Return current filing metadata for one company."""
    return _get_json(f"{_BASE}/submissions/CIK{_padded_cik(cik)}.json")


def companyfacts(cik: str | int) -> dict[str, Any]:
    """Return all XBRL company facts for one company."""
    return _get_json(
        f"{_BASE}/api/xbrl/companyfacts/CIK{_padded_cik(cik)}.json"
    )


def _quarter(day: date) -> int:
    return (day.month - 1) // 3 + 1


def _available_daily_index_urls(start: date, end: date) -> list[str]:
    """List only daily master indexes that SEC says actually exist."""
    quarters: set[tuple[int, int]] = set()
    day = start
    while day <= end:
        quarters.add((day.year, _quarter(day)))
        day += timedelta(days=1)

    urls: list[tuple[date, str]] = []
    for year, quarter in sorted(quarters):
        base = f"{_ARCHIVES}/{year}/QTR{quarter}"
        listing = _get_json(f"{base}/index.json")
        for item in listing.get("directory", {}).get("item", []) or []:
            name = str(item.get("name") or "")
            match = _MASTER_INDEX_RE.match(name)
            if not match:
                continue
            file_day = date(
                int(match.group(1)[:4]),
                int(match.group(1)[4:6]),
                int(match.group(1)[6:8]),
            )
            if start <= file_day <= end:
                urls.append((file_day, f"{base}/{name}"))
    return [url for _, url in sorted(urls)]


def parse_daily_index_ciks(
    text: str,
    *,
    tracked_ciks: set[int],
    forms: tuple[str, ...] = FORMS,
) -> set[int]:
    """Return tracked CIKs that filed a supported financial form."""
    out: set[int] = set()
    allowed = set(forms)
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) != 5 or parts[2].strip() not in allowed:
            continue
        try:
            cik = int(parts[0])
        except ValueError:
            continue
        if cik in tracked_ciks:
            out.add(cik)
    return out


def recent_form_ciks(
    *,
    tracked_ciks: set[int],
    end: date,
    lookback_days: int,
    forms: tuple[str, ...],
) -> tuple[set[int], int]:
    """SEC daily master index에서 지정 form을 제출한 추적 CIK를 찾는다.

    겹치는 달력일 창은 주말·휴일·인덱스 지연·한 번의 스케줄 누락을 흡수한다.
    """
    if lookback_days < 1:
        raise ValueError("lookback_days must be at least 1")

    changed: set[int] = set()
    files_read = 0
    start = end - timedelta(days=lookback_days - 1)
    for url in _available_daily_index_urls(start, end):
        text = _get_text(url)
        if text is not None:
            files_read += 1
            changed.update(
                parse_daily_index_ciks(
                    text,
                    tracked_ciks=tracked_ciks,
                    forms=forms,
                )
            )

    if files_read == 0:
        raise RuntimeError(
            f"no SEC daily index files available from {start} through {end}"
        )
    return changed, files_read


def recent_financial_ciks(
    *,
    tracked_ciks: set[int],
    end: date,
    lookback_days: int,
) -> tuple[set[int], int]:
    """최근 10-K/10-Q 제출 CIK 목록을 조회한다."""
    return recent_form_ciks(
        tracked_ciks=tracked_ciks,
        end=end,
        lookback_days=lookback_days,
        forms=FORMS,
    )


def is_earnings_8k(form_type: str, items: str | None) -> bool:
    """정확한 Form 8-K Item 2.02 공시만 허용한다."""
    from investment_agent.data.fundamentals.infrastructure.sec.edgar_parser.item_classifier import (
        is_earnings_item,
    )

    return is_earnings_item(form_type, items)


def earnings_8k_filings(
    cik: str | int,
    *,
    cutoff: date,
) -> list[sec.SecFiling]:
    """current submissions와 필요한 과거 fragment에서 Item 2.02를 찾는다."""
    return [
        filing
        for filing in sec.filings_filed_since(
            cik,
            forms=EARNINGS_8K_FORMS,
            cutoff=cutoff,
        )
        if is_earnings_8k(filing.form_type, filing.items)
    ]


def financial_filings(document: dict[str, Any]) -> list[Filing]:
    """Extract recent 10-K/10-Q filing metadata from submissions JSON."""
    recent = document.get("filings", {}).get("recent", {}) or {}
    accessions = recent.get("accessionNumber", []) or []
    filing_dates = recent.get("filingDate", []) or []
    report_dates = recent.get("reportDate", []) or []
    # SEC submissions의 키는 원본 이름 `form`이다. 내부 용어(form_type)로 읽으면
    # 항상 빈 목록이 되어 이 함수가 공시를 하나도 못 찾는다.
    forms = recent.get("form", []) or []
    is_xbrl = recent.get("isXBRL", []) or []

    count = min(len(accessions), len(filing_dates), len(report_dates), len(forms))
    out: list[Filing] = []
    for index in range(count):
        form_type = str(forms[index] or "")
        if form_type not in FORMS:
            continue
        out.append(
            Filing(
                accession_no=str(accessions[index]),
                filing_date=str(filing_dates[index]),
                report_date=str(report_dates[index]),
                form_type=form_type,
                is_xbrl=bool(is_xbrl[index]) if index < len(is_xbrl) else True,
            )
        )
    return out


def all_financial_filings(cik: str | int, *, cutoff: date) -> list[Filing]:
    """cutoff 이후의 10-K/10-Q 전부를 반환한다.

    `financial_filings`는 submissions의 `filings.recent`(최근 1000건)만 읽는다.
    8-K를 자주 내는 회사는 그 창이 3~5년밖에 안 되므로, 10년 이력을 훑는
    백필은 과거 fragment까지 이어 붙이는 `sec.filings_filed_since`를 쓴다.
    """
    return [
        Filing(
            accession_no=row.accession_no,
            filing_date=row.filing_date,
            report_date=row.report_date,
            form_type=row.form_type,
            cik=int(cik),
        )
        for row in sec.filings_filed_since(cik, forms=FORMS, cutoff=cutoff)
    ]


def pending_filings(
    filings: list[Filing],
    last_filed: str | None,
    processed_accessions: set[str] | None = None,
) -> list[Filing]:
    """완료 장부에 없는 XBRL 공시만 반환한다.

    A ticker with no stored fundamentals is seeded from its latest filing.
    The dedicated backfill job remains responsible for full history.
    """
    eligible = [filing for filing in filings if filing.is_xbrl]
    processed = processed_accessions or set()
    if not eligible:
        return []
    if last_filed:
        # 실패는 영구 상태로 저장하지 않는다. 완료 장부에 없는 accession_no은
        # 재실행 때 다시 들어와야 운영자가 Discord 카드에서 본 장애를 복구할 수 있다.
        return [filing for filing in eligible if filing.accession_no not in processed]

    latest = max(filing.filing_date for filing in eligible)
    return [
        filing
        for filing in eligible
        if filing.filing_date == latest and filing.accession_no not in processed
    ]


def _to_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _to_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _duration_quarters(start: date | None, end: date, fp: str) -> int:
    if start is None:
        return 0
    days = (end - start).days + 1
    quarters = max(1, min(4, round(days / 91.25)))
    if fp == "FY":
        return 4 if 330 <= days <= 400 else quarters
    return quarters


def _period_is_usable(fp: str, qtrs: int) -> bool:
    if fp == "FY":
        return qtrs in (0, 4)
    if fp == "Q1":
        return qtrs in (0, 1)
    if fp == "Q2":
        return qtrs in (0, 1, 2)
    if fp == "Q3":
        return qtrs in (0, 1, 3)
    if fp == "Q4":
        return qtrs in (0, 1, 4)
    return False


def _quarter_from_annual_distance(days: int, *, before_annual: bool) -> int | None:
    """인접 10-K 기간말과의 거리로 10-Q의 분기 번호를 복원한다."""
    if not 45 <= days <= 335:
        return None
    quarter_steps = int(days / 91.25 + 0.5)
    quarter = 4 - quarter_steps if before_annual else quarter_steps
    return quarter if quarter in (1, 2, 3) else None


def _dominant_source_filing_focus(
    us_gaap: dict[str, Any],
) -> dict[str, tuple[int, str]]:
    """accession별 가장 많이 반복된 SEC fy/fp를 보조 anchor로 고른다."""
    counts: dict[str, Counter[tuple[int, str]]] = {}
    for concept in us_gaap.values():
        for entries in (concept.get("units") or {}).values():
            for entry in entries or []:
                accession_no = str(entry.get("accn") or "")
                fp = str(entry.get("fp") or "").upper()
                try:
                    fiscal_year = int(entry["fy"])
                except (KeyError, TypeError, ValueError):
                    continue
                if accession_no and fp in (*_FISCAL_QUARTERS, "FY"):
                    counts.setdefault(accession_no, Counter())[fiscal_year, fp] += 1
    return {
        accession_no: counter.most_common(1)[0][0]
        for accession_no, counter in counts.items()
    }


def _corroborated_source_accessions(
    parsed: list[tuple[Filing, date, str]],
    source_focus: dict[str, tuple[int, str]],
) -> set[str]:
    """인접한 Qn→Qn+1 쌍으로 SEC source focus의 회계력 전환을 확인한다."""
    quarters: list[tuple[Filing, date, int, int]] = []
    for filing, report_date, form_type in parsed:
        source = source_focus.get(filing.accession_no)
        if form_type != "10-Q" or source is None or source[1] not in _FISCAL_QUARTERS:
            continue
        quarters.append((filing, report_date, source[0], int(source[1][1])))
    quarters.sort(key=lambda row: (row[1], row[0].filing_date, row[0].accession_no))

    corroborated: set[str] = set()
    for index, (filing, report_date, fiscal_year, quarter) in enumerate(quarters):
        for next_filing, next_date, next_year, next_quarter in quarters[index + 1:]:
            days = (next_date - report_date).days
            if days > 140:
                break
            if (
                days >= 45
                and next_year == fiscal_year
                and next_quarter == quarter + 1
            ):
                corroborated.update((filing.accession_no, next_filing.accession_no))
    return corroborated


def _annual_fiscal_year(
    filing: Filing,
    report_date: date,
    parsed: list[tuple[Filing, date, str]],
    source_focus: dict[str, tuple[int, str]],
) -> int:
    """10-K의 회계연도를 인접 10-Q와 함께 결정한다.

    SEC CompanyFacts의 ``fy``는 일부 발행인에서 10-K만 전년도로 반복된다.
    기간말 직전의 Q3는 같은 회계연도의 가장 강한 관측치이므로, 정상적인
    분기 간격(45~140일)에 있는 Q3의 source year를 우선한다. Q3가 누락된
    경우 Q2/Q1을 보조 anchor로 사용하고, 그래도 없으면 10-K source 또는
    reportDate를 사용한다. 1월 초 52주 결산은 Q3도 전년도로 표시되므로
    기존 source year가 보존된다.
    """

    candidates: list[tuple[int, int, int, str]] = []
    for quarter_priority, quarter in ((0, "Q3"), (1, "Q2")):
        for candidate, candidate_date, form_type in parsed:
            if form_type != "10-Q" or candidate_date >= report_date:
                continue
            source = source_focus.get(candidate.accession_no)
            if source is None or source[1] != quarter:
                continue
            days = (report_date - candidate_date).days
            # Q3는 거의 항상 45~140일 전이다. Q2는 누락된 Q3를 보완한다.
            # Q1은 연간 기간말 뒤에 시작하는 다음 회계연도의 분기이므로
            # 연간 anchor를 정할 때 사용하면 한 해를 거꾸로 붙일 수 있다.
            upper = 140 if quarter == "Q3" else 335
            if not 45 <= days <= upper or abs(source[0] - report_date.year) > 1:
                continue
            candidates.append(
                (quarter_priority, days, source[0], candidate.accession_no)
            )

    if candidates:
        # Q3를 최우선으로 하고, 같은 분기라면 기간말에 가까운 공시를 쓴다.
        candidates.sort(key=lambda row: (row[0], row[1], row[3]))
        return candidates[0][2]

    source = source_focus.get(filing.accession_no)
    if (
        source is not None
        and source[1] == "FY"
        and abs(source[0] - report_date.year) <= 1
    ):
        return source[0]
    return report_date.year


def _canonical_filing_focus(
    filings: list[Filing],
    source_focus: dict[str, tuple[int, str]] | None = None,
) -> dict[str, tuple[int, str]]:
    """SEC unit의 오염된 ``fy``/``fp`` 대신 filing 기간으로 회계키를 만든다.

    CompanyFacts는 일부 등록인에서 과거 fy/fp를 수년간 반복한다. 반면 submissions의
    reportDate와 form은 해당 accession의 실제 보고기간을 가리킨다. 10-K는 FY anchor,
    10-Q는 앞뒤 FY anchor와 약 1분기 간격으로 Q1~Q3를 판정한다.
    """
    parsed: list[tuple[Filing, date, str]] = []
    for filing in filings:
        report_date = _to_date(filing.report_date)
        form_type = normalize_form(filing.form_type)
        if report_date is not None and form_type in ("10-K", "10-Q"):
            parsed.append((filing, report_date, form_type))

    source_focus = source_focus or {}
    corroborated_source = _corroborated_source_accessions(parsed, source_focus)
    annual_anchors: list[tuple[date, int]] = []
    annual_year_by_accession: dict[str, int] = {}
    for filing, report_date, form_type in parsed:
        if form_type != "10-K":
            continue
        fiscal_year = _annual_fiscal_year(
            filing,
            report_date,
            parsed,
            source_focus,
        )
        annual_year_by_accession[filing.accession_no] = fiscal_year
        annual_anchors.append((report_date, fiscal_year))
    annual_anchors.sort()

    out: dict[str, tuple[int, str]] = {}
    for filing, report_date, form_type in parsed:
        if form_type == "10-K":
            fiscal_year = annual_year_by_accession.get(filing.accession_no)
            if fiscal_year is None:
                continue
            out[filing.accession_no] = (fiscal_year, "FY")
            continue

        source = source_focus.get(filing.accession_no)
        previous = max(
            (anchor for anchor in annual_anchors if anchor[0] < report_date),
            default=None,
        )
        following = min(
            (anchor for anchor in annual_anchors if anchor[0] > report_date),
            default=None,
        )
        from_previous = (
            (
                _quarter_from_annual_distance(
                    (report_date - previous[0]).days,
                    before_annual=False,
                ),
                previous[1] + 1,
            )
            if previous is not None
            else None
        )
        from_following = (
            (
                _quarter_from_annual_distance(
                    (following[0] - report_date).days,
                    before_annual=True,
                ),
                following[1],
            )
            if following is not None
            else None
        )
        if from_previous is not None and from_previous[0] is None:
            from_previous = None
        if from_following is not None and from_following[0] is None:
            from_following = None
        if (
            from_previous is not None
            and from_following is not None
            and from_previous != from_following
        ):
            # 두 연간 anchor가 서로 다른 회계력을 가리키면, 인접 Qn→Qn+1
            # source 쌍을 마지막 보조 근거로 사용한다. source 쌍은 정상적인
            # 연간 anchor가 양쪽에 있을 때는 사용하지 않는다. SEC가 Q1/Q2에
            # 전년 fy를 반복하고 Q3에서 되돌리는 사례에서는 source 쌍보다
            # reportDate 기반 anchor가 정확하다.
            source = source_focus.get(filing.accession_no)
            if filing.accession_no not in corroborated_source or source is None:
                continue
            out[filing.accession_no] = source
            continue
        if (
            (from_previous is None or from_following is None)
            and filing.accession_no in corroborated_source
            and source is not None
        ):
            # 한쪽 annual anchor만 있거나 기간 간격이 긴 구간에서는
            # 인접 Qn→Qn+1 source가 기간 기반 추정보다 강한 보조 근거다.
            out[filing.accession_no] = source
            continue
        derived = from_following or from_previous
        if derived is None:
            source = source_focus.get(filing.accession_no)
            if (
                source is None
                or source[1] not in _FISCAL_QUARTERS
                or abs(source[0] - report_date.year) > 1
            ):
                continue
            fiscal_year, source_period = source
            quarter = int(source_period[1])
        else:
            quarter, fiscal_year = derived
        out[filing.accession_no] = (fiscal_year, f"Q{quarter}")
    return out


def _filing_focus_plan(
    document: dict[str, Any],
    filings: list[Filing],
) -> tuple[dict[str, tuple[int, str]], set[str]]:
    """중복 회계력 전환까지 접은 canonical focus와 대체 accession을 계산한다."""
    us_gaap = document.get("facts", {}).get("us-gaap", {}) or {}
    source_focus = _dominant_source_filing_focus(us_gaap)
    candidates = _canonical_filing_focus(
        filings,
        source_focus,
    )

    accepted: dict[str, tuple[int, str]] = {}
    superseded: set[str] = set()
    used_fiscal_keys: set[tuple[int, str]] = set()
    used_period_ends: set[str] = set()
    ordered = sorted(
        filings,
        key=lambda filing: (
            filing.accession_no in source_focus,
            str(filing.report_date or ""),
            str(filing.filing_date or ""),
            filing.accession_no,
        ),
        reverse=True,
    )
    for filing in ordered:
        focus = candidates.get(filing.accession_no)
        report_date = str(filing.report_date or "")
        if focus is None or not report_date:
            continue
        if focus in used_fiscal_keys or report_date in used_period_ends:
            superseded.add(filing.accession_no)
            continue
        accepted[filing.accession_no] = focus
        used_fiscal_keys.add(focus)
        used_period_ends.add(report_date)
    return accepted, superseded


def filing_focus(
    document: dict[str, Any],
    filings: list[Filing],
) -> dict[str, tuple[int, str]]:
    """accession별 canonical 회계연도·기간을 한 번에 계산한다."""
    return _filing_focus_plan(document, filings)[0]


def superseded_filing_accessions(
    document: dict[str, Any],
    filings: list[Filing],
) -> set[str]:
    """같은 CIK 안의 새 회계력이 대체하는 이전 accession을 반환한다."""
    return _filing_focus_plan(document, filings)[1]


def _affected_fiscal_years(
    target_accessions: set[str],
    filing_focus: dict[str, tuple[int, str]],
) -> set[int]:
    return {
        filing_focus[accession_no][0]
        for accession_no in target_accessions
        if accession_no in filing_focus
    }


_BALANCE_COVERAGE_KEYS = frozenset({"assets", "liabilities", "common_equity"})
_EARNINGS_COVERAGE_KEYS = frozenset({
    "revenue",
    "operating_income_loss",
    "pretax_income_loss",
    "net_income",
    "net_income_to_common_shareholders",
    "net_interest_income",
})
_COMPLETE_FILING_COVERAGE = frozenset({"balance", "earnings"})


def _accession_coverage(facts: list[dict]) -> dict[str, set[str]]:
    """Return decision-useful statement coverage for each accession."""
    coverage: dict[str, set[str]] = {}
    for row in facts:
        accession_no = str(row.get("accession_no") or "")
        if not accession_no:
            continue
        column_key = str(row.get("column_key") or "")
        if row.get("qtrs") == 0 and column_key in _BALANCE_COVERAGE_KEYS:
            coverage.setdefault(accession_no, set()).add("balance")
        elif row.get("qtrs") != 0 and column_key in _EARNINGS_COVERAGE_KEYS:
            coverage.setdefault(accession_no, set()).add("earnings")
        else:
            coverage.setdefault(accession_no, set())
    return coverage


def companyfacts_to_facts(
    document: dict[str, Any],
    *,
    filings: list[Filing],
    target_accessions: set[str],
    floor: date,
    allowed_keys: set[str] | frozenset[str] | None = None,
    allow_filing_fallback: bool = False,
) -> list[dict]:
    """Convert SEC companyfacts JSON to the transient fact contract.

    Facts from all filings in an affected fiscal year are included so annual
    Q4 values can still be derived from FY minus Q1/Q2/Q3.
    """
    try:
        cik = int(document["cik"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("companyfacts response has no valid CIK") from exc

    padded_cik = f"{cik:010d}"
    us_gaap = document.get("facts", {}).get("us-gaap", {}) or {}
    focus_by_accession = filing_focus(document, filings)
    affected_years = _affected_fiscal_years(
        target_accessions,
        focus_by_accession,
    )
    if not affected_years:
        log.warning(
            "CIK %010d: target filings have no companyfacts entries: %s",
            cik,
            sorted(target_accessions),
        )
        if not allow_filing_fallback:
            return []

    filing_by_accession = {filing.accession_no: filing for filing in filings}
    out: dict[tuple, dict] = {}
    for raw_tag, concept in us_gaap.items():
        if concepts.is_excluded_tag(raw_tag):
            continue
        column_key = concepts.to_column_key(raw_tag)
        if allowed_keys is not None and column_key not in allowed_keys:
            continue

        for unit, entries in (concept.get("units") or {}).items():
            for entry in entries or []:
                accession_no = str(entry.get("accn") or "")
                filing = filing_by_accession.get(accession_no)
                if filing is None or str(entry.get("form") or "") not in FORMS:
                    continue

                focus = focus_by_accession.get(accession_no)
                if focus is None:
                    continue
                fiscal_year, fp = focus
                if fiscal_year not in affected_years:
                    continue

                period_end = _to_date(entry.get("end"))
                report_date = _to_date(filing.report_date)
                if period_end is None or period_end < floor or report_date is None:
                    continue
                if abs((period_end - report_date).days) > 31:
                    continue

                period_start = _to_date(entry.get("start"))
                qtrs = _duration_quarters(period_start, period_end, fp)
                if not _period_is_usable(fp, qtrs):
                    continue

                value = _to_number(entry.get("val"))
                if value is None:
                    continue

                filed_at = str(entry.get("filed") or filing.filing_date)
                if not concepts.policy_accepts(raw_tag, column_key, str(unit) or None):
                    continue

                pk = (
                    padded_cik,
                    column_key,
                    raw_tag,
                    str(unit) or None,
                    fiscal_year,
                    fp,
                    accession_no,
                    qtrs,
                    period_start.isoformat() if period_start else None,
                    period_end.isoformat(),
                )
                out[pk] = {
                    "cik": padded_cik,
                    "statement": STATEMENTS[0] if qtrs == 0 else STATEMENTS[1],
                    "concept": raw_tag,
                    "standard_tag": concepts.to_standard_tag(raw_tag),
                    "column_key": column_key,
                    "fiscal_year": fiscal_year,
                    "fiscal_period": fp,
                    "qtrs": qtrs,
                    "form_type": normalize_form(filing.form_type),
                    "period_start": period_start.isoformat() if period_start else None,
                    "period_end": period_end.isoformat(),
                    "value": value,
                    "unit": str(unit) or None,
                    "filed_at": filed_at,
                    "accession_no": accession_no,
                    "is_derived": False,
                }

    facts = list(out.values())
    if not allow_filing_fallback:
        return facts

    latest_filing = max(
        (
            filing
            for filing in filings
            if filing.accession_no in focus_by_accession
        ),
        key=lambda item: (item.filing_date, item.accession_no),
        default=None,
    )
    if latest_filing is None:
        raise RuntimeError(
            "target accessions have no canonical fiscal focus: "
            + ", ".join(sorted(target_accessions))
        )
    latest_year = focus_by_accession[latest_filing.accession_no][0]
    latest_targets = {
        accession_no
        for accession_no in target_accessions
        if focus_by_accession.get(accession_no, (None, None))[0] == latest_year
    }
    if not latest_targets:
        return facts

    accession_coverage = _accession_coverage(facts)
    loaded_accessions = set(accession_coverage)
    missing_targets = latest_targets - loaded_accessions
    incomplete_targets = {
        accession_no
        for accession_no in latest_targets & loaded_accessions
        if not filing_by_accession[accession_no].form_type.endswith("/A")
        and accession_coverage[accession_no] != _COMPLETE_FILING_COVERAGE
    }
    if not missing_targets and not incomplete_targets:
        return facts

    required_missing = set(missing_targets)

    from investment_agent.data.fundamentals.infrastructure.sec import filing_xbrl

    fallback_accessions: list[str] = []
    expected_empty_amendments: set[str] = set()
    for filing in sorted(
        filings,
        key=lambda item: (item.filing_date, item.accession_no),
    ):
        focus = focus_by_accession.get(filing.accession_no)
        coverage = accession_coverage.get(filing.accession_no, set())
        if (
            focus is None
            or focus[0] != latest_year
            or (
                coverage
                and (
                    filing.form_type.endswith("/A")
                    or coverage == _COMPLETE_FILING_COVERAGE
                )
            )
        ):
            continue
        try:
            fallback_facts = filing_xbrl.filing_to_facts(
                cik,
                filing,
                fiscal_year=focus[0],
                fiscal_period=focus[1],
                floor=floor,
                allowed_keys=allowed_keys,
            )
        except RuntimeError as exc:
            if filing.form_type.endswith("/A") and "no XBRL document" in str(exc):
                expected_empty_amendments.add(filing.accession_no)
                log.warning(
                    "CIK %010d: amendment has no XBRL and remains empty: %s",
                    cik,
                    filing.accession_no,
                )
                continue
            raise
        facts = [
            row
            for row in facts
            if row.get("accession_no") != filing.accession_no
        ]
        facts.extend(fallback_facts)
        loaded_accessions.add(filing.accession_no)
        accession_coverage[filing.accession_no] = _accession_coverage(
            fallback_facts
        ).get(filing.accession_no, set())
        fallback_accessions.append(filing.accession_no)

    still_missing = (
        required_missing - loaded_accessions - expected_empty_amendments
    )
    if still_missing:
        raise RuntimeError(
            "CompanyFacts and filing XBRL both lack target accessions: "
            + ", ".join(sorted(still_missing))
        )
    required_complete = {
        accession_no
        for accession_no in latest_targets
        if not filing_by_accession[accession_no].form_type.endswith("/A")
    }
    still_incomplete = {
        accession_no
        for accession_no in required_complete
        if accession_coverage.get(accession_no) != _COMPLETE_FILING_COVERAGE
    }
    if still_incomplete:
        raise RuntimeError(
            "filing XBRL remains incomplete for target accessions: "
            + ", ".join(sorted(still_incomplete))
        )
    log.warning(
        "CIK %010d: filing XBRL fallback used for CompanyFacts gaps: %s",
        cik,
        fallback_accessions,
    )
    return facts
