"""공개 웹 원천 파서 모음.

활성 seed가 사용하는 CNN·multpl·미 재무부·CBOE를 포함한다. 원천 장애는
지표별 typed failure로 격리하며, 등록되지 않은 parser는 호출하지 않는다.
"""
from __future__ import annotations

import io
import math
import re
import time
import xml.etree.ElementTree as ET
from datetime import date
from functools import lru_cache

import pandas as pd
import requests

from investment_agent.data.macro.infrastructure.fetch import SOURCE_BUDGET_SEC, safe_fetch
from investment_agent.platform.logging import get_logger
from investment_agent.platform.retry import transient_retry

log = get_logger(__name__)


class WebClientError(RuntimeError):
    """웹 원천 수집 계약 위반의 공통 기반 예외."""


class WebConfigurationError(WebClientError):
    """source/parser 설정이 잘못되었을 때 발생한다."""


class UnsupportedWebParserError(WebConfigurationError):
    """등록되지 않은 parser를 fail-closed로 거부한다."""


class WebProviderError(WebClientError):
    """외부 페이지 호출 또는 응답 파싱이 실패했다."""

    def __init__(self, source: str, parser: str, cause: Exception) -> None:
        self.source = source
        self.parser = parser
        self.cause_type = type(cause).__name__
        # requests 예외의 URL에는 query API key가 들어갈 수 있으므로 cause 문자열은
        # 공개 메시지에 포함하지 않고 __cause__에만 보존한다.
        super().__init__(
            f"web provider {source}/{parser} failed ({self.cause_type})"
        )


class WebDataError(WebClientError):
    """parser 결과가 저장 가능한 시계열 계약을 만족하지 않는다."""

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}


@transient_retry()
def _get(url: str, **kw) -> requests.Response:
    """크롤링 대상 페이지는 순간 지연·5xx가 잦다. 한 번 실패로 그날 값을 통째로
    잃지 않도록 일시적 오류만 재시도한다(4xx 차단은 즉시 포기)."""
    r = requests.get(url, headers=_HEADERS, timeout=20, **kw)
    r.raise_for_status()
    return r


def _to_num(x) -> float:
    return float(re.sub(r"[^0-9.\-]", "", str(x)))


def _month_starts(start: date, end: date) -> list[date]:
    cur = date(start.year, start.month, 1)
    stop = date(end.year, end.month, 1)
    out = []
    while cur <= stop:
        out.append(cur)
        cur = date(cur.year + (cur.month == 12), 1 if cur.month == 12 else cur.month + 1, 1)
    return out


# CNN graphdata는 이 날짜보다 이른 시작일을 주면 200이 아니라 500을 돌려준다.
# (2020-09-19는 OK, 2020-06-01은 500 — 실측). 백필 창이 더 길어도 여기서 자른다.
_CNN_FEAR_GREED_FLOOR = date(2020, 9, 19)


def _cnn_fear_greed(start: date, end: date) -> pd.Series:
    """CNN 공포·탐욕 지수를 받아온다. 과거 기록도 함께 제공한다."""
    since = max(start, _CNN_FEAR_GREED_FLOOR)
    url = f"https://production.dataviz.cnn.io/index/fearandgreed/graphdata/{since.isoformat()}"
    data = _get(url).json().get("fear_and_greed_historical", {}).get("data", [])
    items = {pd.Timestamp(d["x"], unit="ms").normalize(): float(d["y"]) for d in data}
    return pd.Series(items).sort_index()


def _multpl(slug: str, start: date, end: date) -> pd.Series:
    """multpl.com의 월별 표에서 값을 읽어온다 (CAPE 등)."""
    html = _get(f"https://www.multpl.com/{slug}/table/by-month").text
    df = pd.read_html(io.StringIO(html))[0]
    df.columns = [str(c).strip().lower() for c in df.columns]
    series = pd.Series(
        [_to_num(v) for v in df["value"]],
        index=pd.to_datetime(df["date"], errors="coerce"),
    ).dropna().sort_index()
    return series[
        (series.index.date >= start) & (series.index.date <= end)
    ]


@lru_cache(maxsize=24)
def _treasury_curve_cached(start_iso: str, end_iso: str) -> pd.DataFrame:
    start = date.fromisoformat(start_iso)
    end = date.fromisoformat(end_iso)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
    }
    rows: list[dict] = []
    for month_start in _month_starts(start, end):
        url = (
            "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
            f"?data=daily_treasury_yield_curve&field_tdr_date_value_month={month_start:%Y%m}"
        )
        root = ET.fromstring(_get(url).text)
        for entry in root.findall("atom:entry", ns):
            props = entry.find("atom:content/m:properties", ns)
            if props is None:
                continue
            row = {child.tag.split("}", 1)[-1]: child.text for child in props}
            rows.append(row)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["NEW_DATE"] = pd.to_datetime(df["NEW_DATE"], errors="coerce").dt.normalize()
    for col in df.columns:
        if col.startswith("BC_"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["NEW_DATE"]).set_index("NEW_DATE").sort_index()
    return df[(df.index.date >= start) & (df.index.date <= end)]


