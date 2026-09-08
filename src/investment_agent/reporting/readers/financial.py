"""v1 reporting 뷰 전용 조회. 연결은 호출자가 주입하며 쓰기·RPC는 제공하지 않는다.

현재 상태 뷰는 PIT 데이터셋이 아니다. 기간 필터를 걸어도 과거 버전 선택을 복원하지
않는다. 가격과 판단 등 이력은 범위를 요구해 무제한 스캔을 막는다.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType
from typing import Any

from investment_agent.platform.db.postgres import Database
from investment_agent.reporting.models import DataResult, public_exception_message
from investment_agent.reporting.readers.runtime import LOCAL_VIEWS, read_local_rows

SCHEMA = "reporting"


@dataclass(frozen=True)
class ViewSpec:
    """공개 컬럼·페이지 정렬·조회 범위의 선언. 숫자의 계산은 원천 뷰가 소유한다."""

    columns: str
    order_by: str
    time_column: str | None = None
    scope_column: str | None = None


VIEWS: Mapping[str, ViewSpec] = MappingProxyType({
    "execution_control_state": ViewSpec("scope,kill_switch_on,durable_lockdown_on,live_enabled,live_autonomy_enabled,version,reason,updated_at", "updated_at"),
    "execution_intents": ViewSpec("intent_id,risk_decision_id,proposal_id,execution_mode,target_weights,not_before,expires_at,status,claimed_at,completed_at,failure_reason,created_at", "created_at"),
    "execution_approvals": ViewSpec("approval_id,intent_id,proposal_id,risk_decision_id,execution_mode,status,decision,requested_at,expires_at,decided_at,consumed_at,updated_at", "requested_at"),
    "execution_orders": ViewSpec("client_order_id,attempt_id,intent_id,approval_id,broker_order_id,ticker,side,quantity,reference_price,notional,status,raw_broker_status,submitted_at,updated_at", "updated_at"),
    "execution_fills": ViewSpec("broker_fill_id,client_order_id,broker_order_id,ticker,side,quantity,price,commission,filled_at,created_at", "filled_at"),
    "current_model_stage": ViewSpec(
        "artifact_id,algorithm,feature_version,train_start,train_end,seed,artifact_uri,sha256,params,code_commit,created_at,stage,current_promotion_id,stage_changed_at", "artifact_id"),
    "institutional_filings": ViewSpec(
        "accession_no,manager_cik,period_end,form_type,report_type,filing_date,accepted_at,amendment_type,amendment_no,reported_value_usd,reported_line_count,confidential_omitted,source_url,content_sha256", "manager_cik,period_end", "period_end", "manager_cik"),
    "institutional_positions": ViewSpec(
        "accession_no,source_row_no,issuer_name,cusip,identifier_type,value_usd,quantity,quantity_type,position_kind,ticker", "accession_no,source_row_no", None, "accession_no"),
    "securities": ViewSpec(
        "ticker,company_name,company_name_ko,sic_industry_name,sic_division_name,"
        "exchange_code,security_type,is_active_listing,is_tracked,"
        "is_watchlisted,watchlist_sources,watch_from", "ticker"),
    "prices_daily": ViewSpec(
        "ticker,trade_date,open,high,low,close,volume,is_repaired",
        "ticker,trade_date", "trade_date", "ticker"),
    "company_financials_latest": ViewSpec(
        "cik,period_end,fiscal_year,fiscal_period,accession_no,filing_date,form_type,"
        "available_at,revenue,operating_income_loss,net_income,eps_diluted_gaap,mapping_version",
        "cik,period_end", "period_end", "cik"),
    "macro_latest": ViewSpec(
        "series_id,name_ko,domain,frequency,unit,ref_period,value,effective_at,collected_at",
        "series_id"),
    "macro_series": ViewSpec(
        "series_id,name_ko,description,country,category,frequency,base_unit,timezone,source,domain,series_kind",
        "series_id"),
    "macro_observations": ViewSpec(
        "series_id,obs_date,value,effective_at,collected_at",
        "series_id,obs_date", "obs_date", "series_id"),
    "macro_release_summary": ViewSpec(
        "event_key,series_id,series_name_ko,country,category,frequency,timezone,ref_period,scheduled_at,schedule_source,schedule_confidence,status,first_actual_at,first_actual_precision,measure_id,measure_code,measure_name_ko,unit,decimal_places,is_surprise_eligible,first_actual_value,latest_actual_value,latest_actual_effective_at,survey_value,nowcast_value,own_model_value,closing_survey_value,closing_nowcast_value,closing_own_model_value,market_surprise,nowcast_error,model_error,revision",
        "scheduled_at,series_id,ref_period", "scheduled_at", "series_id"),
    "macro_release_forecasts": ViewSpec(
        "series_id,ref_period,measure_id,forecast_kind,source,value,as_of,collected_at,previous_value,change_amount",
        "series_id,ref_period,measure_id,forecast_kind,as_of,collected_at", "collected_at", "series_id"),
    "macro_release_actuals": ViewSpec(
        "series_id,ref_period,measure_id,value,effective_at,collected_at,time_precision,source",
        "series_id,ref_period,effective_at,collected_at", "collected_at", "series_id"),
    # measure master는 이력이 아니다 — time_column이 없어 scope를 걸면 범위로 풀 길이
    # 없고, 전체를 읽는 것이 유일한 용법이다(화면도 read model도 그렇게 부른다).
    "macro_measures": ViewSpec(
        "measure_id,series_id,name_ko,unit,transform,is_primary,rollup_method",
        "series_id,measure_id"),
    "security_decisions": ViewSpec(
        "case_key,ticker,as_of_at,horizon_days,status,policy_key,policy_version,model_provider,"
        "model_name,source_kind,final_decision,failure_reason,evidence_uri,evidence_sha256,"
        "evidence_byte_size,evidence_schema_version,created_at", "case_key", "as_of_at", "ticker"),
    "portfolio_decisions": ViewSpec(
        "decision_id,run_id,as_of_at,stage,status,source_type,confidence,risk_approved,"
        "approved_weights,violations,created_at", "decision_id", "as_of_at", "run_id"),
    "notification_failures": ViewSpec(
        "producer,notification_key,kind,entity_key,status,attempt_count,channel,failure_reason,attempted_at",
        "producer,notification_key,attempted_at,channel,failure_reason", "attempted_at", "producer"),
    "earnings_schedule": ViewSpec(
        "ticker,target_fiscal_year,target_fiscal_period,target_period_end,expected_report_at,"
        "expected_report_date,expected_session,is_estimated,snapshot_date,previous_report_at",
        "ticker,target_fiscal_year,target_fiscal_period", "expected_report_date", "ticker"),
    "earnings_surprise": ViewSpec(
        "ticker,cik,fiscal_year,fiscal_period,period_end,filing_date,available_at,accession_no,"
        "revenue_actual,eps_actual,eps_estimate,revenue_estimate,estimate_snapshot_date,"
        "eps_analysts,eps_surprise_pct,revenue_surprise_pct,guidance_summary,"
        "operating_income_actual,net_income_actual,press_release_url",
        "ticker,accession_no", "filing_date", "ticker"),
    "job_health": ViewSpec(
        "job_key,runner,last_status,last_run_at,last_success_at,items_processed,items_failed,"
        "last_detail,seconds_since_success,is_overdue", "job_key"),
})


def _bound(value: date | datetime | str) -> str:
    """정렬 가능한 ISO 값만 허용한다. 시각에는 명시적인 시간대가 필요하다."""
    if isinstance(value, str):
        value = date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value)
    if isinstance(value, datetime) and value.utcoffset() is None:
        raise ValueError("timestamp bounds require a timezone")
    if not isinstance(value, date):
        raise ValueError("bounds must be ISO dates or timestamps")
    return value.isoformat()


class ReportingQueries:
    """화면과 알림에 같은 DataResult를 반환한다. 실패를 빈 결과로 숨기지 않는다."""

    def __init__(self, db: Database | None, *, is_offline: bool = False) -> None:
        self._db = db
        self._is_offline = is_offline

    @classmethod
    def from_client(cls, client: Any, *, is_offline: bool = False) -> ReportingQueries:
        """클라이언트로부터 Database 인스턴스를 내부에서 구성하여 반환한다."""
        db_inst = Database(client) if client is not None else None
        return cls(db_inst, is_offline=is_offline)

    def read(
        self,
        view: str,
        *,
        equals: Mapping[str, Any] | None = None,
        in_values: Mapping[str, Sequence[Any]] | None = None,
        start: date | datetime | str | None = None,
        end: date | datetime | str | None = None,
    ) -> DataResult:
        """허용된 뷰를 끝까지 읽는다. 이력은 종목/주체 또는 양쪽 기간 경계가 필수다.

        기간의 양끝은 포함한다. observed_at은 조회 시각을 원천의 갱신 시각으로
        오인하지 않도록 비워 둔다. 원천 시각은 각 행의 공개 컬럼에 보존된다.
        """
        if view not in VIEWS:
            raise ValueError(f"unknown reporting view: {view}")
        spec = VIEWS[view]
        filters = dict(equals or {})
        memberships = {key: tuple(values) for key, values in (in_values or {}).items()}
        if (set(filters) | set(memberships)) - set(spec.columns.split(",")):
            raise ValueError("unknown reporting filter column")
        if any(value is None or not isinstance(value, (str, int, float, bool))
               or (isinstance(value, str) and not value.strip()) for value in filters.values()):
            raise ValueError("equality filters require nonempty scalar values")
        if any(not values for values in memberships.values()):
            raise ValueError("membership filters require nonempty values")
        if any(any(value is None or not isinstance(value, (str, int, float, bool))
                  or (isinstance(value, str) and not value.strip()) for value in values)
               for values in memberships.values()):
            raise ValueError("membership filters require nonempty scalars")
        if (start is None) != (end is None):
            raise ValueError("both start and end are required")
        lower = upper = None
        if start is not None and end is not None:
            if spec.time_column is None:
                raise ValueError("view has no time range")
            lower, upper = _bound(start), _bound(end)
            # 날짜와 시각을 섞지 않고 시간대 오프셋을 실제 시간으로 비교한다.
            parse = date.fromisoformat if len(lower) == 10 else datetime.fromisoformat
            if (len(lower) == 10) != (len(upper) == 10) or parse(lower) > parse(upper):
                raise ValueError("invalid reporting range")
        if spec.scope_column and spec.scope_column not in filters and spec.scope_column not in memberships and lower is None:
            raise ValueError("history requires a scope filter or bounded time range")
        source = f"{SCHEMA}.{view}"
        if self._is_offline:
            return DataResult.offline(source=source)
        if view in LOCAL_VIEWS:
            source = f"local.runtime.{view}"
            try:
                rows = read_local_rows(view, canonical_db=self._db)
                rows = [row for row in rows if all(row.get(key) == value for key, value in filters.items())
                        and all(row.get(key) in values for key, values in memberships.items())]
                if lower is not None:
                    parse = date.fromisoformat if len(lower) == 10 else datetime.fromisoformat
                    rows = [row for row in rows if row.get(spec.time_column) is not None and parse(lower) <= parse(str(row[spec.time_column])) <= parse(upper)]
                rows.sort(key=lambda row: tuple(str(row.get(key) or "") for key in spec.order_by.split(',')))
                projected = [{key: row.get(key) for key in spec.columns.split(',')} for row in rows]
                return DataResult.ok(rows=projected, source=source) if rows else DataResult.empty(source=source)
            except Exception as exc:
                return DataResult.error(source=source, message=public_exception_message("로컬 조회 실패", exc))
        if self._db is None:
            return DataResult.unconfigured(source=source)

        def factory() -> Any:
            query = self._db.table(SCHEMA, view).select(spec.columns)
            for column, value in filters.items():
                query = query.eq(column, value)
            for column, values in memberships.items():
                query = query.in_(column, list(values))
            if lower is not None:
                query = query.gte(spec.time_column, lower).lte(spec.time_column, upper)
            return query

        try:
            rows = self._db.select_paged(factory, order_by=spec.order_by)
            # 선언에 없는 필드가 응답에 섞이면 조용히 노출하거나 누락시키지 않는다.
            columns = set(spec.columns.split(","))
            if any(set(row) != columns for row in rows):
                raise ValueError("reporting response does not match its view contract")
            return DataResult.ok(rows=rows, source=source) if rows else DataResult.empty(source=source)
        except Exception as exc:
            return DataResult.error(source=source, message=public_exception_message("조회 실패", exc))
