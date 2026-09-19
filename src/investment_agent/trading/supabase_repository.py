"""Trading 원장과 domain owner 사이의 저장소 경계.

판단·신호·모델·포트폴리오의 영구 원장은 v1 ``trading`` schema가 소유한다.
재계산 가능한 research 산출물은 Supabase에 저장하지 않는다.
"""
from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

import investment_agent.research.adapters.trading as research_adapter
from investment_agent.trading.decision.candidate_ranker import (
    FACTOR_SNAPSHOT_MAX_AGE_DAYS,
    select_factor_candidates,
    PriorityCandidate,
    assemble_candidate_features,
    merge_priority_lane,
    priority_candidates,
    rank_candidate_features,
    validate_live_candidate_as_of,
)
from investment_agent.trading.contracts import ContractError, parse_datetime
from investment_agent.platform.serialization import canonical_json
from investment_agent.research.adapters.trading import (
    FEATURE_VERSION,
    EvaluationSummary,
    PromotionDecision,
    latest_cross_section,
    latest_technical_signals_as_of,
    normalize_symbols,
    score_cross_section,
    technical_features_since,
)
from investment_agent.trading.portfolio.signal_book import SignalBatch, SignalRecord
from investment_agent.execution.orders.snapshots import AccountSnapshot
from investment_agent.trading.decision.universe import normalize_ticker
from investment_agent.trading.decision.event_impact import THEME_BY_NAME, global_event_priorities
from investment_agent.trading.portfolio.market_risk import estimate_betas
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
from investment_agent.data.universe.persistence import (
    select_security_profiles,
    select_security_ids_by_ticker,
    select_sp500_membership_snapshots,
    select_tickers_by_security_id,
    select_tracked_tickers,
)

# 매크로 최신값 탐색 창(일). 갱신이 멎은 지표도 마지막 값을 잃지 않을 만큼 넉넉히.

log = get_logger(__name__)