def _treasury_curve(start: date, end: date) -> pd.DataFrame:
    return _treasury_curve_cached(start.isoformat(), end.isoformat())


def _treasury_series(field: str, start: date, end: date) -> pd.Series:
    df = _treasury_curve(start, end)
    if field not in df.columns:
        raise ValueError(f"Treasury field not found: {field}")
    return df[field].dropna().sort_index()


def _treasury_2y(start: date, end: date) -> pd.Series:
    return _treasury_series("BC_2YEAR", start, end)


def _treasury_10y(start: date, end: date) -> pd.Series:
    return _treasury_series("BC_10YEAR", start, end)


def _treasury_30y(start: date, end: date) -> pd.Series:
    return _treasury_series("BC_30YEAR", start, end)


def _treasury_spread_10y2y(start: date, end: date) -> pd.Series:
    df = _treasury_curve(start, end)
    return (df["BC_10YEAR"] - df["BC_2YEAR"]).dropna().sort_index()


def _treasury_spread_10y3m(start: date, end: date) -> pd.Series:
    df = _treasury_curve(start, end)
    return (df["BC_10YEAR"] - df["BC_3MONTH"]).dropna().sort_index()


# CBOE 일간 시장통계는 하루 한 장짜리 페이지뿐이라 구간을 채우려면 거래일마다 한 번씩
# 받아야 한다. 증분 창(14일)은 열 번 남짓으로 끝나고 백필만 이 상한까지 늘어난다.
# 상한을 넘으면 최근 쪽부터 채운다 — 52주 고저는 최근 구간이 있어야 성립한다.
_CBOE_MAX_DATED_REQUESTS = 900
# web 소스 예산 중 put/call 크롤이 쓸 수 있는 몫. 나머지는 같은 소스의 다른 여덟
# 지표 몫으로 남긴다.
_CBOE_BUDGET_SHARE = 0.5
_PCC_LABEL = "TOTAL PUT/CALL RATIO"
_PCC_VALUE_RE = re.compile(r'value[\\":\s]+([0-9]+\.[0-9]+)')


def _cboe_put_call_on(when: date) -> float | None:
    """그 거래일의 전체 Put/Call 비율. 휴장일이면 None.

    (yfinance ^CPC가 제공 중단돼 CBOE 일간 페이지에서 직접 파싱한다.)
    """
    text = _get(
        "https://www.cboe.com/us/options/market_statistics/daily/",
        params={"dt": when.isoformat()},
    ).text
    head = text.find(_PCC_LABEL)
    if head < 0:
        # 휴장일은 비율 블록 자체가 없다. 페이지 개편·차단도 같은 모양이지만 그때는
        # 구간 전체가 비므로 _validate_result가 빈 시계열로 잡아낸다.
        return None
    match = _PCC_VALUE_RE.search(text[head:head + 80])
    if match is None:
        raise ValueError("CBOE put/call 값 파싱 실패")
    return float(match.group(1))


def _cboe_put_call(start: date, end: date) -> pd.Series:
    """CBOE 일간 시장통계에서 전체 Put/Call 비율 구간을 읽어온다.

    하루치만 받으면 실행이 한 번 실패한 날의 값이 영구히 비어, 겹침 창 전체를 훑는다.
    """
    days = [day for day in pd.date_range(start, end, freq="D").date if day.weekday() < 5]
    if len(days) > _CBOE_MAX_DATED_REQUESTS:
        days = days[-_CBOE_MAX_DATED_REQUESTS:]
        log.warning(
            "cboe put/call window truncated to %s..%s (cap %d requests)",
            days[0], days[-1], _CBOE_MAX_DATED_REQUESTS,
        )
    # safe_fetch의 예산은 지표 *사이*에서만 본다. 이 지표는 요청을 최대 900번 보내므로
    # 그 안에서 스스로 멈추지 않으면 혼자 web 소스 전체를 삼킨다 — 실제로 백필에서
    # 예산을 다 써 FEAR_GREED가 "budget exhausted"로 실패했다. 그래서 전체가 아니라
    # 정해진 몫만 쓴다. 나머지 여덟 지표는 한 번씩만 받아 오므로 남는 몫으로 충분하다.
    # 최근 날짜부터 채우고 몫이 끝나면 거기까지만 돌려준다 — 부분 구간이 빈 구간보다 낫다.
    budget = SOURCE_BUDGET_SEC * _CBOE_BUDGET_SHARE
    deadline = time.monotonic() + budget if budget > 0 else None
    values: dict[pd.Timestamp, float] = {}
    for index, day in enumerate(reversed(days)):
        if deadline is not None and time.monotonic() > deadline:
            log.warning(
                "cboe put/call stopped at %s after %d of %d requests (share %.0fs)",
                day, index, len(days), budget,
            )
            break
        value = _cboe_put_call_on(day)
        if value is not None:
            values[pd.Timestamp(day)] = value
    return pd.Series(values, dtype="float64").sort_index()


