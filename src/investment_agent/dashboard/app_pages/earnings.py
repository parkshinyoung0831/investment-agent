"""실적 예정·결과·추이·공시 근거를 선택한 뷰만 표시한다."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from investment_agent.dashboard.calculations import (
    DEFAULT_SCHEDULE_HORIZON,
    SCHEDULE_HORIZONS,
    d_day_label,
    finite_number,
    free_cash_flow,
    historical_surprise_series,
    latest_estimate_overview,
    pre_release_consensus,
    quarter_growth,
    schedule_window,
    sec_gaap_diluted_eps,
    today_kst,
)
from investment_agent.dashboard.db import (
    EXTENDED_SECTIONS,
    load_earnings_data,
    load_earnings_discord_support,
    load_earnings_extended,
    load_ticker_data_quality,
)
from investment_agent.dashboard.components.theme import dashboard_palette, plotly_layout
from investment_agent.dashboard.components.ui import (
    SOURCE_CALC,
    SOURCE_DB,
    dataframe,
    display_money,
    display_number,
    display_percent,
    result_payload,
    result_status,
    source_note,
    view_selector,
)


_COLORS = dashboard_palette()
PRIMARY = _COLORS.primary
TEXT = _COLORS.text
MUTED = _COLORS.muted
UP = _COLORS.up
DOWN = _COLORS.down
from investment_agent.reporting.services.earnings import schedule as calendar_schedule
from investment_agent.reporting.services.earnings.guidance import format_guidance_headline
from investment_agent.reporting.services.earnings import metrics as discord_metrics
from investment_agent.reporting.services.earnings import valuation_history as discord_history
from investment_agent.reporting.services.earnings.thresholds import grade as discord_grade
from investment_agent.notifications.earnings_report import charts as discord_charts
from investment_agent.notifications.earnings_report import card as discord_card
from investment_agent.notifications.earnings_report import candidates as discord_candidates

SEGMENT_TYPE_LABELS: dict[str, str] = {
    "business": "사업 부문",
    "geographic": "지역 부문",
    "product": "제품·서비스",
}



def _ticker_rows(rows: list[dict[str, Any]], ticker: str) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("ticker", "")).upper() == ticker]


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if pd.notna(number) else None


def _difference(actual: Any, estimate: Any) -> dict[str, float | None]:
    actual_number, estimate_number = _number(actual), _number(estimate)
    if actual_number is None or estimate_number is None:
        return {"difference": None, "surprise": None}
    difference = actual_number - estimate_number
    surprise = difference / abs(estimate_number) if estimate_number else None
    return {"difference": difference, "surprise": surprise}


def _estimate_provenance(row: dict[str, Any]) -> str:
    """속보 예상치가 발표 전 관측값인지 사후 재구성값인지 화면에 드러낸다."""
    kind = str(row.get("estimate_kind") or "")
    snapshot_date = str(row.get("estimate_snapshot_date") or "")
    if kind == "observed":
        return f"발표 전 관측 컨센서스 · {snapshot_date}" if snapshot_date else "발표 전 관측 컨센서스"
    if kind == "reconstructed":
        return "Yahoo 발표 이력 재구성값"
    return "예상치 없음"


def _select_ticker(active_watchlist: list[str], *, key: str) -> str | None:
    if not active_watchlist:
        st.info("활성 실적 관심종목이 없어 상세 종목을 선택할 수 없습니다.")
        return None
    return st.selectbox("관심종목", active_watchlist, key=key)


def _latest_row(rows: list[dict[str, Any]], key: str = "period_end") -> dict[str, Any]:
    return max(rows, key=lambda row: str(row.get(key) or ""), default={})


def _safe_discord_derived(
    row: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    """Discord 계산을 재사용하되 결측 현금·CapEx를 0으로 간주하지 않는다."""

    derived = dict(discord_metrics.derive(row, previous))
    if (
        _number(row.get("net_cash_from_operating_activities")) is None
        or _number(row.get("capital_expenses")) is None
    ):
        derived["fcf"] = None

    cash_parts = [
        _number(row.get("cash_and_cash_equivalents")),
        _number(row.get("short_term_investments")),
    ]
    present = [v for v in cash_parts if v is not None]
    cash = sum(present) if present else None
    total_debt = _number(row.get("total_debt_including_current"))
    if total_debt is None:
        debt_parts = [
            _number(row.get(column))
            for column in (
                "short_term_debt",
                "current_portion_of_long_term_debt",
                "long_term_debt",
                "operating_lease_current_debt_equivalent",
                "operating_lease_non_current_debt_equivalent",
            )
        ]
        present_parts = [value for value in debt_parts if value is not None]
        total_debt = sum(present_parts) if present_parts else None
    if cash is None or total_debt is None:
        derived["net_debt"] = None
    return derived


def _cashflow_bridge_ready(row: dict[str, Any] | None) -> bool:
    """0 대체가 허위 FCF를 만들지 않도록 브리지 필수 원값을 확인한다."""

    if not row:
        return False
    return all(
        _number(row.get(column)) is not None
        for column in (
            "net_income",
            "net_cash_from_operating_activities",
            "depreciation_amortization_cf",
            "stock_based_compensation_cf",
            "capital_expenses",
        )
    )


def _historical_valuation(
    *,
    ticker: str,
    current: dict[str, Any],
    core_rows: list[dict[str, Any]],
    valuation_rows: list[dict[str, Any]],
    metric_rows: list[dict[str, Any]],
    price_rows: list[dict[str, Any]],
    share_rows: list[tuple[str, float]],
) -> dict[str, Any] | None:
    """Discord와 같은 available-date as-of 규칙으로 역사 밸류를 계산한다.

    한 분기 스냅샷은 financial_versions와 market 원장에서 모인다. TTM·배수는
    현재 v1 reporting view에 없으므로 추정하지 않고 비워 둔다.
    공시일(`filed_at`)을 모르는 분기는 as-of 기준이 없으므로 건너뛴다.
    """

    filed_at = str(current.get("filed_at") or "")
    if not filed_at:
        return None

    core_by_key = {
        (
            str(row.get("ticker") or "").upper(),
            str(row.get("fiscal_year") or ""),
            str(row.get("fiscal_period") or ""),
        ): row
        for row in core_rows
        if str(row.get("ticker") or "").upper() == ticker
        and str(row.get("fiscal_period") or "") in {"Q1", "Q2", "Q3", "Q4"}
        and row.get("filed_at")
    }
    metrics_by_key = {
        (
            str(row.get("ticker") or "").upper(),
            str(row.get("fiscal_year") or ""),
            str(row.get("fiscal_period") or ""),
        ): row
        for row in metric_rows
    }
    snapshots: list[dict[str, Any]] = []
    for row in valuation_rows:
        if row.get("valuation_supported") is False:
            continue
        key = (
            str(row.get("ticker") or "").upper(),
            str(row.get("fiscal_year") or ""),
            str(row.get("fiscal_period") or ""),
        )
        core = core_by_key.get(key) or {}
        available_date = str(core.get("filed_at") or "")
        if not available_date or available_date > filed_at:
            continue
        metrics = metrics_by_key.get(key) or {}
        enterprise_value = _number(row.get("enterprise_value"))
        market_cap = _number(row.get("market_cap"))
        snapshots.append(
            {
                "available_date": available_date,
                "book_value": core.get("common_equity"),
                "earnings_ttm": metrics.get("earnings_ttm"),
                "revenue_ttm": metrics.get("revenue_ttm"),
                "ebitda_ttm": metrics.get("ebitda_ttm"),
                # 시총을 뺀 나머지(순부채 + 우선주 + 소수지분)가 EV 조정분이다.
                "ev_ex_market_cap": (
                    enterprise_value - market_cap
                    if enterprise_value is not None and market_cap is not None
                    else None
                ),
                "fcf_ttm": metrics.get("free_cash_flow_ttm"),
            }
        )
    snapshots.sort(key=lambda row: row["available_date"])

    prices = sorted(
        [
            (str(row.get("trade_date")), float(row["close"]))
            for row in price_rows
            if row.get("trade_date") and _number(row.get("close")) is not None
        ],
        key=lambda item: item[0],
    )
    splits = sorted(
        [
            (str(row.get("trade_date")), float(row["split_ratio"]))
            for row in price_rows
            if row.get("trade_date")
            and (_number(row.get("split_ratio")) is not None)
            and _number(row.get("split_ratio")) > 0.0
        ],
        key=lambda item: item[0],
    )
    shares = sorted(share_rows, key=lambda item: item[0])
    if not prices:
        return None
    as_of = pd.to_datetime(prices[-1][0], errors="coerce")
    if pd.isna(as_of):
        return None
    history = discord_history.compute(
        prices,
        shares,
        snapshots,
        splits=splits,
        today=as_of.date(),
    )
    if history and any(_number(row.get("ev_ex_market_cap")) is None for row in snapshots):
        # 알림 계산은 누락 EV 조정을 0으로 대체한다. 대시보드는 이를 실제 값처럼
        # 표시하지 않고, 다른 시점정합 배수만 유지한다.
        history = {**history, "stats": dict(history.get("stats") or {})}
        history["stats"].pop("ev_ebitda", None)
    return history


def _filing_trust_notes(
    current: dict[str, Any],
    filing_rows: list[dict[str, Any]],
    quality: dict[str, list[dict[str, Any]]],
    notified: bool | None,
) -> list[tuple[str, str]]:
    """이 공시 숫자를 믿어도 되는지. (심각도, 문장) 목록을 만든다.

    도메인 완료 상태·분할 보정·발행사 매핑 모호를 한곳에서 설명한다.
    운영 실패 원문은 Discord 시스템 로그와 GitHub Actions에서 확인한다.
    """

    notes: list[tuple[str, str]] = []
    accession_no = str(current.get("accession_no") or "")
    ledger = next(
        (row for row in filing_rows if str(row.get("accession_no") or "") == accession_no),
        None,
    )
    if ledger is not None:
        status = str(ledger.get("status") or "")
        if status == "unsupported":
            notes.append(("warning", "지원하지 않는 공시 형식이라 재무 행을 만들지 않았습니다."))
        elif status == "empty":
            notes.append(("warning", "수집은 됐지만 추출된 재무 행이 없습니다."))
        rows_count = finite_number(ledger.get("rows_count"))
        if status == "parsed" and rows_count is not None and rows_count <= 0:
            notes.append(("warning", "파싱 행 수가 0입니다 — 값이 비어 보일 수 있습니다."))
    elif accession_no:
        notes.append(("warning", "이 공시의 수집 장부 기록을 찾지 못했습니다."))

    pending_splits = [
        row for row in (quality.get("splits") or [])
        if str(row.get("status") or "") != "complete"
    ]
    if pending_splits:
        dates = ", ".join(str(row.get("action_date")) for row in pending_splits[:3])
        notes.append((
            "warning",
            f"분할 보정이 끝나지 않았습니다({dates}) — 과거 주가·주식수 기준이 어긋날 수 있습니다.",
        ))

    issuer_rows = quality.get("issuer") or []
    if issuer_rows and issuer_rows[0].get("valuation_supported") is False:
        notes.append((
            "warning",
            "같은 발행사(CIK)에 추적 종목이 여럿이라 주식수 기준이 모호합니다 — "
            "시가총액·EV 기반 배수를 그대로 믿지 마세요.",
        ))

    if notified is False:
        notes.append(("info", "이 공시는 아직 Discord로 발송되지 않았습니다."))
    return notes


def _render_trust_notes(notes: list[tuple[str, str]]) -> None:
    if not notes:
        st.caption(":green[●] 수집·매핑 경고 없음")
        return
    for level, text in notes:
        if level == "error":
            st.error(text, icon=":material/error:")
        elif level == "warning":
            st.warning(text, icon=":material/rule:")
        else:
            st.info(text, icon=":material/info:")


def _render_discord_full(
    *,
    active_watchlist: list[str],
    core_rows: list[dict[str, Any]],
    ticker_profiles: list[dict[str, Any]],
) -> None:
    """실제 Discord 실적 카드 근거를 선택한 한 섹션씩만 표시한다."""

    ticker = _select_ticker(active_watchlist, key="earnings_discord_ticker")
    if not ticker:
        return

    all_ticker_core = [
        row
        for row in _ticker_rows(core_rows, ticker)
        if str(row.get("fiscal_period") or "") in {"Q1", "Q2", "Q3", "Q4", "FY"}
    ]
    filing_groups: dict[str, list[dict[str, Any]]] = {}
    for row in all_ticker_core:
        filing_groups.setdefault(discord_candidates.row_accession_no(row), []).append(row)
    ticker_core = sorted(
        [discord_candidates.pick_headline(rows) for rows in filing_groups.values()],
        key=lambda row: (str(row.get("period_end") or ""), str(row.get("filed_at") or "")),
        reverse=True,
    )
    if not ticker_core:
        st.info(f"{ticker}의 Discord 카드 기준 financial_versions 행이 없습니다.")
        return

    event_index = st.selectbox(
        "Discord 공시 카드",
        range(len(ticker_core)),
        format_func=lambda index: (
            f"FY{ticker_core[index].get('fiscal_year') or '—'} "
            f"{ticker_core[index].get('fiscal_period') or '—'} · "
            f"기간말 {ticker_core[index].get('period_end') or '—'} · "
            f"공시 {ticker_core[index].get('filed_at') or '—'}"
        ),
        key=f"earnings_discord_event:{ticker}",
    )
    current = ticker_core[event_index]
    profile = next(
        (
            row
            for row in ticker_profiles
            if str(row.get("ticker") or "").upper() == ticker
        ),
        {},
    )
    current_fiscal_year = _number(current.get("fiscal_year"))
    previous = (
        next(
            (
                row
                for row in all_ticker_core
                if _number(row.get("fiscal_year")) == current_fiscal_year - 1.0
                and str(row.get("fiscal_period")) == str(current.get("fiscal_period"))
            ),
            None,
        )
        # 회계연도를 모르면 전년 동기를 추측하지 않는다 (0으로 대체하면 엉뚱한 행이 붙는다).
        if current_fiscal_year is not None
        else None
    )
    quarter_history = sorted(
        [
            row
            for row in all_ticker_core
            if str(row.get("fiscal_period")) in {"Q1", "Q2", "Q3", "Q4"}
            and str(row.get("period_end") or "") <= str(current.get("period_end") or "")
        ],
        key=lambda row: str(row.get("period_end") or ""),
    )[-13:]

    section = view_selector(
        "카드 섹션",
        (
            "요약",
            "실적·현금흐름",
            "가격·밸류",
            "건전성·이익의 질",
            "기술·주주환원",
            "세그먼트",
        ),
        key=f"earnings_discord_section:{ticker}:{event_index}",
        default="요약",
    )

    # 선택한 섹션의 실제 SELECT만 실행한다.
    support_result = load_earnings_discord_support(ticker, section=section)
    support_available = result_status(
        support_result,
        empty_text=f"{ticker}의 {section} 근거가 없습니다",
    )
    if not support_available and not (
        support_result.status == "empty" and section in {"카드 요약", "실적·현금흐름"}
    ):
        return
    if support_result.message:
        st.warning(f"부분 연결 실패 · {support_result.message}")
    support = result_payload(support_result, default={}) or {}

    period_cutoff = str(current.get("period_end") or "")
    # 건전성·수익성·성장률은 canonical 원장 값에서 계산 가능한 범위만 표시한다.
    metric_rows = [
        row for row in support.get("metrics", [])
        if str(row.get("period_end") or "") <= period_cutoff
    ]
    ttm_rows = [
        row for row in support.get("ttm", [])
        if str(row.get("period_end") or "") <= period_cutoff
    ]
    valuation_rows = [
        row for row in support.get("valuation", [])
        if str(row.get("period_end") or "") <= period_cutoff
    ]
    metrics = _latest_row(metric_rows)
    ttm = _latest_row(ttm_rows)
    valuation = _latest_row(valuation_rows)
    health = dict(metrics)
    if health.get("altman_z") is None and health.get("altman_z_double_prime") is not None:
        health["altman_z"] = health["altman_z_double_prime"]

    # 요약 화면에서만 신뢰도 사실을 읽는다. 다른 섹션에서는 조회하지 않는다.
    quality_payload: dict[str, list[dict[str, Any]]] = {}
    notified_flag: bool | None = None
    if section == "요약":
        quality_result = load_ticker_data_quality(ticker)
        if quality_result.status in {"ok", "empty"}:
            quality_payload = result_payload(quality_result, default={}) or {}

    expectation: dict[str, Any] = {}


    prices_before_filing: list[dict[str, Any]] = []
    shares_before_filing: list[tuple[str, float]] = []
    if section in {"가격·밸류", "기술·주주환원"}:
        prices_before_filing = discord_charts.prices_before_filing(
            list(support.get("price_history", [])),
            current.get("filed_at"),
        )
        shares_before_filing = sorted(
            [
                (str(row.get("as_of_date")), float(row["shares"]))
                for row in support.get("shares_outstanding_history", [])
                if row.get("as_of_date")
                and row.get("shares") is not None
                and str(row.get("as_of_date")) < str(current.get("filed_at") or "")
            ],
            key=lambda item: item[0],
        )

    if section in {"요약", "카드 요약"}:
        derived = _safe_discord_derived(current, previous)
        badge, _badge_color, grade_label = discord_grade(
            derived,
            has_anomaly=False,
        )
        name_ko = profile.get("name_ko")
        name_en = profile.get("name")
        title = name_ko or name_en or ticker
        st.subheader(f"{title} ({ticker})")
        if name_en and name_en != title:
            st.caption(str(name_en))
        with st.container(horizontal=True):
            st.metric("Discord 등급", badge, grade_label, border=True)
            st.metric("매출", display_money(derived.get("revenue")), display_percent(derived.get("revenue_yoy"), signed=True), border=True)
            st.metric("순이익", display_money(derived.get("net_income")), display_percent(derived.get("net_income_yoy"), signed=True), border=True)
            st.metric("FCF", display_money(derived.get("fcf")), border=True)
        with st.container(border=True):
            st.write(
                f"FY{current.get('fiscal_year') or '—'} {current.get('fiscal_period') or '—'} · "
                f"{current.get('form_type') or '—'} · 기간말 {current.get('period_end') or '—'} · "
                f"공시 {current.get('filed_at') or '—'}"
            )
            st.write(
                f"매출총이익률 · {display_percent(derived.get('gross_margin'))} · "
                f"영업이익률 · {display_percent(derived.get('operating_margin'))} · "
                f"순이익률 · {display_percent(derived.get('net_margin'))}"
            )
            st.write(
                f"현금 · {display_money(derived.get('cash'))} · "
                f"순부채 · {display_money(derived.get('net_debt'))} · "
                f"자사주 매입 · {display_money(derived.get('buyback'))} · "
                f"배당 지급 · {display_money(derived.get('dividends'))}"
            )
            if derived.get("fcf") is None and (
                current.get("net_cash_from_operating_activities") is None
                or current.get("capital_expenses") is None
            ):
                st.caption("FCF 데이터 없음 · 영업현금흐름과 CapEx가 모두 있을 때만 계산")
            if derived.get("net_debt") is None:
                st.caption("순부채 데이터 없음 · 부채와 현금이 모두 확인될 때만 계산")
            _render_trust_notes(
                _filing_trust_notes(
                    current,
                    filing_rows,
                    quality_payload,
                    notified_flag,
                )
            )
            source_note(
                SOURCE_DB,
                SOURCE_CALC,
                observed_at=current.get("filed_at"),
                detail="reporting.earnings.metrics.derive + thresholds.grade 동일 규칙",
            )

        coverage = [
            {"Discord 섹션": label, "조회 방식": "선택 시 해당 DB 근거만 조회"}
            for label in (
                "시장 기대",
                "실적·현금흐름",
                "가격·밸류",
                "건전성·이익의 질",
                "기술·주주환원",
                "세그먼트",
            )
        ]
        dataframe(coverage, key=f"earnings_discord_coverage:{ticker}:{event_index}")

    if section in {"요약", "시장 기대"}:
        if not expectation:
            st.info("공시 전 120일 안의 observed 컨센서스·목표주가가 없어 시장 기대 블록을 만들지 않습니다.")
        else:
            eps = expectation.get("eps") or {}
            revenue = expectation.get("revenue") or {}
            with st.container(horizontal=True):
                st.metric("조정 EPS 실제", display_number(eps.get("actual")), border=True)
                st.metric("조정 EPS 예상", display_number(eps.get("estimate")), border=True)
                st.metric("EPS surprise", display_percent(eps.get("surprise"), signed=True), border=True)
                st.metric("매출 surprise", display_percent(revenue.get("surprise"), signed=True), border=True)
            st.write(
                f"EPS 범위 · {display_number(eps.get('low'))} ~ {display_number(eps.get('high'))} · "
                f"분석가 {eps.get('analysts') if eps.get('analysts') is not None else '—'} · "
                f"범위 내 위치 {display_percent(eps.get('position'))} · "
                f"기준 신뢰 {'정상' if eps.get('reliable') else '확인 필요'}"
            )
            st.write(
                f"매출 실제/예상 · {display_money(revenue.get('actual'))} / {display_money(revenue.get('estimate'))} · "
                f"범위 {display_money(revenue.get('low'))} ~ {display_money(revenue.get('high'))} · "
                f"분석가 {revenue.get('analysts') if revenue.get('analysts') is not None else '—'}"
            )
            revisions = expectation.get("revisions") or {}
            if revisions:
                st.caption(
                    f"리비전 7일 상향/하향 · {revisions.get('up_7d', '—')} / {revisions.get('down_7d', '—')} · "
                    f"30일 · {revisions.get('up', '—')} / {revisions.get('down', '—')} · net {revisions.get('net', '—')}"
                )
                st.info(discord_card.revisions_text(revisions))
                if any(
                    recent is not None and window is not None and int(recent) > int(window)
                    for recent, window in (
                        (revisions.get("up_7d"), revisions.get("up")),
                        (revisions.get("down_7d"), revisions.get("down")),
                    )
                ):
                    st.warning("7일 리비전 수가 30일 수보다 큰 provider 불일치가 있습니다. 원값을 수정하지 않았습니다.")
            next_quarter = expectation.get("next_quarter") or {}
            target = expectation.get("price_target") or {}
            if next_quarter:
                st.write(
                    f"다음 분기 · {next_quarter.get('label') or '—'} · EPS {display_number(next_quarter.get('estimate'))} · "
                    f"매출 {display_money(next_quarter.get('revenue'))} · 분석가 {next_quarter.get('analysts') or '—'}"
                )
            if target:
                st.write(
                    f"공시 전 목표주가 · 평균 {display_money(target.get('mean'))} · "
                    f"중앙 {display_money(target.get('median'))} · 범위 {display_money(target.get('low'))} ~ "
                    f"{display_money(target.get('high'))} · 상승여력 {display_percent(target.get('upside'), signed=True)}"
                )
            dataframe(expectation.get("history") or [], key=f"earnings_discord_surprise_history:{ticker}:{event_index}")
            source_note(
                SOURCE_DB,
                SOURCE_CALC,
                observed_at=expectation.get("snapshot_date"),
                detail="observed snapshot · 공시 전 · 최대 120일 · 정확한 회계기간 키",
            )

    if section == "실적·현금흐름":
        calculation_blocks = (
            "매출·마진·건전성 복합",
            "EPS 13분기",
            "현금흐름 분기",
            "손익 워터폴",
            "현금흐름 브리지",
            "운전자본",
        )
        block = st.selectbox(
            "Discord 계산 블록",
            calculation_blocks,
            key=f"earnings_discord_calculation:{ticker}:{event_index}",
        )
        if block == "매출·마진·건전성 복합":
            context = discord_charts.combo(
                quarter_history,
                sorted(metric_rows, key=lambda row: str(row.get("period_end") or "")),
                (expectation or {}).get("revenue"),
                (expectation or {}).get("next_quarter"),
            )
        elif block == "EPS 13분기":
            context = discord_charts.eps_trend(quarter_history, expectation)
        elif block == "현금흐름 분기":
            context = discord_charts.cashflow_quarters(quarter_history)
        elif block == "손익 워터폴":
            context = discord_charts.income_waterfall(current, previous)
        elif block == "현금흐름 브리지":
            if _cashflow_bridge_ready(current):
                bridge_previous = previous if _cashflow_bridge_ready(previous) else None
                context = discord_charts.cashflow_bridge(current, bridge_previous)
            else:
                context = None
                st.warning(
                    "현금흐름 브리지 생략 · 순이익·영업현금흐름·감가상각·주식보상·CapEx 중 "
                    "하나 이상이 없어 0으로 대체하지 않습니다."
                )
        else:
            context = discord_charts.working_capital(current, quarter_history)
        if context:
            st.json(context, expanded=False)
        else:
            st.info(f"{block}에 필요한 실제 분기 값이 충분하지 않습니다.")
        core_columns = [
            "fiscal_year", "fiscal_period", "period_end", "filed_at", "revenue",
            "gross_profit", "operating_income_loss", "net_income",
            "net_cash_from_operating_activities", "capital_expenses",
            "cash_and_cash_equivalents", "trade_receivables", "inventories", "trade_payables",
        ]
        dataframe(
            [{column: row.get(column) for column in core_columns} for row in quarter_history],
            key=f"earnings_discord_quarter_history:{ticker}:{event_index}",
        )
        source_note(SOURCE_DB, SOURCE_CALC, detail="Discord charts 순수 계산 컨텍스트 · 현재 세션에서만 생성")

    elif section == "가격·밸류":
        valuation_view = view_selector(
            "밸류에이션 보기",
            ("공시 시점 배수", "7년 일별 분포"),
            key=f"earnings_valuation_view:{ticker}:{event_index}",
            default="공시 시점 배수",
        )
        if valuation_view == "공시 시점 배수" and not valuation_rows:
            st.info("선택 공시 시점까지의 저장 밸류에이션 행이 없습니다.")
        elif valuation_view == "공시 시점 배수":
            valuation = _latest_row(valuation_rows)
            with st.container(horizontal=True):
                st.metric("공시 기준 주가", display_money(valuation.get("price")), border=True)
                st.metric("시가총액", display_money(valuation.get("market_cap")), border=True)
                st.metric("기업가치", display_money(valuation.get("enterprise_value")), border=True)
                st.metric("PER (TTM)", display_number(valuation.get("pe_ttm")), border=True)
            metric_labels = {
                "pe_ttm": "PER",
                "pb": "PBR",
                "ps_ttm": "PSR",
                "ev_to_ebitda": "EV/EBITDA",
                "ev_to_sales": "EV/Sales",
                "fcf_yield": "FCF yield",
                "dividend_yield": "Dividend yield",
            }
            selected_metric = st.selectbox(
                "밸류에이션 지표",
                list(metric_labels),
                format_func=lambda key: metric_labels[key],
                key=f"earnings_valuation_metric:{ticker}:{event_index}",
            )
            valuation_frame = pd.DataFrame(valuation_rows).sort_values("period_end")
            valuation_frame[selected_metric] = pd.to_numeric(valuation_frame[selected_metric], errors="coerce")
            valuation_frame = valuation_frame.dropna(subset=[selected_metric])
            if valuation_frame.empty:
                st.info(f"{metric_labels[selected_metric]} 실제 값이 없습니다.")
            else:
                figure = go.Figure(
                    go.Scatter(
                        x=valuation_frame["period_end"],
                        y=valuation_frame[selected_metric],
                        mode="lines+markers",
                        line={"color": PRIMARY, "width": 3},
                        name=metric_labels[selected_metric],
                    )
                )
                figure.update_layout(**plotly_layout(height=400))
                st.plotly_chart(figure, width="stretch", config={"displaylogo": False})
            if valuation.get("valuation_supported") is False:
                st.warning("issuer 수준 주식수 기준이 모호해 저장 뷰가 valuation_supported=false로 표시했습니다.")
            source_note(SOURCE_DB, observed_at=valuation.get("price_date"), detail="시점 가격·주식수·공시된 TTM만 사용")
        else:
            history = _historical_valuation(
                ticker=ticker,
                current=current,
                core_rows=core_rows,
                valuation_rows=valuation_rows,
                metric_rows=metric_rows,
                price_rows=prices_before_filing,
                share_rows=shares_before_filing,
            )
            historical_card = discord_charts.valuation_history(history)
            if not history or not historical_card:
                st.info(
                    "공시일 이전 가격·발행주식수·공시일이 확인된 TTM 스냅샷이 충분하지 않아 "
                    "역사 밸류 분포를 만들지 않습니다."
                )
            else:
                st.caption(
                    f"가용 기간 · 약 {historical_card.get('span_years') or '—'}년 · "
                    "거래일별 종가 × 당시 유효 발행주식수"
                )
                history_rows = []
                for row in historical_card.get("rows", []):
                    history_rows.append(
                        {
                            "지표": row.get("label"),
                            "현재": row.get("value"),
                            "최장 기간 중앙값": row.get("median"),
                            "5%": row.get("lo_label"),
                            "95%": row.get("hi_label"),
                            "현재 백분위": (
                                f"{row.get('pct')}%" if row.get("pct") is not None else "—"
                            ),
                            "가용 기간": f"{row.get('prim_years') or '—'}년",
                            "기간별 중앙값": " · ".join(
                                f"{item.get('y')}년 {item.get('value') or '—'}"
                                for item in row.get("windows", [])
                            ),
                        }
                    )
                dataframe(
                    history_rows,
                    key=f"earnings_valuation_history:{ticker}:{event_index}",
                )
                pe_spark = list(history.get("pe_spark") or [])
                if pe_spark:
                    spark_frame = pd.DataFrame(pe_spark, columns=["date", "PER"])
                    figure = go.Figure(
                        go.Scatter(
                            x=spark_frame["date"],
                            y=spark_frame["PER"],
                            mode="lines",
                            line={"color": PRIMARY, "width": 2},
                            name="주간 PER",
                        )
                    )
                    figure.update_layout(**plotly_layout(height=330))
                    st.plotly_chart(figure, width="stretch", config={"displaylogo": False})
                source_note(
                    SOURCE_DB,
                    SOURCE_CALC,
                    observed_at=prices_before_filing[-1].get("trade_date") if prices_before_filing else None,
                    detail=(
                        "reporting.earnings.valuation_history와 동일 규칙 · available_date=filed_at as-of · "
                        "미래 공시 사용 금지 · 1/3/5/7년 중앙값·분위"
                    ),
                )

    elif section == "건전성·이익의 질":
        if True:
            current_blocks = {
                "Discord 건전성 게이지": discord_charts.gauges(health),
                "수익성·자본효율": discord_charts.quality(health),
                "이익의 질": discord_charts.earnings_quality({**metrics, **ttm}),
            }
            for label, rows in current_blocks.items():
                st.markdown(f"**{label}**")
                if rows:
                    dataframe(rows, key=f"earnings_quality:{ticker}:{event_index}:{label}")
                else:
                    st.info(f"{label}에 필요한 실제 값이 없습니다.")
        source_note(SOURCE_DB, SOURCE_CALC, observed_at=(metrics or ttm).get("period_end"))

    elif section == "기술·주주환원":
        if not prices_before_filing:
            st.info("공시일 이전의 저장 가격 이력이 없어 기술·주주환원 블록을 만들지 않습니다.")
        else:
            technical_snapshot = discord_charts.technical_snapshot(prices_before_filing)
            technical_rows = discord_charts.technicals(technical_snapshot, prices_before_filing) or []
            shareholder_rows = discord_charts.shareholder_return(prices_before_filing, shares_before_filing) or []
            st.markdown("**주가·기술**")
            if technical_rows:
                dataframe(technical_rows, key=f"earnings_technicals:{ticker}:{event_index}")
            else:
                st.info("Discord 기술 지표에 필요한 실제 가격 기간이 부족합니다.")
            st.markdown("**주주환원**")
            if shareholder_rows:
                dataframe(shareholder_rows, key=f"earnings_shareholder:{ticker}:{event_index}")
            else:
                st.info("TTM 배당 또는 비교 가능한 발행주식수 이력이 없습니다.")
            price_frame = pd.DataFrame(prices_before_filing)
            price_frame["close"] = pd.to_numeric(price_frame["close"], errors="coerce")
            price_frame = price_frame.dropna(subset=["close"])
            if not price_frame.empty:
                figure = go.Figure(
                    go.Scatter(
                        x=price_frame["trade_date"],
                        y=price_frame["close"],
                        mode="lines",
                        line={"color": PRIMARY, "width": 2},
                        name="공시 전 종가",
                    )
                )
                if technical_snapshot and technical_snapshot.get("sma_200") is not None:
                    figure.add_hline(
                        y=float(technical_snapshot["sma_200"]),
                        line_dash="dot",
                        line_color=MUTED,
                        annotation_text="SMA200",
                    )
                figure.update_layout(**plotly_layout(height=420))
                st.plotly_chart(figure, width="stretch", config={"displaylogo": False})
            dividend_context = discord_charts.dividend_trend(prices_before_filing)
            price_range = discord_charts.week52_range(
                technical_snapshot,
                (expectation or {}).get("price_target"),
            )
            context_choice = st.selectbox(
                "추가 카드 값",
                ("52주·목표주가 범위", "배당 추이", "발행주식수 이력"),
                key=f"earnings_market_context:{ticker}:{event_index}",
            )
            if context_choice == "52주·목표주가 범위":
                st.json(price_range or {"상태": "필요한 실제 값 없음"}, expanded=False)
            elif context_choice == "배당 추이":
                if not dividend_context or not dividend_context.get("bars"):
                    st.info("해당 공시 시점 기준 최근 배당금 지급 이력이 없습니다.")
                else:
                    bars = dividend_context.get("bars", [])
                    c1, c2, c3, c4 = st.columns(4)
                    latest_dps = bars[-1].get("dps") if bars else None
                    latest_yield = bars[-1].get("yield_pct") if bars else None
                    c1.metric("최신 주당배당금 (DPS)", f"${latest_dps:.2f}" if latest_dps is not None else "—")
                    c2.metric("최신 배당수익률", f"{latest_yield:.2f}%" if latest_yield is not None else "—")
                    freq = dividend_context.get("frequency")
                    freq_str = f"연 {freq}회" if freq else "불규칙"
                    c3.metric("지급 주기", freq_str)
                    cagr = dividend_context.get("dps_cagr_pct")
                    c4.metric("5개년 DPS CAGR", f"{cagr:+.1f}%" if cagr is not None else "—")

                    from plotly.subplots import make_subplots
                    fig = make_subplots(specs=[[{"secondary_y": True}]])
                    months = [b.get("month_label") for b in bars]
                    dps_vals = [b.get("dps") for b in bars]
                    yield_vals = [b.get("yield_pct") for b in bars]

                    fig.add_trace(
                        go.Bar(
                            x=months,
                            y=dps_vals,
                            name="주당 배당금 ($)",
                            marker_color=PRIMARY,
                            text=[f"${d:.2f}" for d in dps_vals],
                            textposition="auto",
                        ),
                        secondary_y=False,
                    )
                    fig.add_trace(
                        go.Scatter(
                            x=months,
                            y=yield_vals,
                            name="시가 배당수익률 (%)",
                            mode="lines+markers",
                            line={"color": UP, "width": 2},
                            marker={"size": 6},
                        ),
                        secondary_y=True,
                    )
                    fig.update_layout(
                        **plotly_layout(height=380),
                        title="최근 5개년 월별 배당금(DPS) 및 시가배당수익률 추이",
                        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
                    )
                    fig.update_yaxes(title_text="주당 배당금 ($)", secondary_y=False)
                    fig.update_yaxes(title_text="배당수익률 (%)", secondary_y=True)
                    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})

                    dataframe(
                        [
                            {
                                "지급월": b.get("month_label"),
                                "주당 배당금 (DPS)": f"${b.get('dps'):.2f}",
                                "주가 (Filing 전)": f"${b.get('price'):.2f}" if b.get("price") else "—",
                                "시가 배당수익률": f"{b.get('yield_pct'):.2f}%" if b.get("yield_pct") else "—",
                            }
                            for b in reversed(bars)
                        ],
                        key=f"earnings_dividend_history:{ticker}:{event_index}",
                    )
            else:
                dataframe(
                    [{"기준일": day, "발행주식수": shares} for day, shares in shares_before_filing],
                    key=f"earnings_shares_history:{ticker}:{event_index}",
                )
            source_note(SOURCE_DB, SOURCE_CALC, observed_at=prices_before_filing[-1].get("trade_date"), detail="공시 당일 반응 제외")

    elif section == "세그먼트":
        accession_no = str(current.get("accession_no") or "").strip()
        try:
            fiscal_year = int(current.get("fiscal_year"))
        except (TypeError, ValueError):
            st.info("선택 공시의 회계연도가 없어 세그먼트를 연결하지 않습니다.")
            return
        fiscal_period = str(current.get("fiscal_period") or "")
        target = (ticker, accession_no, fiscal_year, fiscal_period)
        filing_states = {
            (str(row.get("ticker") or ""), str(row.get("accession_no") or "")): row
            for row in support.get("segment_processing", [])
            if row.get("ticker") and row.get("accession_no")
        }
        segment_state = {"status": "empty", "axes": []}

        filing_state = filing_states.get((ticker, accession_no), {})
        st.caption(
            f"segment filing · {segment_state.get('status') or filing_state.get('status') or '상태 없음'} · "
            f"mapping {filing_state.get('mapping_version') or '—'} · "
            f"updated {filing_state.get('updated_at') or '—'}"
        )
        axes = list(segment_state.get("axes") or [])
        if segment_state.get("status") not in {"verified", "partial"} or not axes:
            st.info(
                "선택 공시에 Discord 품질 규칙을 통과한 세그먼트 축이 없습니다. "
                "미지원 또는 품질 기준 미통과 상태는 차트로 만들지 않습니다."
            )
        else:
            axis_index = st.selectbox(
                "세그먼트 축",
                range(len(axes)),
                format_func=lambda index: (
                    f"{axes[index].get('type_label') or '세그먼트'} · "
                    f"{axes[index].get('axis') or '미분류'}"
                ),
                key=f"earnings_segment_axis:{ticker}:{event_index}",
            )
            selected_axis = axes[axis_index]
            selected_segments = [
                {
                    "세그먼트": row.get("name"),
                    "매출": row.get("revenue"),
                    "비중": display_percent(row.get("revenue_pct")),
                    "매출 YoY": display_percent(row.get("revenue_yoy"), signed=True),
                    "부문이익": row.get("profit_loss"),
                    "이익률": display_percent(row.get("profit_margin")),
                    "이익 정의": row.get("profit_measure_label"),
                    "이익 YoY": display_percent(row.get("profit_yoy"), signed=True),
                    "매출 품질": row.get("quality_status"),
                    "이익 품질": row.get("profit_quality_status"),
                }
                for row in selected_axis.get("rows", [])
            ]
            st.caption(
                f"coverage · {display_percent(selected_axis.get('coverage_ratio'))} · "
                f"원 세그먼트 {selected_axis.get('member_count') or '—'}개 · "
                f"상위 {selected_axis.get('shown_count') or '—'}개 + 기타 집계"
            )
            dataframe(selected_segments, key=f"earnings_segments:{ticker}:{event_index}:{axis_index}")
            chart_rows = [
                row for row in selected_axis.get("rows", [])
                if _number(row.get("revenue")) is not None
            ]
            if chart_rows:
                figure = go.Figure(
                    go.Bar(
                        x=[row.get("name") for row in chart_rows],
                        y=[_number(row.get("revenue")) for row in chart_rows],
                        marker_color=PRIMARY,
                        name="세그먼트 매출",
                    )
                )
                figure.update_layout(**plotly_layout(height=400))
                st.plotly_chart(figure, width="stretch", config={"displaylogo": False})
            source_note(
                SOURCE_DB,
                SOURCE_CALC,
                observed_at=filing_state.get("updated_at"),
                detail="segment_state.build 동일 규칙 · verified/partial · best axis · 기타 집계",
            )

def _usable_segment_value(row: dict[str, Any], value_key: str, status_key: str) -> float | None:
    """품질 게이트를 통과한 세그먼트 숫자만 반환한다(통과 못하면 차트에 올리지 않는다)."""

    if str(row.get(status_key) or "") not in {"verified", "partial"}:
        return None
    return _number(row.get(value_key))


def _non_empty_columns(rows: list[dict[str, Any]], identity: tuple[str, ...]) -> list[str]:
    """이 종목에 실제 값이 하나라도 있는 컬럼만 남긴다(업종별로 채워지는 계정이 다르다)."""

    present: list[str] = []
    for column in {key for row in rows for key in row} - set(identity):
        if any(row.get(column) is not None for row in rows):
            present.append(column)
    return sorted(present)


def _render_growth(rows: list[dict[str, Any]], *, ticker: str) -> None:
    """분기 wide 행에서 만든 YoY·마진 변화 전 구간. Discord는 현재 분기 하나만 싣는다."""

    quarters = quarter_growth(rows)
    if not quarters:
        st.info(f"{ticker}의 분기 financial_versions 행이 없습니다.")
        return
    latest = quarters[-1]
    with st.container(horizontal=True, gap="small"):
        st.metric("매출 YoY", display_percent(latest.get("revenue_yoy"), signed=True), border=True)
        st.metric("순이익 YoY", display_percent(latest.get("net_income_yoy"), signed=True), border=True)
        st.metric(
            "영업이익률 변화",
            display_percent(latest.get("operating_margin_delta_yoy"), signed=True),
            border=True,
        )
        st.metric(
            "매출총이익률 변화",
            display_percent(latest.get("gross_margin_delta_yoy"), signed=True),
            border=True,
        )
    source_note(
        SOURCE_DB,
        SOURCE_CALC,
        observed_at=latest.get("period_end"),
        detail="fundamentals.financial_versions 전년 동기 대비 · 전년 행이 없으면 —로 남긴다",
    )

    metric_labels = {
        "revenue_yoy": "매출 YoY",
        "net_income_yoy": "순이익 YoY",
        "operating_margin_delta_yoy": "영업이익률 변화(pp)",
        "gross_margin_delta_yoy": "매출총이익률 변화(pp)",
    }
    figure = go.Figure()
    palette = (PRIMARY, TEXT, MUTED, UP)
    for (column, label), color in zip(metric_labels.items(), palette, strict=True):
        series = [_number(row.get(column)) for row in quarters]
        if all(value is None for value in series):
            continue
        figure.add_trace(
            go.Scatter(
                x=[row.get("period_end") for row in quarters],
                y=series,
                name=label,
                mode="lines+markers",
                line={"color": color, "width": 2},
                connectgaps=False,
            )
        )
    if figure.data:
        figure.update_layout(**plotly_layout(height=420), yaxis_tickformat=".1%")
        st.plotly_chart(figure, width="stretch", config={"displaylogo": False})
    else:
        st.info("표시할 수 있는 저장 성장률 값이 없습니다.")
    dataframe(
        [
            {
                "회계연도": row.get("fiscal_year"),
                "기간": row.get("fiscal_period"),
                "결산일": row.get("period_end"),
                **{label: row.get(column) for column, label in metric_labels.items()},
            }
            for row in reversed(quarters)
        ],
        key=f"earnings_growth_table:{ticker}",
    )
    source_note(SOURCE_DB, detail="결측은 —로 남기고 0으로 바꾸지 않는다")


def _render_industry_specific(rows: list[dict[str, Any]], *, ticker: str) -> None:
    """financial_versions에 저장된 업종 특수 계정. Discord 카드에는 아예 없는 데이터다."""

    identity = ("ticker", "fiscal_year", "fiscal_period", "accession_no", "form_type",
                "period_end", "filed_at", "mapping_version", "ingested_at")
    if not rows:
        st.info(f"{ticker}의 fundamentals.financial_versions 행이 없습니다.")
        return
    columns = _non_empty_columns(rows, identity)
    if not columns:
        st.info(
            f"{ticker}은 업종 특수 계정(순이자이익·대손충당·대출채권·예수금)을 "
            "보고하지 않습니다. 은행·금융 업종에만 채워지는 계정입니다."
        )
        return
    ordered = sorted(rows, key=lambda row: str(row.get("period_end") or ""))
    st.caption(
        f"채워진 업종 특수 계정 · {len(columns)}개 · "
        f"기간 {ordered[0].get('period_end') or '—'} ~ {ordered[-1].get('period_end') or '—'}"
    )
    selected_column = st.selectbox(
        "업종 특수 계정",
        columns,
        key=f"earnings_industry_column:{ticker}",
    )
    series = [(row.get("period_end"), _number(row.get(selected_column))) for row in ordered]
    points = [(period, value) for period, value in series if value is not None]
    if points:
        figure = go.Figure(
            go.Bar(
                x=[period for period, _value in points],
                y=[value for _value_period, value in points],
                marker_color=PRIMARY,
                name=selected_column,
            )
        )
        figure.update_layout(**plotly_layout(height=380))
        st.plotly_chart(figure, width="stretch", config={"displaylogo": False})
    else:
        st.info(f"{selected_column}의 실제 값이 없습니다.")
    dataframe(
        [
            {
                "회계연도": row.get("fiscal_year"),
                "기간": row.get("fiscal_period"),
                "결산일": row.get("period_end"),
                "공시일": row.get("filed_at"),
                "form_type": row.get("form_type"),
                **{column: row.get(column) for column in columns},
            }
            for row in reversed(ordered)
        ],
        key=f"earnings_sector_table:{ticker}",
    )
    source_note(
        SOURCE_DB,
        observed_at=ordered[-1].get("ingested_at") or ordered[-1].get("filed_at"),
        detail="fundamentals.financial_versions · 종목이 실제로 보고한 계정만 컬럼으로 남김",
    )


def _render_stored_technicals(
    *,
    ticker: str,
    tech_daily: list[dict[str, Any]],
    tech_view: list[dict[str, Any]],
    oscillators: list[dict[str, Any]],
) -> None:
    """저장된 기술 지표(RSI/MACD + 뷰 계산). 카드의 공시 시점 스냅샷과 별개다."""

    if not tech_daily and not tech_view and not oscillators:
        st.info(
            f"{ticker}의 저장된 기술 지표가 없습니다. "
            "Research 로컬 feature가 아직 적재되지 않았습니다."
        )
        return
    trend = sorted(tech_view, key=lambda row: str(row.get("trade_date") or ""))
    momentum = sorted(tech_daily, key=lambda row: str(row.get("trade_date") or ""))
    swing = sorted(oscillators, key=lambda row: str(row.get("trade_date") or ""))
    latest_trend = trend[-1] if trend else {}
    latest_momentum = momentum[-1] if momentum else {}
    latest_swing = swing[-1] if swing else {}

    with st.container(horizontal=True, gap="small"):
        st.metric("종가", display_money(latest_trend.get("close")), border=True)
        st.metric("RSI 14", display_number(latest_momentum.get("rsi14")), border=True)
        st.metric(
            "MACD · 시그널",
            f"{display_number(latest_momentum.get('macd'))} · "
            f"{display_number(latest_momentum.get('macd_signal'))}",
            border=True,
        )
        st.metric("50/200 추세", str(latest_trend.get("ma_trend_50_200") or "—"), border=True)
    with st.container(horizontal=True, gap="small"):
        st.metric("52주 고가", display_money(latest_trend.get("high_52w")), border=True)
        st.metric("52주 저가", display_money(latest_trend.get("low_52w")), border=True)
        st.metric("연환산 변동성 20일", display_percent(latest_trend.get("hist_vol_20_ann")), border=True)
        st.metric("스토캐스틱 %K", display_number(latest_swing.get("stoch_k_14")), border=True)
    source_note(
        SOURCE_DB,
        observed_at=(
            latest_momentum.get("trade_date")
            or latest_trend.get("trade_date")
            or latest_swing.get("trade_date")
        ),
        detail="Research DuckDB feature_signals_daily(저장) · 비재귀 지표는 필요 시 계산",
    )

    block = view_selector(
        "지표 블록",
        ("추세·채널", "모멘텀"),
        key=f"earnings_tech_block:{ticker}",
        default="추세·채널",
    )
    if block == "추세·채널":
        if not trend:
            st.info("비재귀 추세 feature는 아직 저장하지 않아 추세 차트를 만들지 않습니다.")
            return
        figure = go.Figure()
        for column, label, color, width in (
            ("close", "종가", PRIMARY, 2),
            ("sma_20", "SMA20", TEXT, 1),
            ("sma_50", "SMA50", MUTED, 1),
            ("sma_200", "SMA200", UP, 1),
        ):
            values = [_number(row.get(column)) for row in trend]
            if all(value is None for value in values):
                continue
            figure.add_trace(
                go.Scatter(
                    x=[row.get("trade_date") for row in trend],
                    y=values,
                    name=label,
                    mode="lines",
                    line={"color": color, "width": width},
                    connectgaps=False,
                )
            )
        figure.update_layout(**plotly_layout(height=430))
        st.plotly_chart(figure, width="stretch", config={"displaylogo": False})
        source_note(SOURCE_DB, observed_at=latest_trend.get("trade_date"))
    elif block == "모멘텀":
        if not momentum:
            st.info("Research feature 행이 없어 모멘텀 차트를 만들지 않습니다.")
            return
        figure = go.Figure()
        figure.add_trace(
            go.Scatter(
                x=[row.get("trade_date") for row in momentum],
                y=[_number(row.get("rsi14")) for row in momentum],
                name="RSI 14",
                mode="lines",
                line={"color": PRIMARY, "width": 2},
                connectgaps=False,
            )
        )
        figure.add_hline(y=70.0, line_dash="dot", line_color=DOWN, annotation_text="70")
        figure.add_hline(y=30.0, line_dash="dot", line_color=UP, annotation_text="30")
        figure.update_layout(**plotly_layout(height=330))
        st.plotly_chart(figure, width="stretch", config={"displaylogo": False})
        macd_figure = go.Figure()
        for column, label, color in (("macd", "MACD", PRIMARY), ("macd_signal", "시그널", TEXT)):
            macd_figure.add_trace(
                go.Scatter(
                    x=[row.get("trade_date") for row in momentum],
                    y=[_number(row.get(column)) for row in momentum],
                    name=label,
                    mode="lines",
                    line={"color": color, "width": 2},
                    connectgaps=False,
                )
            )
        macd_figure.update_layout(**plotly_layout(height=300))
        st.plotly_chart(macd_figure, width="stretch", config={"displaylogo": False})
        source_note(SOURCE_DB, observed_at=latest_momentum.get("trade_date"), detail="Wilder RSI·MACD 저장값")



def _render_all_segment_axes(
    *,
    ticker: str,
    segment_rows: list[dict[str, Any]],
    segment_processing: list[dict[str, Any]],
) -> None:
    """보고된 **모든** 축을 다기간으로 본다. 카드는 종류별 대표 축 1개·상위 6행만 싣는다."""

    if not segment_rows:
        st.info(f"{ticker}의 fundamentals.segment_metrics 행이 없습니다.")
        return
    filing_status = {
        str(row.get("accession_no") or ""): row for row in segment_processing if row.get("accession_no")
    }
    axes = sorted(
        {
            (str(row.get("segment_type") or ""), str(row.get("axis") or ""))
            for row in segment_rows
        }
    )
    period_kinds = sorted({str(row.get("period_kind") or "") for row in segment_rows})
    with st.container(horizontal=True, gap="small"):
        st.metric("보고된 축", f"{len(axes)}개", border=True)
        st.metric(
            "세그먼트 행",
            f"{len(segment_rows)}행",
            border=True,
        )
        st.metric(
            "기간 종류",
            ", ".join(kind for kind in period_kinds if kind) or "—",
            border=True,
        )
        st.metric("공시 수", f"{len(filing_status)}건", border=True)
    source_note(
        SOURCE_DB,
        detail="Discord는 종류별 대표 축 1개만 싣는다 · 여기는 필터 없이 전 축",
    )

    period_kind = view_selector(
        "기간 종류",
        tuple(kind for kind in ("quarter", "annual") if kind in period_kinds) or ("quarter",),
        key=f"earnings_segment_period_kind:{ticker}",
        default=("quarter" if "quarter" in period_kinds else period_kinds[0]),
    )
    axis_options = [item for item in axes if any(
        str(row.get("segment_type")) == item[0]
        and str(row.get("axis")) == item[1]
        and str(row.get("period_kind")) == period_kind
        for row in segment_rows
    )]
    if not axis_options:
        st.info(f"{period_kind} 기간의 세그먼트 축이 없습니다.")
        return
    axis_index = st.selectbox(
        "세그먼트 축 (전체)",
        range(len(axis_options)),
        format_func=lambda index: (
            f"{SEGMENT_TYPE_LABELS.get(axis_options[index][0], axis_options[index][0])} · "
            f"{axis_options[index][1] or '미분류'}"
        ),
        key=f"earnings_segment_axis_all:{ticker}:{period_kind}",
    )
    segment_type, axis = axis_options[axis_index]
    # 축 이름은 SEC가 보고한 원값이다. 표준 분류 사전이 없으므로 회사마다 표기가 다르다.
    st.caption(f"축 · {axis or '미분류'} · SEC 보고 원값")

    selected = [
        row
        for row in segment_rows
        if str(row.get("segment_type")) == segment_type
        and str(row.get("axis")) == axis
        and str(row.get("period_kind")) == period_kind
    ]
    periods = sorted({str(row.get("period_end") or "") for row in selected if row.get("period_end")})
    members = sorted({str(row.get("display_name") or row.get("member") or "") for row in selected})
    st.caption(
        f"기간 {len(periods)}개 · 원 세그먼트 {len(members)}개 · 상위 N 절단이나 '기타' 합산 없음"
    )

    detail = view_selector(
        "세그먼트 보기",
        ("최신 기간", "기간별 추이", "품질·방법"),
        key=f"earnings_segment_detail_all:{ticker}:{period_kind}:{axis_index}",
        default="최신 기간",
    )

    if detail == "최신 기간":
        if not periods:
            st.info("표시할 기간이 없습니다.")
            return
        latest_period = periods[-1]
        current = [row for row in selected if str(row.get("period_end")) == latest_period]
        accessions = sorted({str(row.get("accession_no") or "") for row in current})
        for accession_no in accessions:
            state = filing_status.get(accession_no, {})
            st.caption(
                f"accession_no {accession_no or '—'} · 상태 {state.get('status') or '기록 없음'} · "
                f"mapping {state.get('mapping_version') or '—'} · "
                f"updated {state.get('updated_at') or '—'}"
            )
        revenue_points = [
            (
                str(row.get("display_name") or row.get("member") or "—"),
                _usable_segment_value(row, "revenue", "quality_status"),
            )
            for row in current
        ]
        chartable = [(name, value) for name, value in revenue_points if value is not None]
        # 비중 분모는 품질 게이트를 통과한 매출만으로 만든다. 게이트를 못 넘은 값을 0으로
        # 넣으면 통과한 세그먼트의 비중이 과대평가된다.
        total = sum(value for _name, value in chartable)

        def _segment_display_row(row: dict[str, Any]) -> dict[str, Any]:
            revenue = _usable_segment_value(row, "revenue", "quality_status")
            return {
                "세그먼트": row.get("display_name") or row.get("member"),
                "매출": revenue,
                "매출 비중": revenue / total if revenue is not None and total > 0.0 else None,
                "부문이익": _usable_segment_value(row, "profit_loss", "profit_quality_status"),
                "이익 정의": row.get("profit_measure_label") or row.get("profit_measure_kind"),
                "자산": _usable_segment_value(row, "assets", "assets_quality_status"),
                "매출 품질": row.get("quality_status") or "게이트 미통과",
                "이익 품질": row.get("profit_quality_status") or "게이트 미통과",
                "자산 품질": row.get("assets_quality_status") or "게이트 미통과",
                "coverage": row.get("coverage_ratio"),
                "derived": row.get("is_derived"),
            }

        def _segment_sort_key(row: dict[str, Any]) -> tuple[int, float]:
            revenue = _usable_segment_value(row, "revenue", "quality_status")
            # 값이 없는 행은 크기 비교에 끼우지 않고 뒤로 보낸다.
            return (0, -revenue) if revenue is not None else (1, 0.0)

        dataframe(
            [_segment_display_row(row) for row in sorted(current, key=_segment_sort_key)],
            key=f"earnings_segment_latest:{ticker}:{axis_index}",
            column_config={"매출 비중": st.column_config.NumberColumn(format="percent")},
        )
        if chartable:
            figure = go.Figure(
                go.Bar(
                    x=[name for name, _value in chartable],
                    y=[value for _name, value in chartable],
                    marker_color=PRIMARY,
                    name="세그먼트 매출",
                )
            )
            figure.update_layout(**plotly_layout(height=400))
            st.plotly_chart(figure, width="stretch", config={"displaylogo": False})
        else:
            st.info("품질 게이트를 통과한 매출 값이 없어 차트를 만들지 않습니다.")
        source_note(
            SOURCE_DB,
            observed_at=latest_period,
            detail="verified/partial만 숫자로 표시 · 그 외는 상태 문자열로만",
        )
    elif detail == "기간별 추이":
        if len(periods) < 2:
            st.info("비교할 기간이 두 개 미만이라 추이를 만들지 않습니다.")
            return
        by_member: dict[str, dict[str, float]] = {}
        for row in selected:
            name = str(row.get("display_name") or row.get("member") or "—")
            value = _usable_segment_value(row, "revenue", "quality_status")
            if value is None:
                continue
            by_member.setdefault(name, {})[str(row.get("period_end"))] = value
        if not by_member:
            st.info("품질 게이트를 통과한 매출 값이 없어 추이를 만들지 않습니다.")
            return
        ranked = sorted(
            by_member.items(),
            key=lambda item: -max(item[1].values()),
        )
        figure = go.Figure()
        palette = (PRIMARY, TEXT, MUTED, UP, DOWN)
        for position, (name, values) in enumerate(ranked):
            figure.add_trace(
                go.Scatter(
                    x=periods,
                    y=[values.get(period) for period in periods],
                    name=name,
                    mode="lines+markers",
                    line={"color": palette[position % len(palette)], "width": 2},
                    connectgaps=False,
                )
            )
        figure.update_layout(**plotly_layout(height=440))
        st.plotly_chart(figure, width="stretch", config={"displaylogo": False})
        dataframe(
            [
                {"세그먼트": name, **{period: values.get(period) for period in periods}}
                for name, values in ranked
            ],
            key=f"earnings_segment_trend:{ticker}:{axis_index}",
        )
        source_note(
            SOURCE_DB,
            observed_at=periods[-1],
            detail="같은 축·같은 기간 종류만 이어 붙임 · 결측 기간은 선을 잇지 않음",
        )
    else:
        dataframe(
            [
                {
                    "결산일": row.get("period_end"),
                    "세그먼트": row.get("display_name") or row.get("member"),
                    "보조 축": row.get("secondary_member"),
                    "이익 정의": row.get("profit_measure_kind"),
                    "매출 품질": row.get("quality_status"),
                    "이익 품질": row.get("profit_quality_status"),
                    "자산 품질": row.get("assets_quality_status"),
                    "coverage": row.get("coverage_ratio"),
                    "derived": row.get("is_derived"),
                    "accession_no": row.get("accession_no"),
                }
                for row in sorted(
                    selected,
                    key=lambda row: (str(row.get("period_end") or ""), str(row.get("member") or "")),
                    reverse=True,
                )
            ],
            key=f"earnings_segment_quality:{ticker}:{axis_index}",
        )
        source_note(SOURCE_DB, detail="매핑 방법·품질 상태 원값 · 대시보드가 보정하지 않음")


def _render_collection_audit(
    *,
    ticker: str,
    filing_ledger: list[dict[str, Any]],
    notify_log: list[dict[str, Any]],
) -> None:
    """정상 처리 provenance와 Discord 발송 중복 방지 기록을 보여준다."""

    ledger = sorted(filing_ledger, key=lambda row: str(row.get("filing_date") or ""), reverse=True)
    statuses: dict[str, int] = {}
    for row in ledger:
        statuses[str(row.get("status") or "unknown")] = statuses.get(str(row.get("status") or "unknown"), 0) + 1
    sent_accessions = {str(row.get("accession_no") or "") for row in notify_log}
    parsed_accessions = {
        str(row.get("accession_no") or "")
        for row in ledger
        if str(row.get("status")) == "parsed"
    }
    unsent = sorted(parsed_accessions - sent_accessions)

    with st.container(horizontal=True, gap="small"):
        st.metric("수집 공시", f"{len(ledger)}건", border=True)
        st.metric("미지원", f"{statuses.get('unsupported', 0)}건", border=True)
        st.metric("Discord 발송", f"{len(sent_accessions)}건", border=True)
    st.caption("상태 분포 · " + (", ".join(f"{key} {value}" for key, value in sorted(statuses.items())) or "—"))
    source_note(
        SOURCE_DB,
        SOURCE_CALC,
        detail="fundamentals.filing_processing + notifications.outbox · 운영 오류는 Discord #액션-실패",
    )

    if statuses.get("unsupported"):
        st.warning(
            "지원하지 않는 공시 형식은 재무 행을 만들지 않습니다. 실행 오류는 Discord 시스템 로그에서 확인하세요."
        )

    block = view_selector(
        "감사 대상",
        ("수집 장부", "발송 기록"),
        key=f"earnings_audit_block:{ticker}",
        default="수집 장부",
    )
    if block == "수집 장부":
        dataframe(
            [
                {
                    "공시일": row.get("filing_date"),
                    "결산일": row.get("report_date"),
                    "form_type": row.get("form_type"),
                    "상태": row.get("status"),
                    "accession_no": row.get("accession_no"),
                    "facts": row.get("facts_count"),
                    "rows": row.get("rows_count"),
                    "mapping": row.get("mapping_version"),
                    "Discord 발송": "예" if str(row.get("accession_no")) in sent_accessions else "아니오",
                    "updated": row.get("updated_at"),
                }
                for row in ledger
            ],
            key=f"earnings_audit_ledger:{ticker}",
        )
        if unsent:
            st.caption(
                f"parsed지만 발송 기록이 없는 accession_no {len(unsent)}건 · "
                "관심종목 등록 전 공시이거나 알림이 아직 돌지 않은 건입니다."
            )
        source_note(SOURCE_DB, SOURCE_CALC, detail="발송 여부는 notifications.outbox의 report:{ticker}:{accession_no} 키와 resolved_at으로 판단")
    else:
        dataframe(
            [
                {
                    "발송 시각": row.get("sent_at"),
                    "공시일": row.get("filed_at"),
                    "회계연도": row.get("fiscal_year"),
                    "기간": row.get("fiscal_period"),
                    "accession_no": row.get("accession_no"),
                }
                for row in sorted(notify_log, key=lambda row: str(row.get("sent_at") or ""), reverse=True)
            ],
            key=f"earnings_audit_notify:{ticker}",
        )
        source_note(SOURCE_DB, detail="notifications.outbox(kind=fundamentals_earnings,status=sent) · 이 화면은 발송하지 않는다")


def _render_extended(*, active_watchlist: list[str]) -> None:
    """Discord 카드가 싣지 않는 확장 근거를 선택한 한 섹션만 읽고 표시한다."""

    st.caption(
        "이 보기는 Discord 카드의 재현이 아니라 **확장**입니다. 카드가 지면 때문에 생략하는 "
        "성장 뷰·업종 특수 계정·저장 기술 지표·모든 세그먼트 축·수집 감사 장부를 봅니다."
    )
    ticker = _select_ticker(active_watchlist, key="earnings_extended_ticker")
    if not ticker:
        return
    section = view_selector(
        "확장 섹션",
        EXTENDED_SECTIONS,
        key=f"earnings_extended_section:{ticker}",
        default=EXTENDED_SECTIONS[0],
    )
    # 선택한 섹션의 SELECT만 실행한다.
    result = load_earnings_extended(ticker, section=section)
    if not result_status(result, empty_text=f"{ticker}의 {section} 확장 근거가 없습니다"):
        return
    if result.message:
        st.warning(f"부분 연결 실패 · {result.message}")
    payload = result_payload(result, default={}) or {}

    if section == "성장·마진":
        _render_growth(list(payload.get("growth", [])), ticker=ticker)
    elif section == "업종 특수 재무":
        _render_industry_specific(list(payload.get("industry", [])), ticker=ticker)
    elif section == "기술 지표":
        _render_stored_technicals(
            ticker=ticker,
            tech_daily=list(payload.get("tech_daily", [])),
            tech_view=list(payload.get("tech_view", [])),
            oscillators=list(payload.get("oscillators", [])),
        )
    elif section == "세그먼트 전 축":
        _render_all_segment_axes(
            ticker=ticker,
            segment_rows=list(payload.get("segment_all", [])),
            segment_processing=list(payload.get("segment_processing", [])),
        )
    else:
        _render_collection_audit(
            ticker=ticker,
            filing_ledger=list(payload.get("filing_ledger", [])),
            notify_log=list(payload.get("notify_log", [])),
        )


st.title("어닝 인사이트")
st.warning(
    "SEC GAAP 공시와 provider 조정 EPS는 기준이 달라요. "
    "같은 기준의 actual/estimate 쌍만 서프라이즈로 보여드려요.",
    icon=":material/rule:",
)

# 최상위는 두 갈래다 — 아직 안 나온 실적(예정·속보)과 이미 나온 실적(결과).
# 나머지는 전부 '결과'의 상세이므로 상위 탭으로 올리지 않는다.
UPCOMING_VIEWS = {"일정": "발표 예정", "8-K 속보": "⚡ 실적 속보 (8-K)"}
RESULT_VIEWS = {
    "공시 카드": "Discord 카드 전체",
    "컨센서스 대비": "발표 결과",
    "재무 추이": "재무 추이",
    "공시 장부": "공시 근거",
    "확장 분석": "확장 분석",
}

top_view = view_selector(
    "실적 보기",
    ("발표 예정", "실적 결과"),
    key="earnings_top_view",
    default="실적 결과",
)
if top_view == "발표 예정":
    st.caption("아직 10-Q가 나오지 않은 건입니다. 일정은 확정 공시일이 아니고, 속보는 8-K 보도자료입니다.")
    upcoming_view = view_selector(
        "예정 보기",
        tuple(UPCOMING_VIEWS),
        key="earnings_upcoming_view",
        default="일정",
    )
    view = UPCOMING_VIEWS[upcoming_view]
else:
    st.caption("이미 제출된 공시입니다. 기본은 공시 카드 한 장이고, 더 필요한 근거만 눌러서 엽니다.")
    result_view = view_selector(
        "결과 보기",
        tuple(RESULT_VIEWS),
        key="earnings_result_view",
        default="공시 카드",
    )
    view = RESULT_VIEWS[result_view]

earnings_result = load_earnings_data(section=view)
if not result_status(earnings_result, empty_text="실적·컨센서스 저장 데이터가 없습니다"):
    st.stop()

payload = result_payload(earnings_result, default={}) or {}
core_rows = list(payload.get("core", []))
filing_rows = list(payload.get("filings", []))
# 컨센서스는 관측 이력 원본으로 온다. 화면이 쓰는 두 축약은 여기서 만든다.
consensus_rows = list(payload.get("consensus", []))
overview_rows = latest_estimate_overview(consensus_rows)
pre_release_rows = pre_release_consensus(core_rows, consensus_rows)
watchlist_rows = list(payload.get("watchlist", []))
ticker_profiles = list(payload.get("ticker_profiles", []))
active_watchlist = sorted(
    {
        str(row.get("ticker", "")).upper()
        for row in watchlist_rows
        if row.get("ticker") and not row.get("removed_at")
    }
)

if view == "⚡ 실적 속보 (8-K)":
    flash_rows = list(payload.get("earnings_flash", []))
    st.subheader(":material/bolt: 8-K 실적 발표 속보")
    st.caption(
        "실적 발표 당일 장 시작 전/후에 제출된 Form 8-K (Item 2.02) 보도자료를 기반으로 "
        "매출·EPS 서프라이즈를 실시간 파악하고 정식 10-Q 공시 대기 상태를 추적합니다."
    )

    if not flash_rows:
        st.info("최근 수집된 8-K 실적 속보 공시가 없습니다.")
    else:
        profile_map = {
            str(row.get("ticker")): row for row in ticker_profiles if isinstance(row, dict) and row.get("ticker")
        }
        filed_10q_keys = {
            (
                str(row.get("ticker") or "").upper(),
                int(row.get("fiscal_year") or 0),
                str(row.get("fiscal_period") or ""),
            )
            for row in core_rows
            if row.get("ticker") and row.get("fiscal_year")
        }

        total_flash = len(flash_rows)
        beats = sum(1 for r in flash_rows if (r.get("surprise_eps_pct") or 0) > 0)
        pending_10q = sum(
            1
            for r in flash_rows
            if (
                str(r.get("ticker") or "").upper(),
                int(r.get("fiscal_year") or 0),
                str(r.get("fiscal_period") or ""),
            )
            not in filed_10q_keys
        )

        m1, m2, m3 = st.columns(3)
        m1.metric("최근 8-K 속보 발표", f"{total_flash}건")
        m2.metric("어닝 서프라이즈 (상회)", f"{beats}건", f"{(beats/total_flash*100):.0f}%" if total_flash else None)
        m3.metric("정식 10-Q 대기 중", f"{pending_10q}건", f"미제출 {pending_10q}건" if pending_10q else "모두 제출됨")

        table_data = []
        for r in flash_rows:
            ticker = str(r.get("ticker") or "").upper()
            profile = profile_map.get(ticker) or {}
            name_display = f"{profile.get('name_ko') or profile.get('name') or ticker} ({ticker})"
            fy = r.get("fiscal_year")
            fp = r.get("fiscal_period")
            period_str = f"FY{fy} {fp}" if fy and fp else "—"
            filed_d = str(r.get("filed_at") or "")

            eps_act = r.get("eps_actual")
            eps_est = r.get("eps_estimate")
            surp_eps = r.get("surprise_eps_pct")
            if surp_eps is None and eps_act is not None and eps_est is not None and eps_est != 0:
                surp_eps = ((eps_act - eps_est) / abs(eps_est)) * 100.0

            rev_act = r.get("revenue_actual")
            rev_est = r.get("revenue_estimate")
            surp_rev = r.get("surprise_revenue_pct")
            op_act = r.get("operating_income_actual")
            net_act = r.get("net_income_actual")
            if surp_rev is None and rev_act is not None and rev_est is not None and rev_est > 0:
                surp_rev = ((rev_act - rev_est) / rev_est) * 100.0

            if eps_act is not None and eps_est is not None:
                eps_str = f"${eps_act:.2f} (예상 ${eps_est:.2f})"
            elif eps_act is not None:
                eps_str = f"${eps_act:.2f}"
            else:
                eps_str = "—"

            if surp_eps is not None:
                surp_eps_str = f"{surp_eps:+.1f}% 🟢" if surp_eps > 0 else f"{surp_eps:+.1f}% 🔴"
            else:
                surp_eps_str = "—"

            if rev_act is not None and rev_est is not None:
                rev_str = f"{display_money(rev_act)} (예상 {display_money(rev_est)})"
            elif rev_act is not None:
                rev_str = display_money(rev_act)
            else:
                rev_str = "—"

            if surp_rev is not None:
                surp_rev_str = f"{surp_rev:+.1f}% 🟢" if surp_rev > 0 else f"{surp_rev:+.1f}% 🔴"
            else:
                surp_rev_str = "—"

            is_10q_ready = (ticker, int(fy or 0), str(fp or "")) in filed_10q_keys
            status_10q = "✅ 10-Q 공시 완료" if is_10q_ready else "⏳ 10-Q 대기 중 (1~2주)"

            press_url = r.get("press_release_url")

            table_data.append({
                "종목": name_display,
                "대상 분기": period_str,
                "8-K 공시일": filed_d,
                "주당순이익 (EPS)": eps_str,
                "EPS 서프라이즈": surp_eps_str,
                "EPS 예상값 기준": _estimate_provenance(r),
                "매출액 (Revenue)": rev_str,
                "매출 서프라이즈": surp_rev_str,
                "영업이익 (Operating Income)": display_money(op_act) if op_act is not None else "—",
                "순이익 (Net Income)": display_money(net_act) if net_act is not None else "—",
                "10-Q 정식 공시 상태": status_10q,
                "SEC 공시": press_url or "SEC 8-K",
            })

        dataframe(
            table_data,
            key="earnings_flash_table",
        )

        st.space("medium")
        st.subheader(":material/search: 속보 상세 보기")
        selected_flash = st.selectbox(
            "속보 공시 선택",
            options=range(len(flash_rows)),
            format_func=lambda idx: f"{flash_rows[idx].get('ticker')} - FY{flash_rows[idx].get('fiscal_year')} {flash_rows[idx].get('fiscal_period')} (공시일: {flash_rows[idx].get('filed_at')})",
            key="earnings_flash_select",
        )
        if selected_flash is not None and selected_flash < len(flash_rows):
            f_row = flash_rows[selected_flash]
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f"**티커**: `{f_row.get('ticker')}`")
                st.markdown(f"**대상 분기**: `FY{f_row.get('fiscal_year')} {f_row.get('fiscal_period')}`")
                st.markdown(f"**SEC 접수일**: `{f_row.get('filed_at')}`")
                st.markdown(f"**Accession No**: `{f_row.get('accession_no')}`")
            with col_b:
                st.markdown(f"**주당순이익 (EPS)**: `{f_row.get('eps_actual')}` (예상: `{f_row.get('eps_estimate')}`, 서프라이즈: `{f_row.get('surprise_eps_pct')}%`)")
                st.markdown(f"**EPS 예상값 기준**: `{_estimate_provenance(f_row)}`")
                st.markdown(f"**매출액 (Revenue)**: `{display_money(f_row.get('revenue_actual'))}` (예상: `{display_money(f_row.get('revenue_estimate'))}`, 서프라이즈: `{f_row.get('surprise_revenue_pct')}%`)")
                st.markdown(f"**영업이익 (Operating Income)**: `{display_money(f_row.get('operating_income_actual'))}`")
                st.markdown(f"**순이익 (Net Income)**: `{display_money(f_row.get('net_income_actual'))}`")
                if f_row.get("press_release_url"):
                    st.markdown(f":material/open_in_new: [SEC 8-K 공시 원문 열기]({f_row.get('press_release_url')})")

            guidance_clean = format_guidance_headline(f_row.get("guidance_summary"))
            if guidance_clean:
                st.info(f"**가이던스 요약** · **{guidance_clean}**", icon=":material/campaign:")

elif view == "발표 예정":
    overview = pd.DataFrame(overview_rows)
    today = pd.Timestamp(today_kst())
    profile_map = {
        str(row.get("ticker")): row for row in ticker_profiles if isinstance(row, dict) and row.get("ticker")
    }
    consensus_by_key = {
        (
            str(row.get("ticker")),
            str(row.get("target_fiscal_year")),
            str(row.get("target_fiscal_period")),
            str(row.get("snapshot_date")),
            str(row.get("source")),
        ): row
        for row in overview_rows
    }
    calendar_input: list[dict[str, Any]] = []
    for schedule in overview_rows:
        key = (
            str(schedule.get("ticker")),
            str(schedule.get("target_fiscal_year")),
            str(schedule.get("target_fiscal_period")),
            str(schedule.get("snapshot_date")),
            str(schedule.get("source")),
        )
        # Discord calendar.db와 같은 exact snapshot/source 키로만 consensus를 결합한다.
        calendar_input.append({**schedule, **(consensus_by_key.get(key) or {})})

    # 예정일이 없는 행은 아래 순수 함수가 버린다. 그러면 화면이 통째로 비는데,
    # "예정된 실적이 없다"와 "예정일 원천이 없다"는 전혀 다른 사실이므로 먼저 구분해 말한다.
    if not any(row.get("expected_report_date") for row in calendar_input):
        st.warning(
            "발표 예정일 원천이 현재 스키마에 없습니다 — `fundamentals.earnings_estimates`는 "
            "대상 회계기간(`target_period_end`)까지만 갖고 있고 `expected_report_date` 컬럼이 "
            "없습니다. 아래 컨센서스 값은 실제 저장된 값이고, 예정일만 비어 있습니다.",
            icon=":material/event_busy:",
        )

    # Discord 카드는 '이번 주'만 주장한다(월–일). 화면은 지면 제약이 없으므로 창을
    # 골라 볼 수 있게 하고, Discord 규칙은 그중 한 선택지로 그대로 남긴다.
    horizon = view_selector(
        "일정 지평",
        tuple(SCHEDULE_HORIZONS),
        key="earnings_schedule_horizon",
        default=DEFAULT_SCHEDULE_HORIZON,
    )
    window_start, window_end, group_by_target = schedule_window(horizon, today.date())
    # shifted/stale 등급·전년 제출일 규칙은 Discord와 같은 순수 함수를 재사용한다.
    calendar_rows = calendar_schedule.build_rows_in_window(
        calendar_input,
        core_rows,
        profile_map,
        today.date(),
        start=window_start,
        end=window_end,
        group_by_target=group_by_target,
    )
    if active_watchlist:
        calendar_rows = [row for row in calendar_rows if str(row.get("ticker", "")).upper() in active_watchlist]
    st.caption(
        f"조회 창 · {window_start.isoformat()} ~ {window_end.isoformat()} · "
        + ("종목·기간별 최신 스냅샷" if group_by_target else "Discord와 같은 종목별 최신 스냅샷 1건")
    )

    if not calendar_rows:
        st.info(
            f"{horizon} 창({window_start.isoformat()} ~ {window_end.isoformat()})에 "
            "실제 저장된 발표 예정 건이 없습니다. 임의 일정을 만들지 않습니다."
        )
    else:
        nearest = calendar_rows[0]
        eps_ready = sum(row.get("eps_avg") is not None for row in calendar_rows)
        revenue_ready = sum(row.get("revenue_avg") is not None for row in calendar_rows)
        with st.container(horizontal=True):
            st.metric(f"{horizon} 예정", f"{len(calendar_rows)}건", border=True)
            st.metric("가장 가까운 발표", str(nearest.get("ticker") or "—"), border=True)
            st.metric("EPS 컨센서스", f"{eps_ready}/{len(calendar_rows)}", border=True)
            st.metric("매출 컨센서스", f"{revenue_ready}/{len(calendar_rows)}", border=True)

        event_options = range(len(calendar_rows))
        event_index = st.selectbox(
            "발표 예정 건",
            event_options,
            format_func=lambda index: (
                f"{calendar_rows[index].get('ticker') or '—'} · "
                f"{calendar_rows[index].get('expected_label') or calendar_rows[index].get('expected') or '—'} · "
                f"{calendar_rows[index].get('name') or '—'} · "
                f"[{'10-K 연간결산' if calendar_rows[index].get('form_expected') == '10-K' else '10-Q 분기'}]"
            ),
            key="earnings_schedule_event",
        )
        calendar_selected = calendar_rows[event_index]
        matching_schedules = [
            row
            for row in calendar_input
            if str(row.get("ticker")) == str(calendar_selected.get("ticker"))
            and str(row.get("snapshot_date")) == str(calendar_selected.get("snapshot_date"))
            and str(row.get("target_period_end")) == str(calendar_selected.get("target_period_end"))
            and str(row.get("expected_report_date")) == str(calendar_selected.get("expected"))
        ]
        schedule_selected = max(
            matching_schedules,
            key=lambda row: str(row.get("collected_at") or row.get("snapshot_date") or ""),
            default={},
        )
        selected = {**calendar_selected, **schedule_selected}
        snapshot = pd.to_datetime(selected.get("snapshot_date"), errors="coerce")
        stale_days = (today - snapshot.normalize()).days if pd.notna(snapshot) else None
        schedule_detail = view_selector(
            "예정 카드 상세",
            ("컨센서스", "목표·등급"),
            key=f"earnings_schedule_detail:{selected.get('ticker')}:{event_index}",
            default="컨센서스",
        )
        expected_value = calendar_selected.get("expected") or selected.get("expected_report_date")
        target_fp = str(selected.get("target_fiscal_period") or "").upper()
        form_expected = selected.get("form_expected") or ("10-K" if target_fp in ("Q4", "FY") else "10-Q")
        form_name = "Form 10-K (연간 사업보고서 · 결산)" if form_expected == "10-K" or target_fp in ("Q4", "FY") else "Form 10-Q (분기 보고서)"
        period_end_dt = pd.to_datetime(selected.get("target_period_end"), errors="coerce")
        sec_deadline_dt = (period_end_dt + pd.Timedelta(days=60 if "10-K" in form_name else 40)).strftime("%Y-%m-%d") if pd.notna(period_end_dt) else "—"

        with st.container(border=True):
            st.markdown(
                f"### {calendar_selected.get('name') or selected.get('ticker') or '—'} "
                f"(`{selected.get('ticker') or '—'}`) · {form_name}"
            )
            c_sch1, c_sch2 = st.columns(2)
            with c_sch1:
                st.markdown(f":material/bolt: **1단계 · 8-K 실적 발표 예정** · `{expected_value or '—'}` (`{d_day_label(calendar_selected.get('days_until'))}`)")
                st.markdown(f":material/description: **2단계 · 정식 보고서 법적 마감** · `{sec_deadline_dt}`까지")
            with c_sch2:
                st.markdown(f"**대상 회계기간**: `FY{selected.get('target_fiscal_year') or '—'} {selected.get('target_fiscal_period') or '—'}` (기간말: `{selected.get('target_period_end') or '—'}`)")
                st.markdown(f"**섹터 / 신뢰도**: `{calendar_selected.get('sector') or '—'}` · `{calendar_selected.get('confidence') or '—'}`")

            st.info(
                "실적 발표 당일(`8-K`)에는 매출·EPS 서프라이즈 속보가 발송되고, "
                f"정식 {form_name.split()[1]} 공시가 SEC에 접수되면 13분기 종합 재무 분석 카드가 발행돼요.",
                icon=":material/notifications_active:",
            )

            st.caption(
                f"동일 기간 예정일 관측 · {calendar_selected.get('observations') if calendar_selected.get('observations') is not None else '—'}회 · "
                f"이전 예정일 · {calendar_selected.get('previous_expected') or '—'} · "
                f"전년 동기 실제 제출 · {calendar_selected.get('prior_filed_at') or '—'} ({calendar_selected.get('prior_period') or '—'})"
            )
            if schedule_detail == "컨센서스":
                st.write(
                    f"조정 EPS 예상 · {display_number(selected.get('eps_avg'))} "
                    f"[{display_number(selected.get('eps_low'))} ~ {display_number(selected.get('eps_high'))}] · "
                    f"분석가 · {selected.get('eps_analysts') if selected.get('eps_analysts') is not None else '—'}"
                )
                st.write(
                    f"매출 예상 · {display_money(selected.get('revenue_avg'))} "
                    f"[{display_money(selected.get('revenue_low'))} ~ {display_money(selected.get('revenue_high'))}] · "
                    f"분석가 · {selected.get('revenue_analysts') if selected.get('revenue_analysts') is not None else '—'} · "
                    f"통화 · {selected.get('currency') or '—'}"
                )
                st.caption(
                    f"리비전 7일 상향/하향 · {selected.get('revisions_up_7d') if selected.get('revisions_up_7d') is not None else '—'} / "
                    f"{selected.get('revisions_down_7d') if selected.get('revisions_down_7d') is not None else '—'} · "
                    f"30일 · {selected.get('revisions_up_30d') if selected.get('revisions_up_30d') is not None else '—'} / "
                    f"{selected.get('revisions_down_30d') if selected.get('revisions_down_30d') is not None else '—'}"
                )
            else:
                with st.container(horizontal=True):
                    st.metric("목표 평균", display_money(selected.get("target_mean")), border=True)
                    st.metric("목표 중앙값", display_money(selected.get("target_median")), border=True)
                    st.metric("목표 범위", f"{display_money(selected.get('target_low'))} ~ {display_money(selected.get('target_high'))}", border=True)
                dataframe(
                    [
                        {
                            "Strong buy": selected.get("strong_buy"),
                            "Buy": selected.get("buy"),
                            "Hold": selected.get("hold"),
                            "Sell": selected.get("sell"),
                            "Strong sell": selected.get("strong_sell"),
                            "source horizon": selected.get("source_horizon"),
                            "collected at": selected.get("collected_at"),
                        }
                    ],
                    key=f"earnings_ratings:{selected.get('ticker')}:{event_index}",
                )
            st.caption(
                f"컨센서스 기준일 · {selected.get('snapshot_date') or '—'} · "
                f"일정 기준일 · {selected.get('schedule_snapshot_date') or '—'} · "
                f"source · {selected.get('source') or '—'} · kind · {selected.get('snapshot_kind') or '—'}"
            )
            if stale_days is None:
                st.warning("컨센서스 기준일을 확인할 수 없습니다.")
            elif stale_days > 7:
                st.warning(f"데이터 품질 · 컨센서스 스냅샷이 {stale_days}일 전 값입니다.")
            else:
                st.caption(f"데이터 품질 · 스냅샷 경과 {stale_days}일 · 예정일은 확정 공시일이 아님")
            source_note(
                SOURCE_DB,
                SOURCE_CALC,
                observed_at=selected.get("snapshot_date"),
                detail=(
                    "earnings_estimates(최신 관측) + financial_versions + universe entities/securities · "
                    "발표 예정일 표는 현재 스키마에 없음"
                ),
            )

        schedule_display = [
            {
                "발표 예정일": row.get("expected"),
                "D-day": d_day_label(row.get("days_until")),
                "종목": row.get("ticker"),
                "회사": row.get("name"),
                "sic_industry": row.get("sic_industry"),
                "대상 기간말": row.get("target_period_end"),
                "confidence": row.get("confidence"),
                "이전 예정일": row.get("previous_expected"),
                "관측 수": row.get("observations"),
                "조정 EPS 예상": row.get("eps_avg"),
                "EPS 분석가": row.get("eps_analysts"),
                "매출 예상": row.get("revenue_avg"),
                "전년 실제 제출": row.get("prior_filed_at"),
                "전년 기간": row.get("prior_period"),
                "컨센서스 기준일": row.get("snapshot_date"),
            }
            for row in calendar_rows
        ]
        dataframe(schedule_display, key="earnings_week_table")
        source_note(SOURCE_DB, detail="reporting.earnings.schedule와 동일한 shifted > stale > estimated 규칙")

elif view == "발표 결과":
    ticker = _select_ticker(active_watchlist, key="earnings_result_ticker")
    if ticker:
        ticker_pre = sorted(
            _ticker_rows(pre_release_rows, ticker),
            key=lambda row: str(row.get("period_end") or ""),
            reverse=True,
        )
        if not ticker_pre:
            st.info(f"{ticker}의 공시 전 컨센서스 결합 결과가 없습니다.")
        else:
            event_index = st.selectbox(
                "발표 결과 건",
                range(len(ticker_pre)),
                format_func=lambda index: (
                    f"FY{ticker_pre[index].get('fiscal_year') or '—'} {ticker_pre[index].get('fiscal_period') or '—'} · "
                    f"기간말 {ticker_pre[index].get('period_end') or '—'} · 공시 {ticker_pre[index].get('filed_at') or '—'}"
                ),
                key=f"earnings_result_event:{ticker}",
            )
            selected = ticker_pre[event_index]
            core_candidates = [
                row
                for row in _ticker_rows(core_rows, ticker)
                if str(row.get("fiscal_year")) == str(selected.get("fiscal_year"))
                and str(row.get("fiscal_period")) == str(selected.get("fiscal_period"))
                and str(row.get("period_end")) == str(selected.get("period_end"))
            ]
            exact_filing = [
                row
                for row in core_candidates
                if str(row.get("filed_at")) == str(selected.get("filed_at"))
            ]
            matching_core = max(
                exact_filing,
                key=lambda row: str(row.get("filed_at") or ""),
                default={},
            )
            revenue_pair = _difference(matching_core.get("revenue"), selected.get("revenue_avg"))
            quality_value = _number(revenue_pair["surprise"])
            quality_warning = quality_value is not None and abs(quality_value) > 0.5
            snapshot_at = pd.to_datetime(selected.get("snapshot_date"), errors="coerce")
            filed_at = pd.to_datetime(selected.get("filed_at"), errors="coerce")
            snapshot_age = (
                (filed_at.normalize() - snapshot_at.normalize()).days
                if pd.notna(snapshot_at) and pd.notna(filed_at)
                else None
            )
            with st.container(horizontal=True):
                st.metric("EPS 컨센서스", display_number(selected.get("eps_avg")), border=True)
                st.metric("매출 실제", display_money(matching_core.get("revenue")), border=True)
                st.metric("매출 예상", display_money(selected.get("revenue_avg")), border=True)
                st.metric("매출 surprise", display_percent(revenue_pair["surprise"], signed=True), border=True)
            with st.container(border=True):
                st.markdown("**발표 결과와 시점 근거**")
                st.write(
                    f"대상 · FY{selected.get('fiscal_year') or '—'} {selected.get('fiscal_period') or '—'} · "
                    f"기간말 · {selected.get('period_end') or '—'} · 공시 · {selected.get('filed_at') or '—'}"
                )
                st.write(
                    f"매출 실제 · {display_money(matching_core.get('revenue'))} · "
                    f"예상 · {display_money(selected.get('revenue_avg'))} · "
                    f"차이 · {display_money(revenue_pair['difference'])} · "
                    f"surprise · {display_percent(revenue_pair['surprise'], signed=True)}"
                )
                st.caption(
                    f"컨센서스 기준일 · {selected.get('snapshot_date') or '—'} · "
                    f"EPS range · {display_number(selected.get('eps_low'))} ~ {display_number(selected.get('eps_high'))} · "
                    f"매출 range · {display_money(selected.get('revenue_low'))} ~ {display_money(selected.get('revenue_high'))}"
                )
                st.caption(
                    f"컨센서스 source · {selected.get('source') or '—'} · "
                    f"EPS 분석가 · {selected.get('eps_analysts') if selected.get('eps_analysts') is not None else '—'} · "
                    f"매출 분석가 · {selected.get('revenue_analysts') if selected.get('revenue_analysts') is not None else '—'}"
                )
                st.caption(
                    "EPS surprise는 reporting.earnings_surprise의 발표 전 동일 기준 예상·실제 쌍이 "
                    "있을 때만 표시한다 · SEC GAAP 희석 EPS로 대체하지 않는다"
                )
                if not matching_core and core_candidates:
                    st.warning(
                        "데이터 연결 실패 · 같은 회계기간의 financial_versions 행은 있지만 공시일이 정확히 "
                        "일치하지 않아 매출·provenance를 결합하지 않았습니다."
                    )
                elif not matching_core:
                    st.warning("데이터 없음 · ticker/FY/period/period_end/filed_at가 모두 일치하는 financial_versions 행이 없습니다.")
                if snapshot_age is None:
                    st.warning("데이터 품질 · 컨센서스 기준일과 공시일의 시점 차이를 확인할 수 없습니다.")
                elif snapshot_age <= 0:
                    st.warning("데이터 품질 · 공시 전 스냅샷이 아니므로 surprise 해석에 사용하면 안 됩니다.")
                elif snapshot_age > 120:
                    st.warning(
                        f"데이터 품질 · 컨센서스가 공시 {snapshot_age}일 전 값입니다. "
                        "Discord 카드의 120일 freshness 범위를 벗어납니다."
                    )
                elif quality_warning:
                    st.warning("데이터 품질 · 매출 surprise 절대값이 50%를 넘어 기준 불일치 가능성이 있습니다.")
                else:
                    st.caption(
                        f"데이터 품질 · 공시 {snapshot_age}일 전의 컨센서스 스냅샷으로 매출을 대조"
                    )
                source_note(SOURCE_DB, SOURCE_CALC, observed_at=selected.get("filed_at"), detail="earnings_estimates(snapshot_date < filed_at) + financial_versions")

            # 분기별 어닝 서프라이즈 트랙 레코드 (과거 분기 추이)
            st.space("medium")
            st.markdown("##### :material/trending_up: 분기별 매출 서프라이즈 트랙 레코드")
            ticker_core_all = _ticker_rows(core_rows, ticker)
            surprise_history = historical_surprise_series(ticker_core_all, consensus_rows)
            valid_surprises = [
                row for row in surprise_history
                if row.get("revenue_surprise_pct") is not None
            ]
            if not valid_surprises:
                st.info(f"{ticker}의 사전 컨센서스가 결합된 과거 분기 서프라이즈 이력이 없습니다.")
            else:
                display_history = sorted(
                    valid_surprises[:8],
                    key=lambda r: str(r.get("period_end") or ""),
                )
                latest_streak = display_history[-1].get("consecutive_revenue_beats", 0)
                beat_count = sum(1 for r in display_history if r.get("revenue_status") == "beat")
                beat_rate = (beat_count / len(display_history)) * 100 if display_history else 0

                with st.container(horizontal=True):
                    st.metric(
                        "연속 매출 상회 (Beat)",
                        f"{latest_streak}분기 연속" if latest_streak > 0 else "0분기",
                        border=True,
                    )
                    st.metric(
                        "최근 관측 분기 Beat 비율",
                        f"{beat_rate:.0f}% ({beat_count}/{len(display_history)}분기)",
                        border=True,
                    )

                labels = [f"FY{r.get('fiscal_year')} {r.get('fiscal_period')}" for r in display_history]
                pct_values = [float(r.get("revenue_surprise_pct") or 0.0) * 100.0 for r in display_history]
                colors = [UP if val >= 0 else DOWN for val in pct_values]
                text_labels = [f"{val:+.1f}%" for val in pct_values]

                fig = go.Figure()
                fig.add_trace(
                    go.Bar(
                        x=labels,
                        y=pct_values,
                        marker_color=colors,
                        text=text_labels,
                        textposition="outside",
                        hovertemplate="<b>%{x}</b><br>서프라이즈: %{y:+.2f}%<extra></extra>",
                    )
                )
                fig.add_hline(y=0, line_dash="dash", line_color=MUTED)
                layout = plotly_layout(height=280)
                layout["yaxis_ticksuffix"] = "%"
                layout["margin"] = {"l": 20, "r": 20, "t": 30, "b": 20}
                fig.update_layout(**layout)
                st.plotly_chart(
                    fig,
                    width="stretch",
                    config={"displaylogo": False},
                    key=f"earnings_surprise_chart_{ticker}",
                )

                table_rows = []
                for r in reversed(display_history):
                    status_text = (
                        "🟢 Beat" if r.get("revenue_status") == "beat"
                        else ("🔴 Miss" if r.get("revenue_status") == "miss" else "⚪ In-Line")
                    )
                    table_rows.append({
                        "회계기간": f"FY{r.get('fiscal_year')} {r.get('fiscal_period')}",
                        "기간말": str(r.get("period_end") or "—"),
                        "공시일": str(r.get("filed_at") or "—"),
                        "매출 실제": display_money(r.get("revenue_actual")),
                        "매출 예상": display_money(r.get("revenue_estimate")),
                        "서프라이즈": display_percent(r.get("revenue_surprise_pct"), signed=True),
                        "판정": status_text,
                    })
                dataframe(table_rows, key=f"earnings_surprise_table_{ticker}")
                source_note(
                    SOURCE_DB,
                    SOURCE_CALC,
                    detail="earnings_estimates(공시일 이전) + financial_versions 분기별 결합",
                )

elif view == "재무 추이":
    ticker = _select_ticker(active_watchlist, key="earnings_trend_ticker")
    if ticker:
        ticker_core = _ticker_rows(core_rows, ticker)
        if not ticker_core:
            st.info(f"{ticker}의 실제 financial_versions 재무 데이터가 없습니다.")
        else:
            history = pd.DataFrame(ticker_core)
            if "period_end" in history:
                history["period_end"] = pd.to_datetime(history["period_end"], errors="coerce")
                history = history.sort_values("period_end")
            fiscal_period = history.get("fiscal_period", pd.Series(index=history.index, dtype=str)).astype(str).str.upper()
            annual = history[fiscal_period == "FY"]
            selected_history = (annual.tail(4) if len(annual) >= 2 else history.tail(8)).copy()
            category = view_selector(
                "재무 범주",
                ("핵심 추이", "손익 구조", "재무상태", "현금흐름·주주환원", "Raw 근거"),
                key=f"earnings_financial_category:{ticker}",
                default="핵심 추이",
            )
            identity = ["ticker", "fiscal_year", "fiscal_period", "period_end", "filed_at", "form_type", "accession_no"]
            if category == "핵심 추이":
                selected_history["fcf_screen"] = [free_cash_flow(row) for row in selected_history.to_dict("records")]
                selected_history["sec_gaap_diluted_eps_screen"] = [
                    sec_gaap_diluted_eps(row) for row in selected_history.to_dict("records")
                ]
                figure = go.Figure()
                figure.add_trace(
                    go.Bar(x=selected_history.get("period_end"), y=selected_history.get("revenue"), name="매출", marker_color=PRIMARY)
                )
                figure.add_trace(
                    go.Bar(x=selected_history.get("period_end"), y=selected_history.get("net_income"), name="순이익", marker_color=TEXT)
                )
                figure.add_trace(
                    go.Scatter(x=selected_history.get("period_end"), y=selected_history.get("fcf_screen"), name="FCF", line={"color": MUTED, "width": 3})
                )
                figure.update_layout(**plotly_layout(height=430), barmode="group")
                st.plotly_chart(figure, width="stretch", config={"displaylogo": False})
                columns = identity + [
                    "revenue",
                    "operating_income_loss",
                    "net_income",
                    "fcf_screen",
                    "sec_gaap_diluted_eps_screen",
                ]
            elif category == "손익 구조":
                columns = identity + [
                    "revenue",
                    "cost_of_goods_and_services_sold",
                    "gross_profit",
                    "research_and_development_expenses",
                    "operating_income_loss",
                    "interest_expense",
                    "pretax_income_loss",
                    "income_taxes",
                    "net_income",
                    "net_income_to_common_shareholders",
                ]
            elif category == "재무상태":
                columns = identity + [
                    "assets",
                    "current_assets_total",
                    "cash_and_cash_equivalents",
                    "short_term_investments",
                    "trade_receivables",
                    "inventories",
                    "property_plant_equipment_net",
                    "goodwill",
                    "intangible_assets_excluding_goodwill",
                    "liabilities",
                    "current_liabilities_total",
                    "trade_payables",
                    "short_term_debt",
                    "current_portion_of_long_term_debt",
                    "long_term_debt",
                    "total_debt_including_current",
                    "common_equity",
                    "minority_interest_balance",
                    "preferred_stock",
                    "retained_earnings",
                ]
            elif category == "현금흐름·주주환원":
                columns = identity + [
                    "net_cash_from_operating_activities",
                    "net_cash_from_investing_activities",
                    "net_cash_from_financing_activities",
                    "cash_and_cash_equivalents",
                    "depreciation_amortization_cf",
                    "stock_based_compensation_cf",
                    "capital_expenses",
                    "stock_repurchase_payments",
                    "common_dividends_paid",
                    "operating_lease_current_debt_equivalent",
                    "operating_lease_non_current_debt_equivalent",
                ]
            else:
                columns = list(selected_history.columns)

            display_history = selected_history[[column for column in columns if column in selected_history]].copy()
            display_history = display_history.rename(
                columns={
                    "fiscal_year": "회계연도",
                    "fiscal_period": "기간",
                    "period_end": "결산일",
                    "filed_at": "공시일",
                    "revenue": "매출 · SEC GAAP",
                    "operating_income_loss": "영업이익 · SEC GAAP",
                    "net_income": "순이익 · SEC GAAP",
                    "fcf_screen": "FCF · 화면 계산",
                    "sec_gaap_diluted_eps_screen": "희석 EPS · SEC GAAP 계산",
                }
            )
            dataframe(display_history, key=f"earnings_trend_table:{ticker}:{category}")
            source_note(
                SOURCE_DB,
                SOURCE_CALC if category == "핵심 추이" else "",
                observed_at=selected_history.get("filed_at", pd.Series(dtype=object)).dropna().max() if "filed_at" in selected_history and selected_history["filed_at"].notna().any() else None,
                detail=(
                    "FCF=영업현금흐름-자본적지출; 두 값 모두 있을 때만 계산"
                    if category == "핵심 추이"
                    else "financial_versions 실제 저장 필드 · 결측은 —/빈 셀로 유지"
                ),
            )

elif view == "공시 근거":
    ticker = _select_ticker(active_watchlist, key="earnings_filing_ticker")
    if ticker:
        ticker_filings = sorted(
            [row for row in _ticker_rows(filing_rows, ticker) if row.get("form_type") in {"10-K", "10-Q"}],
            key=lambda row: str(row.get("filing_date") or ""),
            reverse=True,
        )
        if not ticker_filings:
            st.info(f"{ticker}의 10-K/10-Q 수집 장부가 없습니다.")
        else:
            filing_index = st.selectbox(
                "공시 건",
                range(len(ticker_filings)),
                format_func=lambda index: (
                    f"{ticker_filings[index].get('form_type') or '—'} · "
                    f"공시 {ticker_filings[index].get('filing_date') or '—'} · "
                    f"결산 {ticker_filings[index].get('report_date') or '—'}"
                ),
                key=f"earnings_filing_event:{ticker}",
            )
            filing = ticker_filings[filing_index]
            core = next(
                (
                    row
                    for row in _ticker_rows(core_rows, ticker)
                    if row.get("accession_no") == filing.get("accession_no")
                ),
                {},
            )
            fcf = free_cash_flow(core) if core else None
            gaap_eps = sec_gaap_diluted_eps(core) if core else None
            with st.container(border=True):
                st.markdown(f"**{filing.get('form_type') or '—'} 수집·공시 근거**")
                st.write(
                    f"공시일 · {filing.get('filing_date') or '—'} · 결산일 · {filing.get('report_date') or core.get('period_end') or '—'} · "
                    f"상태 · {filing.get('status') or '—'}"
                )
                st.caption(
                    f"accession_no · {filing.get('accession_no') or '—'} · source · {filing.get('source') or '—'} · "
                    f"facts/rows · {filing.get('facts_count') if filing.get('facts_count') is not None else '—'} / "
                    f"{filing.get('rows_count') if filing.get('rows_count') is not None else '—'}"
                )
                st.caption(
                    f"데이터 품질 · mapping {filing.get('mapping_version') or core.get('mapping_version') or '—'} · "
                    f"updated {filing.get('updated_at') or core.get('ingested_at') or '—'}"
                )
            with st.container(horizontal=True):
                st.metric("매출 · SEC GAAP", display_money(core.get("revenue")), border=True)
                st.metric("영업이익 · SEC GAAP", display_money(core.get("operating_income_loss")), border=True)
                st.metric("순이익 · SEC GAAP", display_money(core.get("net_income")), border=True)
                st.metric("FCF · 화면 계산", display_money(fcf), border=True)
            with st.container(border=True):
                st.write(
                    f"자산 · {display_money(core.get('assets'))} · 영업현금흐름 · {display_money(core.get('net_cash_from_operating_activities'))} · "
                    f"자본적지출 · {display_money(core.get('capital_expenses'))}"
                )
                st.write(f"희석 EPS · SEC GAAP 계산 · {display_number(gaap_eps)}")
                st.caption(
                    f"SEC GAAP EPS(기본/희석) · {display_number(core.get('eps_basic_gaap'))} / "
                    f"{display_number(core.get('eps_diluted_gaap'))}"
                )
                source_note(SOURCE_DB, SOURCE_CALC, observed_at=filing.get("filing_date"), detail="filing_processing 장부 + financial_versions exact accession_no")

elif view == "Discord 카드 전체":
    _render_discord_full(
        active_watchlist=active_watchlist,
        core_rows=core_rows,
        ticker_profiles=ticker_profiles,
    )

elif view == "확장 분석":
    _render_extended(active_watchlist=active_watchlist)