@transient_retry(attempts=4, max_wait=8.0)
def _historical_input_read(read: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """멱등인 과거 입력 GET 하나만 재시도해 이미 성공한 다른 도메인을 반복하지 않는다."""
    return read(*args, **kwargs)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("as_of_at must include timezone")
    return value.astimezone(timezone.utc).isoformat()


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _security_id(ticker: str) -> int:
    symbol = normalize_ticker(ticker)
    value = select_security_ids_by_ticker([symbol]).get(symbol)
    if value is None:
        raise RuntimeError(f"unknown universe security: {symbol}")
    return value


def _security_ids(tickers: Sequence[str]) -> dict[str, int]:
    symbols = sorted({normalize_ticker(ticker) for ticker in tickers})
    result = select_security_ids_by_ticker(symbols)
    missing = [symbol for symbol in symbols if symbol not in result]
    if missing:
        raise RuntimeError(f"unknown universe securities: {missing[:10]}")
    return result


def _segment_candidate_signals(
    filings: Sequence[dict[str, Any]],
    metrics: Sequence[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    """종목별 최신 공시의 세그먼트 집중도와 검증 품질만 축약한다."""
    latest_by_ticker: dict[str, dict[str, Any]] = {}
    for row in filings:
        symbol = normalize_ticker(row.get("ticker"))
        current = latest_by_ticker.get(symbol)
        key = (str(row.get("filing_date") or ""), str(row.get("accession_no") or ""))
        current_key = (
            str(current.get("filing_date") or ""),
            str(current.get("accession_no") or ""),
        ) if current else ("", "")
        if symbol and key > current_key:
            latest_by_ticker[symbol] = row

    metrics_by_accession: dict[str, list[dict[str, Any]]] = {}
    for row in metrics:
        metrics_by_accession.setdefault(str(row.get("accession_no") or ""), []).append(row)
    result: dict[str, dict[str, float]] = {}
    for symbol, filing in latest_by_ticker.items():
        rows = metrics_by_accession.get(str(filing.get("accession_no") or ""), [])
        axis_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            revenue = _finite(row.get("revenue"))
            if revenue is None or revenue <= 0:
                continue
            key = (str(row.get("segment_type") or ""), str(row.get("axis") or ""))
            axis_groups.setdefault(key, []).append(row)
        candidates: list[tuple[float, str, float]] = []
        for key, group in axis_groups.items():
            revenues = [float(row["revenue"]) for row in group]
            total = sum(revenues)
            if total <= 0:
                continue
            coverage_values = [
                value for value in (_finite(row.get("coverage_ratio")) for row in group)
                if value is not None
            ]
            coverage = (
                sum(min(1.0, max(0.0, value)) for value in coverage_values)
                / len(coverage_values)
                if coverage_values else 0.0
            )
            verified = sum(row.get("quality_status") == "verified" for row in group) / len(group)
            quality = coverage * verified
            concentration = sum((revenue / total) ** 2 for revenue in revenues)
            candidates.append((quality, "|".join(key), concentration))
        if candidates:
            quality, _axis_key, concentration = max(
                candidates, key=lambda item: (item[0], item[1])
            )
            result[symbol] = {
                "quality": quality,
                "concentration": concentration,
            }
    return result


def _guru_candidate_signals(
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
#: 예상값 출처의 우선순위. 시장 컨센서스가 있으면 그것을, 없으면 nowcast를,
#: 그것도 없으면 자체 모델을 쓴다.
_ECON_FORECAST_KEYS = (
    "closing_survey_value", "closing_nowcast_value", "closing_own_model_value",
)


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


class SupabaseRepository:
    """Reader·trading 원장·Research artifact 저장소를 잇는 호환 façade."""

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

    @staticmethod
    def _research_store(*, read_only: bool = False) -> Any:
        return research_adapter.open_research_store(read_only=read_only)

    @staticmethod
    def _trading_repository():
        """v1 trading 원장의 domain owner를 지연 생성한다."""
        from investment_agent.trading.repository import TradingRepository

        return TradingRepository()

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
    def _candidate_last_analyzed(
        self,
        tickers: Sequence[str],
        *,
        as_of_at: datetime,
    ) -> dict[str, datetime]:
        """실제로 성공 판단이 저장된 case만 마지막 분석 시각으로 인정한다.

        판단 원장은 Supabase가 아니라 로컬 runtime이 소유한다. 전에는 여기서만
        Postgres `trading` 스키마를 읽고 있었는데 그 스키마는 선언에 없다 —
        Data API가 닫혀 있는 동안 모든 요청이 같은 오류로 막혀서 그 사실이
        드러나지 않았고, 열자마자 후보 선정이 PGRST106으로 죽었다.
        """
        from investment_agent.reporting.readers.runtime import read_local_rows

        members = {normalize_ticker(ticker) for ticker in tickers}
        latest: dict[str, datetime] = {}
        # 판단 원장은 ticker가 아니라 security_id를 저장한다. 신원 조회기를 넘기지 않으면 reader가
        # 판단이 하나라도 있는 순간부터 매번 실패해 후보 선정 전체가 멈춘다.
        for row in read_local_rows("security_decisions", canonical_db=Database(sb)):
            if str(row.get("status") or "") not in {"completed", "abstained"}:
                continue
            symbol = normalize_ticker(str(row.get("ticker") or ""))
            if symbol not in members:
                continue
            raw = str(row.get("as_of_at") or "")
            if not raw:
                continue
            analyzed_at = parse_datetime(raw).astimezone(timezone.utc)
            if analyzed_at > as_of_at:
                continue  # 미래 판단은 이 as_of 기준의 coverage가 아니다.
            current = latest.get(symbol)
            if current is None or analyzed_at > current:
                latest[symbol] = analyzed_at
        return latest

    def _candidate_market_rows(
        self,
        tickers: Sequence[str],
        as_of_at: datetime,
    ) -> list[dict[str, Any]]:
        since = as_of_at.date() - timedelta(days=60)
        # 창 하나를 한 번에 읽는다. 종목마다 부르면 종목당 왕복이 네 번이고, 봉은
        # 전체 이력을 읽은 뒤 잘라 낸다 — 후보 선정은 창 안의 종가·거래량만 본다.
        return market_db.price_window_as_of(
            sorted({normalize_ticker(value) for value in tickers}),
            start=since,
            as_of_at=as_of_at,
        )

    def _candidate_technical_rows(
        self,
        tickers: Sequence[str],
        as_of_at: datetime,
    ) -> list[dict[str, Any]]:
        since = (as_of_at.date() - timedelta(days=21)).isoformat()
        wanted = {normalize_ticker(value) for value in tickers}
        until = as_of_at.date().isoformat()
        rows: list[dict[str, Any]] = []
        # 창 하나를 한 번에 읽는다. 종목마다 부르면 저장소 연결이 종목 수만큼 열린다.
        for row in technical_features_since(since):
            if normalize_ticker(str(row.get("ticker") or "")) not in wanted:
                continue
            if str(row.get("trade_date") or "") > until:
                continue
            ingested_at = row.get("ingested_at")
            if ingested_at and parse_datetime(str(ingested_at)) > as_of_at:
                continue
            rows.append(dict(row))
        return sorted(rows, key=lambda row: (str(row.get("ticker")), str(row.get("trade_date"))))

    def _candidate_fundamental_rows(
        self,
        tickers: Sequence[str],
        as_of_at: datetime,
    ) -> list[dict[str, Any]]:
        since = as_of_at.date() - timedelta(days=1100)
        # 종목마다 부르면 종목당 왕복이 세 번이다(증권→재무→공시).
        rows = [
            row for row in fundamentals_expectations.securities_fundamentals_as_of(
                sorted({normalize_ticker(value) for value in tickers}), as_of_at, limit=520
            )
            if since.isoformat() <= str(row.get("filed_at") or "")
            and str(row.get("filed_at") or "") <= as_of_at.date().isoformat()
        ]
        return sorted(
            rows,
            key=lambda row: (
                str(row.get("ticker") or ""),
                str(row.get("filed_at") or ""),
                str(row.get("period_end") or ""),
            ),
        )

    def _candidate_segment_signals(
        self,
        tickers: Sequence[str],
        as_of_at: datetime,
    ) -> dict[str, dict[str, float]]:
        # 종목마다 부르면 종목당 왕복이 네 번 이상이다(증권→공시→처리상태→지표).
        snapshots = fundamentals_segments.segment_snapshots_as_of(
            sorted({normalize_ticker(value) for value in tickers}), as_of_at
        )
        filings: list[dict[str, Any]] = []
        metrics: list[dict[str, Any]] = []
        for snapshot in snapshots.values():
            filings.extend(snapshot.get("filings", []))
            metrics.extend(snapshot.get("metrics", []))
        return _segment_candidate_signals(filings, metrics)


    def _candidate_guru_signals(
        self,
        tickers: Sequence[str],
        as_of_at: datetime,
    ) -> dict[str, dict[str, float | str]]:
        current, previous, holdings = self._effective_guru_state(as_of_at)
        all_signals = _guru_candidate_signals(current, previous, holdings)
        wanted = {normalize_ticker(ticker) for ticker in tickers}
        return {ticker: signal for ticker, signal in all_signals.items() if ticker in wanted}

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
    def candidate_tickers(
        self,
        limit: int = 50,
        *,
        as_of_at: datetime,
    ) -> list[str]:
        """분석할 종목: 새 정보가 생긴 종목 먼저, 그다음 factor 상위 보유 후보.

        factor 횡단면이 없으면(feature 적재 전·중단) 예전 다중 도메인 순환 랭커로 고른다. 분석 대상 선정은
        주문이 아니므로 fail-open이고, 어느 경로로 골랐는지 로그에 남긴다.
        """
        as_of_at = validate_live_candidate_as_of(as_of_at)
        tickers = self.current_tracked_tickers()
        if not tickers:
            return []
        last_analyzed = self._last_attempted(tickers, as_of_at=as_of_at)
        fundamental_rows = self._candidate_fundamental_rows(tickers, as_of_at)
        latest_filed: dict[str, str] = {}
        for row in fundamental_rows:
            ticker = normalize_ticker(row.get("ticker"))
            filed = str(row.get("filed_at") or "")
            if ticker and filed > latest_filed.get(ticker, ""):
                latest_filed[ticker] = filed
        held = self._candidate_held_tickers()
        priority = priority_candidates(
            tickers=tickers,
            held_tickers=held,
            last_analyzed_at=last_analyzed,
            latest_filed_at=latest_filed,
            event_features=self._candidate_event_features(as_of_at),
            as_of_at=as_of_at,
        )
        factor_scores = self._candidate_factor_scores(tickers, as_of_at)
        if factor_scores is not None:
            snapshot_as_of, scores = factor_scores
            factor_ranked = select_factor_candidates(
                {ticker: score for ticker, score in scores.items() if ticker in set(tickers)},
                held_tickers=held, last_analyzed_at=last_analyzed, as_of_at=as_of_at,
            )
            selected = merge_priority_lane(priority, [row.ticker for row in factor_ranked], limit=limit)
            log.info(
                "ai investor candidate ranking path=factor as_of=%s snapshot=%s universe=%d selected=%s "
                "priority=%s factor=%s",
                as_of_at.isoformat(), snapshot_as_of, len(tickers), selected,
                {item.ticker: item.reason for item in priority},
                {row.ticker: [row.reason, None if row.composite is None else round(row.composite, 4)]
                 for row in factor_ranked if row.ticker in selected},
            )
            return selected
        features = assemble_candidate_features(
            tickers,
            last_analyzed_at=last_analyzed,
            market_rows=self._candidate_market_rows(tickers, as_of_at),
            technical_rows=self._candidate_technical_rows(tickers, as_of_at),
            fundamental_rows=fundamental_rows,
            segment_signals=self._candidate_segment_signals(tickers, as_of_at),
            guru_signals=self._candidate_guru_signals(tickers, as_of_at),
        )
        ranking = rank_candidate_features(features, as_of_at=as_of_at, limit=limit + len(priority))
        selected = merge_priority_lane(priority, [row.ticker for row in ranking], limit=limit)
        log.warning(
            "ai investor candidate ranking path=legacy_rotation (factor cross-section unavailable) "
            "as_of=%s universe=%d selected=%s priority=%s scores=%s",
            as_of_at.isoformat(),
            len(tickers),
            selected,
            {item.ticker: item.reason for item in priority},
            {row.ticker: row.score for row in ranking},
        )
        return selected

    def _last_attempted(self, tickers: list[str], *, as_of_at: datetime) -> dict[str, datetime]:
        """마지막 분석 시각. 실패한 시도도 포함한다 — 한 종목의 장애가 순환·재분석을 막지 않게."""
        last_analyzed = self._candidate_last_analyzed(tickers, as_of_at=as_of_at)
        from investment_agent.reporting.readers.runtime import read_local_rows
        for row in read_local_rows('security_decisions', canonical_db=Database(sb)):
            ticker=normalize_ticker(row.get('ticker'))
            if ticker in tickers and row.get('status')=='failed' and row.get('as_of_at'):
                attempted=parse_datetime(row['as_of_at'])
                if attempted <= as_of_at and (ticker not in last_analyzed or attempted > last_analyzed[ticker]):
                    last_analyzed[ticker]=attempted
        return last_analyzed

    def event_reanalysis_priorities(
        self,
        *,
        as_of_at: datetime,
        global_event_hours: int = 48,
    ) -> tuple[PriorityCandidate, ...]:
        """정기 순환을 기다리지 않고 지금 다시 볼 종목.

        보유 종목의 새 공시·고영향 사건(`priority_candidates`)과, 검증을 통과한 글로벌 사건에 민감한
        보유 종목(`global_event_priorities`)을 합친다. 공시 조회는 보유 종목으로 좁힌다 — 이 경로는
        몇 분마다 돌기 때문에 500종목 재무를 매번 읽을 이유가 없다.
        """
        as_of_at = validate_live_candidate_as_of(as_of_at)
        tickers = self.current_tracked_tickers()
        if not tickers:
            return ()
        held = [ticker for ticker in self._candidate_held_tickers() if ticker in set(tickers)]
        last_analyzed = self._last_attempted(tickers, as_of_at=as_of_at)
        latest_filed: dict[str, str] = {}
        for row in (self._candidate_fundamental_rows(held, as_of_at) if held else []):
            ticker = normalize_ticker(row.get("ticker"))
            filed = str(row.get("filed_at") or "")
            if ticker and filed > latest_filed.get(ticker, ""):
                latest_filed[ticker] = filed
        local = priority_candidates(
            tickers=tickers, held_tickers=held, last_analyzed_at=last_analyzed,
            latest_filed_at=latest_filed, event_features=self._candidate_event_features(as_of_at),
            as_of_at=as_of_at,
        )
        global_events = self._recent_global_events(as_of_at, hours=global_event_hours) if held else []
        themes = {theme for event in global_events for theme in (event.get("metadata") or {}).get("themes") or ()}
        proxies = sorted({THEME_BY_NAME[name].proxy for name in themes if name in THEME_BY_NAME})
        sensitivities: dict[str, dict[str, float]] = {}
        proxy_rows: dict[str, list[dict]] = {}
        if proxies:
            rows = {symbol: self.market_prices(symbol, as_of_at, limit=260) for symbol in (*held, *proxies)}
            for proxy in proxies:
                proxy_rows[proxy] = rows[proxy]
                try:
                    sensitivities[proxy] = estimate_betas(rows, symbols=held, benchmark_symbol=proxy)
                except ContractError as exc:
                    log.warning("global event sensitivity unavailable proxy=%s: %s", proxy, exc)
        global_priority = global_event_priorities(
            global_events, held_tickers=held, last_analyzed_at=last_analyzed,
            sensitivities=sensitivities, proxy_rows=proxy_rows, as_of_at=as_of_at,
        )
        merged: dict[str, PriorityCandidate] = {}
        for candidate in (*local, *global_priority):
            current = merged.get(candidate.ticker)
            if current is None or (candidate.tier, -candidate.importance) < (current.tier, -current.importance):
                merged[candidate.ticker] = candidate
        return tuple(sorted(merged.values(), key=lambda item: (item.tier, -item.importance, item.ticker)))

    def _recent_global_events(self, as_of_at: datetime, *, hours: int) -> list[dict[str, Any]]:
        try:
            rows = research_adapter.open_research_store(read_only=True).records(
                "events",
                start_as_of=None,
                end_as_of=None,
            )
        except Exception as exc:  # noqa: BLE001 - 사건 저장소 부재가 재분석 판단을 멈추게 두지 않는다
            log.warning("global events unavailable: %s", type(exc).__name__)
            return []
        floor = as_of_at - timedelta(hours=hours)
        return [
            row for row in rows
            if not row.get("ticker") and row.get("available_at")
            and floor <= parse_datetime(str(row["available_at"])) <= as_of_at
        ]

    def _candidate_factor_scores(
        self, tickers: Sequence[str], as_of_at: datetime,
    ) -> tuple[str, dict[str, Any]] | None:
        return self.factor_cross_section(as_of_at, universe_size=len(tickers))

    def factor_cross_section(
        self, as_of_at: datetime, *, universe_size: int | None = None,
    ) -> tuple[str, dict[str, Any]] | None:
        """최근 온전한 live feature 횡단면의 factor 점수. 없거나 오래됐으면 None.

        후보 선정과 System 목표가 같은 횡단면을 읽는다 — 둘이 다른 날의 점수를 보면 분석한 종목과
        담는 종목이 어긋난다.
        """
        tickers_count = universe_size if universe_size is not None else len(self.current_tracked_tickers())
        try:
            rows = research_adapter.open_research_store(read_only=True).records(
                "rl_feature_snapshots",
                start_as_of=(as_of_at - timedelta(days=FACTOR_SNAPSHOT_MAX_AGE_DAYS)).isoformat(),
                end_as_of=as_of_at.isoformat(),
            )
        except Exception as exc:  # noqa: BLE001 - feature 저장소 부재가 정기 분석을 멈추게 두지 않는다
            log.warning("factor snapshots unavailable for candidate selection: %s", type(exc).__name__)
            return None
        # 과거 재현 행은 판단 시각이 과거라 이 창에 거의 없지만, 섞이지 않게 live 행만 쓴다.
        live_rows = [row for row in rows if (row.get("provenance") or {}).get("source_kind") != "historical_replay"]
        section = latest_cross_section(
            live_rows, feature_version=FEATURE_VERSION, min_coverage=max(1, tickers_count // 2),
        )
        if section is None:
            return None
        snapshot_as_of, features = section
        return snapshot_as_of, score_cross_section(features, groups=self.sp500_sector_map(list(features)))

    def _candidate_held_tickers(self) -> list[str]:
        """System Portfolio가 지금 보유한 종목. 실계좌 보유는 분석 대상 선정에 들어오지 않는다."""
        from investment_agent.trading.system.store import SystemPortfolioStore
        try:
            return SystemPortfolioStore().held_tickers()
        except Exception as exc:  # noqa: BLE001 - 원장이 없어도 정기 분석은 계속한다
            log.warning("system holdings unavailable for candidate priority: %s", type(exc).__name__)
            return []

    def thesis_views(self, tickers: Sequence[str], *, as_of_at: datetime, valid_days: int) -> dict[str, Any]:
        """종목별 최신 TradingAgents 논지(채택된 ML 보정 반영). 판단 시점 이전에 기록된 것만 읽는다."""
        from investment_agent.trading.decision.alpha import ThesisView

        wanted = {normalize_ticker(ticker) for ticker in tickers}
        repository = self._trading_repository()
        rows = repository.signal_rows_recorded_between(start=as_of_at - timedelta(days=valid_days), end=as_of_at)
        if not rows:
            return {}
        artifacts = {
            str(row["batch_id"]): row.get("model_artifact_id")
            for row in repository.signal_batches(as_of_at=as_of_at, lookback_days=min(365, valid_days + 1))
        }
        tickers_by_id = select_tickers_by_security_id([int(row["security_id"]) for row in rows])
        views: dict[str, Any] = {}
        for row in rows:
            ticker = normalize_ticker(tickers_by_id.get(int(row["security_id"])))
            if ticker not in wanted:
                continue
            view = ThesisView.from_proposal({**dict(row["proposal"]), "ticker": ticker},
                                            model_artifact_id=artifacts.get(str(row["batch_id"])))
            if view is not None and view.as_of_at <= as_of_at and (ticker not in views or view.as_of_at >= views[ticker].as_of_at):
                views[ticker] = view
        return views

    def _candidate_event_features(self, as_of_at: datetime) -> list[dict[str, Any]]:
        """최근 7일 사건 요약. 로컬 research 저장소가 없으면 빈 목록이다."""
        try:
            return research_adapter.open_research_store(read_only=True).records(
                "event_feature_snapshots",
                start_as_of=(as_of_at - timedelta(days=7)).isoformat(),
                end_as_of=as_of_at.isoformat(),
            )
        except Exception as exc:  # noqa: BLE001 - 사건 저장소 부재가 정기 분석을 멈추게 두지 않는다
            log.warning("event features unavailable for candidate priority: %s", type(exc).__name__)
            return []

    def sp500_sector_map(self, tickers: list[str] | tuple[str, ...]) -> dict[str, str]:
        symbols = sorted({str(ticker).upper() for ticker in tickers})
        if not symbols:
            return {}
        mirror = self._mirror()
        if mirror is not None:
            return mirror.sector_map(symbols)
        rows = select_security_profiles(symbols, tracked_only=True)
        return {
            str(row["ticker"]).upper(): str(row["sic_division"])
            for row in rows if row.get("sic_division")
        }

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
            lambda: latest_technical_signals_as_of(as_of_at),
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
        signals = _guru_candidate_signals(current, previous, holdings)
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


    def save_policy(self, row: dict) -> None:
        self._trading_repository().record_policy(row)

    def case_exists(self, case_key: str) -> bool:
        return self._trading_repository().decision_exists(case_key)

    def save_case(self, row: dict) -> None:
        payload = dict(row)
        ticker = payload.pop("ticker", None)
        evidence_bundle = payload.pop("evidence_bundle", None)
        payload.pop("role_analyses", None)
        evidence_meta = dict(evidence_bundle or {})
        final_decision = payload.get("final_decision")
        if isinstance(final_decision, dict):
            final_decision = dict(final_decision)
            if isinstance(evidence_meta.get("_digest"), dict):
                final_decision["evidence_digest"] = evidence_meta["_digest"]
            if evidence_meta.get("_artifact_error"):
                final_decision["evidence_artifact_error"] = str(
                    evidence_meta["_artifact_error"]
                )[:500]
            payload["final_decision"] = final_decision
        payload["security_id"] = _security_id(str(ticker))
        repository = self._trading_repository()
        repository.record_decision(payload)
        artifact = dict(evidence_meta.get("_artifact") or {})
        if artifact:
            repository.record_evidence([{
                "case_key": payload["case_key"],
                "evidence_kind": "bundle",
                "artifact_uri": artifact.get("uri") or artifact.get("artifact_uri"),
                "sha256": artifact["sha256"],
                "byte_size": int(artifact["byte_size"]),
                "schema_version": str(artifact["schema_version"]),
            }])

    def save_decision_run(self, row: dict) -> None:
        self._trading_repository().record_run(row)

    def finish_decision_run(
        self,
        run_id: str,
        *,
        status: str,
        failure_reason: str | None = None,
    ) -> None:
        self._trading_repository().finish_run(
            run_id,
            status=status,
            failure_reason=failure_reason,
        )

    def save_portfolio_snapshot(self, snapshot: AccountSnapshot) -> str:
        """execution owner의 불변 계좌 원장에 snapshot을 기록한다.

        ``trading``은 계좌 상태를 소유하지 않지만, 판단이 사용한 snapshot을
        가리킬 수 있어야 한다. 따라서 이 writer는 execution repository의
        공개 계약만 호출하고, trading 테이블에는 snapshot 자체를 복제하지 않는다.
        실제 계좌번호는 execution 원장에도 평문으로 남기지 않고 hash만 기록한다.
        """
        from investment_agent.execution.db import ExecutionRepository

        execution = ExecutionRepository()
        account_ref = hashlib.sha256(
            f"{snapshot.broker}|{snapshot.account_id}".encode("utf-8")
        ).hexdigest()
        snapshot_id = execution.save_account_snapshot({
            "execution_mode": "live",
            "broker_account_hash": account_ref,
            "equity": snapshot.total_value,
            "cash": snapshot.cash_value,
            "buying_power": snapshot.cash_value,
            "captured_at": snapshot.captured_at,
            "raw_snapshot": {
                "source": "portfolio_construction",
                "broker": snapshot.broker,
                "base_currency": snapshot.base_currency,
                "open_order_count": len(snapshot.open_order_ids),
            },
        })
        if snapshot.positions:
            security_ids = _security_ids([position.ticker for position in snapshot.positions])
            execution.save_position_snapshots([
                {
                    "account_snapshot_id": snapshot_id,
                    "ticker": normalize_ticker(position.ticker),
                    "security_id": security_ids[normalize_ticker(position.ticker)],
                    "quantity": position.quantity,
                    "market_price": position.market_price,
                    "market_value": position.market_value,
                    "weight": position.market_value / snapshot.total_value,
                }
                for position in snapshot.positions
            ])
        return str(snapshot_id)

    def save_signal_batch(
        self,
        *,
        run_id: str,
        batch: SignalBatch,
        records: tuple[SignalRecord, ...],
    ) -> None:
        """배치 행을 먼저 저장한 뒤 종목 의견을 immutable ID로 저장한다."""
        if any(record.batch_id != batch.batch_id for record in records):
            raise ValueError("signal records do not belong to the supplied batch")
        batch_row = {
            "batch_id": batch.batch_id,
            "run_id": run_id,
            "as_of_at": batch.as_of_at,
            "completed_at": batch.completed_at,
            "requested_symbols": list(batch.requested_symbols),
            "successful_symbols": list(batch.successful_symbols),
            "failed_symbols": list(batch.failed_symbols),
            "is_complete": batch.is_complete,
            "model_artifact_id": batch.model_artifact_id,
        }
        security_ids = _security_ids([record.proposal.ticker for record in records]) if records else {}
        signal_rows = [{
            "signal_id": record.signal_id,
            "batch_id": record.batch_id,
            "case_key": record.case_key,
            "security_id": security_ids[normalize_ticker(record.proposal.ticker)],
            "proposal": record.proposal.to_dict(),
            "recorded_at": record.recorded_at,
            "expires_at": record.expires_at,
        } for record in records]
        self._trading_repository().record_signal_batch(batch=batch_row, signals=signal_rows)

    def latest_signal_batch_id(self, *, as_of_at: datetime) -> str | None:
        return self._trading_repository().latest_signal_batch_id(as_of_at=as_of_at)

    def signal_batch_id_for_as_of(self, as_of_at: str | datetime) -> str:
        """Shadow 입력 시각과 정확히 같은 단일 batch만 반환해 완료시각 경합을 없앤다."""
        point = parse_datetime(as_of_at)
        return self._trading_repository().signal_batch_id_for_as_of(point)

    def save_portfolio_proposal(self, row: dict) -> None:
        self._trading_repository().record_proposal(dict(row))

    def save_risk_decision(self, row: dict) -> None:
        self._trading_repository().record_risk_decision(dict(row))

    def save_portfolio_decision(self, row: dict) -> None:
        self._trading_repository().adopt_portfolio(row)

    def save_model_artifact(self, row: dict) -> None:
        self._trading_repository().record_model_version(row)

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
        rows = research_adapter.open_research_store(read_only=True).records(
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
    def rl_feature_snapshot_rows(
        self,
        symbols: tuple[str, ...],
        *,
        start_as_of: str,
        end_as_of: str,
        feature_version: str,
        as_of_values: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """미래 라벨 컬럼을 전혀 조회하지 않는 point-in-time feature 경계다."""
        return research_adapter.open_research_store(read_only=True).rl_feature_snapshot_rows(
            symbols,
            start_as_of=start_as_of,
            end_as_of=end_as_of,
            feature_version=feature_version,
            as_of_values=as_of_values,
        )

    def rl_training_label_rows(
        self,
        symbols: tuple[str, ...],
        *,
        start_as_of: str,
        end_as_of: str,
        feature_version: str,
        label_cutoff_at: str,
        as_of_values: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """학습 cutoff 전에 실제 생성된 미래 label만 별도로 반환한다."""
        return research_adapter.open_research_store(read_only=True).rl_training_label_rows(
            symbols,
            start_as_of=start_as_of,
            end_as_of=end_as_of,
            feature_version=feature_version,
            label_cutoff_at=label_cutoff_at,
            as_of_values=as_of_values,
        )

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

    def save_promotion(self, row: dict) -> None:
        self._research_store().save_promotion(self._trading_repository(), row)

    def model_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        return self._trading_repository().model_version(artifact_id)

    def model_stage(self, artifact_id: str) -> str | None:
        return self._trading_repository().current_model_stage(artifact_id)

    def model_evaluation_rows(self, artifact_id: str) -> list[dict[str, Any]]:
        return self._research_store(read_only=True).model_evaluation_rows(artifact_id)

    def model_evaluation_summary(self, artifact_id: str) -> EvaluationSummary:
        """평가 원장 전체를 보수적인 승격 요약으로 집계한다."""
        if self.model_artifact(artifact_id) is None:
            raise LookupError(f"model artifact not found: {artifact_id}")
        return self._research_store(read_only=True).model_evaluation_summary(artifact_id)

    def approve_model_promotion(
        self,
        decision: PromotionDecision,
        *,
        confirmation: str,
    ) -> dict[str, Any]:
        """평가 재검증 뒤 현재 단계를 잠그고 승인 audit만 기록한다."""
        return self._research_store().approve_model_promotion(
            self._trading_repository(),
            decision,
            confirmation=confirmation,
            model_artifact=self.model_artifact(decision.artifact_id),
            model_stage=self.model_stage(decision.artifact_id),
        )

    def risk_decision(self, risk_decision_id: str) -> dict | None:
        from investment_agent.execution.db import ExecutionRepository

        return ExecutionRepository().risk_decision(risk_decision_id)

    def portfolio_proposal(self, proposal_id: str) -> dict | None:
        from investment_agent.execution.db import ExecutionRepository
        return ExecutionRepository().portfolio_proposal(proposal_id)

    def has_approved_promotion(self, artifact_id: str, to_stage: str) -> bool:
        if to_stage not in {"paper", "live"}:
            return False
        stage = self.model_stage(artifact_id)
        if stage is None:
            return False
        if {"shadow": 0, "backtest": 1, "out_of_sample": 2, "walk_forward": 3, "paper": 4, "live": 5}.get(stage, -1) < {
            "paper": 4,
            "live": 5,
        }[to_stage]:
            return False
        rows = [
            row for row in self._trading_repository().model_promotions(artifact_id)
            if row.get("status") == "approved"
        ]
        approved_transitions = {
            (str(row.get("from_stage")), str(row.get("to_stage")))
            for row in rows
            if row.get("confirmation_text")
            == (
                f"PROMOTE {artifact_id} {row.get('from_stage')}"
                f"->{row.get('to_stage')}"
            )
        }
        required = {
            ("shadow", "backtest"),
            ("backtest", "out_of_sample"),
            ("out_of_sample", "walk_forward"),
            ("walk_forward", "paper"),
        }
        if to_stage == "live":
            required.add(("paper", "live"))
        return required.issubset(approved_transitions)

    def decision_cases_for_experiences(self) -> list[dict]:
        """체결 여부로 거르지 않은 원본 판단이다."""
        rows = self._trading_repository().decision_cases()
        tickers = select_tickers_by_security_id([int(row["security_id"]) for row in rows])
        return [{**row, "ticker": tickers[int(row["security_id"])]}
                for row in rows if int(row["security_id"]) in tickers]

    def decision_experience_rows(self, *, as_of_at: datetime | None = None) -> list[dict]:
        """라벨 관측 시각으로 제한한 가상 판단 경험을 읽는다."""
        try:
            rows = research_adapter.open_research_store(read_only=True).records("decision_experiences")
        except FileNotFoundError:
            return []
        return [row for row in rows if as_of_at is None
                or parse_datetime(row["available_at"]) <= as_of_at]

    def save_decision_experiences(self, rows: Sequence[dict]) -> None:
        self._research_store().save_decision_experiences(rows)

    def cases_for_evaluation(self, limit: int = 200) -> list[dict]:
        rows = self._trading_repository().evaluation_candidates(limit=limit)
        tickers = select_tickers_by_security_id([int(row["security_id"]) for row in rows])
        return [
            {**row, "ticker": tickers[int(row["security_id"])]}
            for row in rows if int(row["security_id"]) in tickers
        ]

    def existing_evaluation_horizons(self, case_key: str) -> set[int]:
        return self._trading_repository().evaluation_horizons(case_key)

    def price_path(self, ticker: str, start_date: date, limit: int = 80) -> list[dict]:
        """사후 평가용 경로. PIT 조회가 아니다."""
        return market_db.price_path_from(ticker, start_date, limit=limit)
    def save_evaluation(self, row: dict) -> None:
        self._trading_repository().record_evaluation(row)

    def previous_decision(self, ticker: str, *, as_of_at: datetime) -> dict | None:
        """같은 종목의 직전 판단. 다음 판단이 무엇이 바뀌었는지 설명하게 하는 기준이다."""
        return self._trading_repository().previous_decision_row(security_id=_security_id(ticker), as_of_at=as_of_at)

    def evaluated_memories(
        self,
        ticker: str,
        limit: int = 5,
        as_of_at: datetime | None = None,
    ) -> list[dict]:
        cases = self._trading_repository().evaluated_memory_rows(
            security_id=_security_id(ticker),
            limit=limit,
            as_of_at=as_of_at,
        )
        return [
            {
                **row,
                "ticker": normalize_ticker(ticker),
                "evaluations": row["evaluations"],
            }
            for row in cases
        ][:limit]


# ── 운영 scorecard용 최신 1행 읽기 ─────────────────────────────────────────
# ops가 이 스키마를 직접 조회하면 테이블·컬럼 이름이 저장소 경계 밖으로 새어 나가고,
# 오타가 import 에러가 아니라 런타임 PGRST 404로만 드러난다. 계약은 여기서 소유한다.


def latest_decision_run() -> dict | None:
    return SupabaseRepository._trading_repository().latest_run()


def latest_model_artifact() -> dict | None:
    return SupabaseRepository._trading_repository().latest_model_version()


def latest_backtest_evaluation() -> dict | None:
    rows = [
        row for row in research_adapter.open_research_store(read_only=True).records("portfolio_evaluations")
        if str(row.get("evaluation_kind") or "") == "backtest"
    ]
    rows.sort(key=lambda row: str(row.get("evaluated_at") or ""), reverse=True)
    return rows[0] if rows else None


def latest_risk_decision() -> dict | None:
    return SupabaseRepository._trading_repository().latest_risk_decision()