def _cboe_vix(start: date, end: date) -> pd.Series:
    """CBOE 공식 VIX 일별 히스토리 CSV에서 종가를 읽는다."""
    raw = _get("https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv").text
    df = pd.read_csv(io.StringIO(raw))
    df.columns = [str(c).strip().upper() for c in df.columns]
    if not {"DATE", "CLOSE"}.issubset(df.columns):
        raise ValueError("CBOE VIX CSV columns changed")
    idx = pd.to_datetime(df["DATE"], format="%m/%d/%Y", errors="coerce")
    vals = pd.to_numeric(df["CLOSE"], errors="coerce")
    s = pd.Series(vals.values, index=idx).dropna().sort_index()
    return s[(s.index.date >= start) & (s.index.date <= end)]


PARSERS = {
    ("cnn",         "fear_greed"):     _cnn_fear_greed,
    ("multpl",      "shiller_pe"):     lambda s, e: _multpl("shiller-pe", s, e),
    ("treasury",    "2y"):             _treasury_2y,
    ("treasury",    "10y"):            _treasury_10y,
    ("treasury",    "30y"):            _treasury_30y,
    ("treasury",    "10y2y"):          _treasury_spread_10y2y,
    ("treasury",    "10y3m"):          _treasury_spread_10y3m,
    ("cboe",        "put_call"):       _cboe_put_call,
    ("cboe",        "vix"):            _cboe_vix,
}


def _validate_result(source: str, parser: str, result: pd.Series) -> pd.Series:
    """웹 parser의 최소 출력 계약을 검사한다."""
    if not isinstance(result, pd.Series):
        raise WebDataError(
            f"web parser {source}/{parser} returned "
            f"{type(result).__name__}, expected Series"
        )
    try:
        cleaned = result.dropna().sort_index()
    except Exception as exc:
        raise WebDataError(
            f"web parser {source}/{parser} returned an invalid series"
        ) from exc
    if cleaned.empty:
        raise WebDataError(
            f"web parser {source}/{parser} returned an empty series"
        )
    if not isinstance(cleaned.index, pd.DatetimeIndex):
        raise WebDataError(
            f"web parser {source}/{parser} returned a non-datetime index"
        )
    if cleaned.index.has_duplicates:
        raise WebDataError(
            f"web parser {source}/{parser} returned duplicate dates"
        )
    try:
        finite = all(math.isfinite(float(value)) for value in cleaned.values)
    except (TypeError, ValueError) as exc:
        raise WebDataError(
            f"web parser {source}/{parser} returned a non-numeric value"
        ) from exc
    if not finite:
        raise WebDataError(
            f"web parser {source}/{parser} returned a non-finite value"
        )
    return cleaned


def fetch_batch(
    indicators: list[dict], start: date, end: date,
) -> tuple[dict[str, pd.Series], list[dict]]:
    if start > end:
        raise WebConfigurationError("start must be on or before end")

    def _per(ind: dict) -> pd.Series:
        raw_params = ind.get("source_params")
        p = {} if raw_params is None else raw_params
        if not isinstance(p, dict):
            raise WebConfigurationError("source_params must be an object")
        source = p.get("source")
        parser = p.get("parser")
        if not isinstance(source, str) or not source.strip():
            raise WebConfigurationError("source_params.source is required")
        if not isinstance(parser, str) or not parser.strip():
            raise WebConfigurationError("source_params.parser is required")
        key = (source, parser)
        fn = PARSERS.get(key)
        if fn is None:
            raise UnsupportedWebParserError(
                f"unsupported web parser: {source}/{parser}"
            )
        try:
            result = fn(start, end)
        except WebClientError:
            raise
        except Exception as exc:
            raise WebProviderError(source, parser, exc) from exc
        return _validate_result(source, parser, result)
    return safe_fetch(log, indicators, _per)
