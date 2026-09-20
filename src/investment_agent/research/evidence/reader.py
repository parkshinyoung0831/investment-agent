"""PIT 데이터 읽기 조립. Data owner의 읽기를 판단 시각 기준으로 묶는다.

Research feature·label·valuation과 Trading 판단이 같은 시점 규칙으로 같은 사실을 읽게 하는 원천이다.
같은 실행 안의 재사용 캐시와 과거 재현용 로컬 mirror 상태를 소유한다. Trading 원장·후보 선정은 모른다.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from investment_agent.platform.serialization import normalize_ticker, parse_datetime
from investment_agent.research.features import db as features_db
from investment_agent.research.rl.contracts import normalize_symbols
from investment_agent.platform.logging import get_logger
from investment_agent.platform.retry import transient_retry
from investment_agent.platform.db.postgres import sb
from investment_agent.data.macro.repository import MacroRepository
from investment_agent.platform.db.postgres import Database
from investment_agent.data.macro.releases import db as econ_calendar_db
from investment_agent.data.institutional import persistence as institutional_persistence
from investment_agent.data.fundamentals.infrastructure.supabase import (
    expectations as fundamentals_expectations,
    segment_metrics as fundamentals_segments,
    share_class_snapshots as fundamentals_shares,
)
from investment_agent.data.market import persistence as market_db
from investment_agent.data.universe.persistence import (select_sp500_sector_map, select_sp500_membership_snapshots, select_tracked_tickers)

from investment_agent.research.storage.repository import ResearchStore

log = get_logger(__name__)


@transient_retry(attempts=4, max_wait=8.0)
def _historical_input_read(read: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """멱등인 과거 입력 GET 하나만 재시도해 이미 성공한 다른 도메인을 반복하지 않는다."""
    return read(*args, **kwargs)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("as_of_at must include timezone")
    return value.astimezone(timezone.utc).isoformat()


def _nearest_rows(
    rows: list[dict[str, Any]], *, point: datetime, limit: int
) -> list[dict[str, Any]]:
    """cutoff에 가까운 순으로 limit개만 남기고, 다시 시간순으로 되돌린다."""
    if len(rows) <= limit:
        return rows

    def distance(row: dict[str, Any]) -> float:
        scheduled = (row.get("release") or {}).get("scheduled_at")
        if not scheduled:
            return float("inf")
        try:
            return abs((parse_datetime(str(scheduled)) - point).total_seconds())
        except (TypeError, ValueError):
            return float("inf")

    nearest = sorted(rows, key=distance)[:limit]
    return sorted(nearest, key=lambda row: str((row.get("release") or {}).get("scheduled_at") or ""))


def guru_candidate_signals(
    current_by_manager: Mapping[str, Mapping[str, Any]],
    previous_by_manager: Mapping[str, Mapping[str, Any]],
    holdings: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, float | str]]:
    """PIT-effective holdings에서 후보용 raw Guru feature를 만든다.

    특정 원시 filing 하나를 고르는 대신, ``effective_accession_no``별 현재/직전
    공개 포트폴리오를 비교한다. 따라서 RESTATEMENT와 NEW HOLDINGS의 공개 시각을
    넘겨보지 않고, PUT/CALL/PRN은 equity consensus에서 제외한다.
    """
    equity_by_accession: dict[str, list[Mapping[str, Any]]] = {}
    for row in holdings:
        if row.get("position_kind") != "SHARES" or row.get("quantity_type") != "SH":
            continue
        equity_by_accession.setdefault(
            str(row.get("effective_accession_no") or ""), []
        ).append(row)

    result: dict[str, dict[str, Any]] = {}
    for manager, current_event in current_by_manager.items():
        current_accession = str(current_event.get("effective_accession_no") or "")
        previous_event = previous_by_manager.get(manager)
        previous_accession = str(
            previous_event.get("effective_accession_no") or ""
        ) if previous_event else ""
        current_rows = equity_by_accession.get(current_accession, [])
        previous_rows = equity_by_accession.get(previous_accession, [])
        current_total = sum(
            float(row.get("value_usd") or 0) for row in current_rows
        )

        def by_ticker(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, float]]:
            grouped: dict[str, dict[str, float]] = {}
            for row in rows:
                symbol = normalize_ticker(row.get("ticker"))
                if not symbol or row.get("mapping_status") not in {"mapped", "historical"}:
                    continue
                item = grouped.setdefault(symbol, {"quantity": 0.0, "value_usd": 0.0})
                item["quantity"] += float(row.get("quantity") or 0)
                item["value_usd"] += float(row.get("value_usd") or 0)
            return grouped

        current_by_ticker = by_ticker(current_rows)
        previous_by_ticker = by_ticker(previous_rows)
        for symbol in sorted(current_by_ticker.keys() | previous_by_ticker.keys()):
            current = current_by_ticker.get(symbol)
            previous = previous_by_ticker.get(symbol)
            feature = result.setdefault(
                symbol,
                {
                    "holder_count": 0.0,
                    "new_buy_count": 0.0,
                    "add_count": 0.0,
                    "hold_count": 0.0,
                    "reduce_count": 0.0,
                    "exit_count": 0.0,
                    "total_value_usd": 0.0,
                    "quantity_change_values": [],
                    "max_weight_pct": 0.0,
                },
            )
            if current is not None:
                feature["holder_count"] += 1.0
                feature["total_value_usd"] += current["value_usd"]
                feature["max_weight_pct"] = max(
                    feature["max_weight_pct"],
                    100 * current["value_usd"] / current_total if current_total else 0.0,
                )
            if previous is None:
                feature["new_buy_count"] += 1.0
            elif current is None:
                feature["exit_count"] += 1.0
            elif current["quantity"] > previous["quantity"]:
                feature["add_count"] += 1.0
                if previous["quantity"]:
                    feature["quantity_change_values"].append(
                        100 * (current["quantity"] - previous["quantity"])
                        / previous["quantity"]
                    )
            elif current["quantity"] < previous["quantity"]:
                feature["reduce_count"] += 1.0
                if previous["quantity"]:
                    feature["quantity_change_values"].append(
                        100 * (current["quantity"] - previous["quantity"])
                        / previous["quantity"]
                    )
            else:
                feature["hold_count"] += 1.0

    output: dict[str, dict[str, float | str]] = {}
    for symbol, values in result.items():
        average_values = values.pop("quantity_change_values")
        accumulation = values["new_buy_count"] + values["add_count"]
        distribution = values["reduce_count"] + values["exit_count"]
        output[symbol] = {
            **{key: float(value) for key, value in values.items()},
            "avg_quantity_change_pct": (
                sum(average_values) / len(average_values) if average_values else 0.0
            ),
            "consensus": (
                "accumulating" if accumulation > distribution
                else "distributing" if accumulation < distribution
                else "holding"
            ),
        }
    return output

ECON_MAX_ROWS_PER_KIND = 12
_ECON_RELEASE_KEYS = (
    "event_key", "series_id", "ref_period", "scheduled_at", "status", "schedule_confidence",
)
_ECON_FORECAST_KEYS = (
    "closing_survey_value", "closing_nowcast_value", "closing_own_model_value",
)


class PointInTimeReaderCache:
    """동일 실행의 point-in-time 입력 재사용과 local mirror 상태를 소유한다."""

    # 같은 판단 시각의 같은 조회를 한 실행 안에서 다시 보내지 않는다. 판단 하나가 비용·베타·스트레스·시장위험마다
    # 같은 종목 가격을 읽고, 13F 유효 보유 상태는 종목과 무관한데 종목마다 다시 만든다. 키에 판단 시각이 들어가
    # 시점 규칙은 그대로다. 장시간 프로세스가 늦게 적재된 값을 놓치지 않게 짧게만 기억한다.
    _MEMO_SECONDS = 600.0
    _MEMO_MAX_ENTRIES = 4096

    def memo(self, key: tuple, read):
        import threading
        import time

        state = self.__dict__.setdefault("_memo_state", {"lock": threading.Lock(), "values": {}})
        now = time.monotonic()
        with state["lock"]:
            cached = state["values"].get(key)
            if cached is not None and cached[1] > now:
                return cached[0]
        value = read()
        with state["lock"]:
            if len(state["values"]) >= self._MEMO_MAX_ENTRIES:
                state["values"].clear()
            state["values"][key] = (value, now + self._MEMO_SECONDS)
        return value

    def seed(self, key: tuple, value: Any) -> None:
        """날짜별 일괄 조회 결과를 기존 단건 계약의 캐시에 넣는다."""
        import threading
        import time

        state = self.__dict__.setdefault("_memo_state", {"lock": threading.Lock(), "values": {}})
        with state["lock"]:
            state["values"][key] = (value, time.monotonic() + self._MEMO_SECONDS)

    def drop_historical_inputs(self) -> None:
        """다음 재현 날짜를 넣기 전에 이전 날짜의 대형 종목별 입력 묶음을 버린다."""
        import threading

        state = self.__dict__.setdefault("_memo_state", {"lock": threading.Lock(), "values": {}})
        date_scoped = {
            "historical_replay_inputs", "fundamentals_pit", "observed_consensus",
            "share_class_snapshots_pit", "segment_snapshot",
        }
        with state["lock"]:
            state["values"] = {
                key: value for key, value in state["values"].items()
                if not key or key[0] not in date_scoped
            }

    def mirror(self, as_of_at: datetime | None = None):
        """로컬 사본이 이 조회를 답할 수 있으면 그 사본. 없거나 오래됐으면 None — Supabase로 읽는다.

        사본은 Supabase 원본의 계산용 복사다(`data.market.local_mirror`). 판단마다 종목별로 원격 표를 읽지 않게 한다.
        """
        from investment_agent.data.market.local_mirror.store import LocalMirror

        mirror = self.__dict__.get("_local_mirror")
        if mirror is None:
            mirror = self.__dict__.setdefault("_local_mirror", LocalMirror())
        moment = as_of_at or datetime.now(timezone.utc)
        return mirror if mirror.covers(moment) else None


class PitReader:
    """Data owner 읽기를 판단 시각 기준으로 조립하는 reader. Trading 원장은 다루지 않는다."""

    def _reader_cache(self) -> PointInTimeReaderCache:
        return self.__dict__.setdefault("_reader_cache_state", PointInTimeReaderCache())

    def _memo(self, key: tuple, read):
        return self._reader_cache().memo(key, read)

    def _memo_seed(self, key: tuple, value: Any) -> None:
        self._reader_cache().seed(key, value)

    def _memo_drop_historical_inputs(self) -> None:
        self._reader_cache().drop_historical_inputs()

    def _mirror(self, as_of_at: datetime | None = None):
        return self._reader_cache().mirror(as_of_at)

    def current_tracked_tickers(self) -> list[str]:
        """범용 수집 게이트 universe.securities.is_tracked의 현재 종목을 반환한다."""
        mirror = self._mirror()
        if mirror is not None:
            return mirror.tracked_tickers()
        return sorted({str(ticker).upper() for ticker in select_tracked_tickers()})

    def historical_sp500_membership(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """universe 스키마의 owner에게 위임한다. 로컬 사본이 그 기간을 덮으면 사본의 같은 규칙으로 답한다."""
        mirror = self._mirror(datetime.combine(end_date, datetime.min.time(), tzinfo=timezone.utc))
        if mirror is not None:
            return mirror.membership_snapshots(start_date=start_date, end_date=end_date)
        return select_sp500_membership_snapshots(start_date=start_date, end_date=end_date)

    def sp500_sector_map(self, tickers: list[str] | tuple[str, ...]) -> dict[str, str]:
        symbols = sorted({str(ticker).upper() for ticker in tickers})
        if not symbols:
            return {}
        mirror = self._mirror()
        if mirror is not None:
            return mirror.sector_map(symbols)
        return select_sp500_sector_map(symbols)

    def market_prices(self, ticker: str, as_of_at: datetime, limit: int = 260) -> list[dict]:
        """market 스키마의 owner에게 위임한다 — 조회 규칙을 두 곳에 두지 않는다.

        기억한 결과는 행 사본으로 돌려준다. 부르는 쪽이 행을 고쳐도 다음 호출이 오염되지 않는다.
        """
        mirror = self._mirror(as_of_at)
        if mirror is not None:
            return mirror.price_history_as_of(ticker, as_of_at, limit=limit)
        rows = self._memo(
            ("market_prices", str(ticker).upper(), as_of_at.isoformat(), int(limit)),
            lambda: market_db.price_history_as_of(ticker, as_of_at, limit=limit),
        )
        return [dict(row) for row in rows]

    def closes_on_date(self, tickers: Sequence[str], trade_date: date) -> dict[str, float]:
        """연구 전용 횡단면 종가 — evidence/feature 경로에서 부르지 않는다(미래 가격일 수 있다)."""
        return market_db.closes_on_date(tickers, trade_date)

    def trading_dates(self, reference_ticker: str, *, start: date, end: date) -> list[date]:
        """market 스키마의 owner에게 위임한다."""
        return market_db.trading_dates(reference_ticker, start=start, end=end)

    def split_history(self, ticker: str) -> list[dict]:
        """market 스키마의 owner에게 위임한다."""
        rows = self._memo(
            ("split_history", str(ticker).upper()),
            lambda: market_db.split_history(ticker),
        )
        return [dict(row) for row in rows]

    def technical_snapshot(self, ticker: str, as_of_at: datetime) -> list[dict]:
        """Research DuckDB feature store의 owner에게 위임한다.

        종목마다 DuckDB 파일을 새로 열면 종목당 약 0.3초가 든다. 같은 판단 시각이면 전 종목의 최신 행을 한 번에
        읽어 두고 나눠 준다(조건은 종목별 조회와 같다: 거래일 ≤ 판단일, 적재 시각 ≤ 판단 시각).
        """
        if as_of_at.tzinfo is None:
            raise ValueError("as_of_at must include timezone")
        latest = self._memo(
            ("technical_snapshot", as_of_at.isoformat()),
            lambda: features_db.latest_signals_as_of(as_of_at),
        )
        row = latest.get(str(ticker))
        return [dict(row)] if row is not None else []

    def fundamentals(self, ticker: str, as_of_at: datetime, limit: int = 12) -> list[dict]:
        """fundamentals 스키마의 owner에게 위임한다."""
        return fundamentals_expectations.security_fundamentals_as_of(ticker, as_of_at, limit=limit)

    def fundamentals_pit(self, ticker: str, as_of_at: datetime, limit: int = 12) -> list[dict]:
        """공시일 cutoff까지 공개된 canonical financials 행을 반환한다."""
        rows = self._memo(
            ("fundamentals_pit", str(ticker).upper(), as_of_at.isoformat(), int(limit)),
            lambda: fundamentals_expectations.security_fundamentals_filed_before(
                ticker, as_of_at, limit=limit
            ),
        )
        return [dict(row) for row in rows]

    def estimates(self, ticker: str, as_of_at: datetime, limit: int = 12) -> dict[str, list[dict]]:
        """관측 컨센서스만 담아 돌려준다 — 모양은 evidence 계약이 정한다."""
        consensus = self._memo(
            ("observed_consensus", str(ticker).upper(), as_of_at.isoformat(), int(limit)),
            lambda: fundamentals_expectations.observed_consensus_as_of(
                ticker, as_of_at, limit=limit
            ),
        )
        return {"consensus": [dict(row) for row in consensus]}

    def macro_snapshot(self, as_of_at: datetime) -> dict[str, Any]:
        """macro 스키마의 owner에게 위임한다."""
        return MacroRepository(Database(sb)).observation_snapshot_as_of(as_of_at)

    def macro_histories(
        self, series_ids: Sequence[str], *, as_of_at: datetime, lookback_days: int = 120,
    ) -> dict[str, list[tuple[date, float]]]:
        """series별 판단 시점까지 알려진 (관측일, 값) 이력. 노출 규칙이 수준과 변화폭을 함께 본다."""
        observed = MacroRepository(Database(sb)).observations(
            list(series_ids), since=as_of_at.date() - timedelta(days=lookback_days),
        )
        output: dict[str, list[tuple[date, float]]] = {}
        for item in observed:
            if item.known_at(as_of_at) and item.value is not None:
                output.setdefault(item.series_id, []).append((item.ref_period, float(item.value)))
        return output

    def segment_snapshot(self, ticker: str, as_of_at: datetime) -> dict[str, Any]:
        """fundamentals 스키마의 owner에게 위임한다."""
        return dict(self._memo(
            ("segment_snapshot", str(ticker).upper(), as_of_at.isoformat()),
            lambda: fundamentals_segments.segment_snapshot_as_of(ticker, as_of_at),
        ))

    def prepare_historical_replay(self, tickers: Sequence[str], as_of_at: datetime) -> None:
        """과거 재현에 필요한 원격 도메인을 날짜당 한 번씩 읽어 단건 계약 캐시에 배치한다."""
        symbols = sorted({normalize_ticker(ticker) for ticker in tickers})
        key = ("historical_replay_inputs", tuple(symbols), as_of_at.isoformat())

        def read() -> bool:
            self._memo_drop_historical_inputs()
            with ThreadPoolExecutor(max_workers=4, thread_name_prefix="historical-input") as executor:
                fundamentals_future = executor.submit(
                    _historical_input_read, fundamentals_expectations.securities_fundamentals_filed_before,
                    symbols, as_of_at, limit=12,
                )
                consensus_future = executor.submit(
                    _historical_input_read, fundamentals_expectations.observed_consensus_for_tickers_as_of,
                    symbols, as_of_at, limit=12,
                )
                shares_future = executor.submit(
                    _historical_input_read, fundamentals_shares.share_class_snapshots_for_tickers_filed_before,
                    symbols, as_of_at, limit=24,
                )
                segments_future = executor.submit(
                    _historical_input_read, fundamentals_segments.segment_snapshots_as_of, symbols, as_of_at,
                )
                fundamentals = fundamentals_future.result()
                consensus = consensus_future.result()
                shares = shares_future.result()
                segments = segments_future.result()
            fundamentals_by_ticker: dict[str, list[dict]] = {ticker: [] for ticker in symbols}
            for row in fundamentals:
                fundamentals_by_ticker.setdefault(normalize_ticker(row.get("ticker")), []).append(dict(row))
            mirror = self._mirror(as_of_at)
            splits = mirror.split_histories(symbols) if mirror is not None else {
                ticker: market_db.split_history(ticker) for ticker in symbols
            }
            for ticker in symbols:
                self._memo_seed(("fundamentals_pit", ticker, as_of_at.isoformat(), 12),
                                fundamentals_by_ticker.get(ticker, []))
                self._memo_seed(("observed_consensus", ticker, as_of_at.isoformat(), 12),
                                list(consensus.get(ticker, [])))
                self._memo_seed(("share_class_snapshots_pit", ticker, as_of_at.isoformat(), 24),
                                list(shares.get(ticker, [])))
                self._memo_seed(("segment_snapshot", ticker, as_of_at.isoformat()),
                                dict(segments.get(ticker, {"filings": [], "metrics": []})))
                self._memo_seed(("split_history", ticker), list(splits.get(ticker, [])))
            return True

        self._memo(key, read)

    def segment_capability(self) -> dict[str, Any]:
        """코드에 구현된 도메인 저장소 기능을 반환한다.

        실행 성공 여부는 Discord/GitHub에서 관제하고, 투자 컨텍스트는 실제
        ``fundamentals.filing_processing``와 ``segment_metrics`` 행의 유무로 판단한다.
        """
        return {
            "availability": "available",
            "source": "fundamentals.filing_processing+segment_metrics",
        }

    def guru_snapshot(self, ticker: str, as_of_at: datetime) -> dict[str, Any]:
        symbol = normalize_ticker(ticker)
        current, previous, holdings = self._effective_guru_state(as_of_at)
        signals = guru_candidate_signals(current, previous, holdings)
        relevant_accessions = {
            str(event["effective_accession_no"])
            for event in [*current.values(), *previous.values()]
        }
        positions = [
            row for row in holdings
            if str(row.get("effective_accession_no") or "") in relevant_accessions
            and normalize_ticker(row.get("ticker")) == symbol
        ]
        filings = [
            {
                "accession_no": event["effective_accession_no"],
                "manager_cik": event["manager_cik"],
                "period_end": event["period_end"],
                "filing_date": event["effective_filing_date"],
                "accepted_at": event["effective_accepted_at"],
                "form_type": event["effective_form_type"],
                "report_type": event["effective_report_type"],
                "amendment_type": event["effective_amendment_type"],
                "amendment_no": event["effective_amendment_no"],
                "source_url": event["effective_source_url"],
            }
            for event in current.values()
        ]
        return {
            "filings": sorted(filings, key=lambda row: str(row["accepted_at"]), reverse=True),
            "positions": positions,
            "features": signals.get(symbol, {}),
        }

    def econ_snapshot(
        self,
        as_of_at: datetime,
        lookback_days: int = 14,
        max_rows_per_kind: int = ECON_MAX_ROWS_PER_KIND,
    ) -> dict[str, Any]:
        """관련 발표를 먼저 선택하고, 같은 cutoff 이전의 마지막 상태를 읽는다.

        이 결과는 LLM 프롬프트에 통째로 들어간다. 같은 값을 평면 키와 중첩 그룹에
        두 번 담거나 창 안의 모든 행을 그대로 넘기면 프롬프트가 provider 한도를
        넘어 판단 자체가 시작되지 않는다 — 실측(2026-09-03)으로 번들의 69%가
        여기였다. 그래서 중복을 걷어내고 cutoff에 가까운 행만 남긴다.
        """
        if int(max_rows_per_kind) < 1:
            raise ValueError("max_rows_per_kind must be positive")
        # 조회는 macro owner가, 프롬프트에 무엇을 남길지는 여기가 정한다.
        rows = econ_calendar_db.select_snapshot_rows(
            as_of_at=as_of_at, lookback_days=lookback_days, lookahead_days=30
        )
        point = parse_datetime(_iso(as_of_at))
        result: dict[str, list[dict[str, Any]]] = {"events": [], "results": [], "forecasts": []}
        for row in rows:
            release = {key: row.get(key) for key in _ECON_RELEASE_KEYS}
            actual = row.get("latest_actual_value")
            forecast = next(
                (row.get(key) for key in _ECON_FORECAST_KEYS if row.get(key) is not None), None
            )
            base = {
                "release": release,
                "series_name_ko": row.get("series_name_ko"),
                "unit": row.get("unit"),
                # owner가 cutoff 이전 버전만 조립한다. 발표 예정시각은 자료를
                # 알게 된 시각이 아니므로 이 스냅샷의 cutoff를 보수적 상한으로 쓴다.
                "collected_at": point.isoformat(),
            }
            # 발표 하나가 여러 목록에 들어간다 — 예정된 사건이면서 값이 나온 것이고
            # 예상도 있었던 것이다. 어느 목록에 넣을지는 그 행이 실제로 무엇을
            # 들고 있는지가 정한다.
            result["events"].append({**base, "scheduled_at": row.get("scheduled_at"),
                                     "status": row.get("status")})
            if actual is not None:
                result["results"].append({**base, "actual": actual,
                                          "first_actual_value": row.get("first_actual_value"),
                                          "revision": row.get("revision")})
            if forecast is not None:
                result["forecasts"].append({**base, "forecast": forecast,
                                            "market_surprise": row.get("market_surprise"),
                                            "model_error": row.get("model_error")})
        for kind, entries in result.items():
            result[kind] = _nearest_rows(entries, point=point, limit=int(max_rows_per_kind))
        return result

    def _effective_guru_state(
        self,
        as_of_at: datetime,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
        """institutional 스키마의 owner에게 위임한다 — 유효 신고 선택 규칙은 그쪽 domain 지식이다.

        종목과 무관한 전체 13F 상태라 판단 시각마다 한 번만 만든다. 부르는 쪽은 읽기만 한다.
        """
        return self._memo(
            ("effective_guru_state", as_of_at.isoformat()),
            lambda: institutional_persistence.effective_portfolio_state(as_of_at),
        )

    def share_class_snapshots_pit(
        self,
        ticker: str,
        as_of_at: datetime,
        limit: int = 24,
    ) -> list[dict[str, Any]]:
        """공시 수리 시각이 cutoff 이전인 발행주식수 snapshot만 반환한다."""
        rows = self._memo(
            ("share_class_snapshots_pit", str(ticker).upper(), as_of_at.isoformat(), int(limit)),
            lambda: fundamentals_shares.share_class_snapshots_filed_before(
                ticker, as_of_at, limit=limit
            ),
        )
        return [dict(row) for row in rows]

    def valuation_observation_rows(
        self,
        symbols: tuple[str, ...],
        *,
        start_as_of: str,
        end_as_of: str,
        source_kind: str = "live_shadow",
    ) -> list[dict[str, Any]]:
        """서류철·feature가 읽는 point-in-time 밸류에이션 관측값이다."""
        normalized = normalize_symbols(symbols)
        start = parse_datetime(start_as_of)
        end = parse_datetime(end_as_of)
        if end < start:
            raise ValueError("valuation end_as_of must not precede start_as_of")
        rows = ResearchStore(read_only=True).records(
            "valuation_observations",
            start_as_of=start.isoformat(),
            end_as_of=end.isoformat(),
        )
        return [
            row for row in rows
            if str(row.get("source_kind")) == source_kind
            and normalize_ticker(str(row.get("ticker"))) in normalized
        ]

    def forward_prices_for_labels(
        self,
        ticker: str,
        *,
        after_date: str,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        """label 전용 미래 종가다 — evidence/feature 경로에서 절대 부르지 않는다."""
        return market_db.forward_closes_after(ticker, after_date=after_date, limit=limit)

    def label_price_rows(
        self, tickers: Sequence[str], *, start: date, end: date,
    ) -> list[dict[str, Any]]:
        """확정 라벨용 종가 창. 로컬 사본을 우선하고 없으면 owner의 묶음 조회를 쓴다."""
        point = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
        mirror = self._mirror(point)
        if mirror is not None:
            return mirror.closes_between(tickers, start=start, end=end)
        return market_db.close_window_for_labels(tickers, start=start, end=end)

    def rl_historical_membership_rows(
        self,
        *,
        start_as_of: str,
        end_as_of: str,
    ) -> list[dict[str, Any]]:
        """현재 tracked를 과거에 대입하지 않는 MembershipTimeline 입력 행이다."""
        start = parse_datetime(start_as_of)
        end = parse_datetime(end_as_of)
        if end < start:
            raise ValueError("membership end_as_of must not precede start_as_of")
        snapshots = self.historical_sp500_membership(
            start_date=start.date(),
            end_date=end.date(),
        )
        return [
            {
                "effective_at": f"{row['effective_date']}T00:00:00+00:00",
                "symbols": list(row["symbols"]),
                "source_id": str(row.get("source_hash") or row.get("source") or ""),
                "source_kind": "historical_point_in_time",
            }
            for row in snapshots
        ]

    def price_path(self, ticker: str, start_date: date, limit: int = 80) -> list[dict]:
        """사후 평가용 경로. PIT 조회가 아니다."""
        return market_db.price_path_from(ticker, start_date, limit=limit)


__all__ = ["PitReader", "PointInTimeReaderCache", "guru_candidate_signals"]
