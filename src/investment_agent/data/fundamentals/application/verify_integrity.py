"""적재 결과의 불변조건을 점검해 조용히 썩는 실패를 드러낸다.

순수 판정만 여기 둔다. 조회는 repository가 하고, 이 함수는 숫자를 받아 등급을
매긴다 — 그래야 네트워크 없이 테스트할 수 있다.
"""
from __future__ import annotations

from datetime import date

# 남는 불일치의 구조적 하한. 파생 총부채는 검사에서 제외하고 직접 보고된
# 총부채만 대조했을 때 실측 2.4%다(2026-08-29, 503종목). 나머지는 ARES·BX처럼
# StockholdersEquity(모회사)만 태깅하고 MinorityInterest를 따로 안 내는 회사라
# 저장된 값으로는 복원할 수 없다.
BALANCE_MISMATCH_WARN = 0.06
BALANCE_MISMATCH_ERROR = 0.12

ERROR = "error"
WARNING = "warning"
OK = "ok"


def _check(name: str, severity: str, message: str, **detail) -> dict:
    return {"name": name, "severity": severity, "message": message, "detail": detail}


def evaluate(
    facts: dict,
    today: date,
    *,
    stale_filing_days: int,
    stale_mv_days: int,
) -> list[dict]:
    """조회 결과를 점검 항목 목록으로 바꾼다."""
    checks: list[dict] = []

    # 1. 스키마와 코드가 어긋나면 적재가 통째로 PGRST204로 실패하거나, 아무도
    #    채우지 않는 컬럼이 남는다. 둘 다 조용하다.
    missing = sorted(facts.get("columns_missing_in_db") or [])
    extra = sorted(facts.get("columns_missing_in_code") or [])
    if missing:
        checks.append(_check(
            "schema_drift", ERROR,
            "코드가 쓰는 컬럼이 DB에 없다 — 적재가 PGRST204로 실패한다",
            missing=missing))
    elif extra:
        checks.append(_check(
            "schema_drift", WARNING,
            "DB에만 있는 컬럼이 남아 있다 — 아무도 채우지 않는다",
            extra=extra))
    else:
        checks.append(_check("schema_drift", OK, "스키마와 코드 컬럼이 일치한다"))

    # 2. 매핑 정책과 불일치하는 행이 섞이면 deterministic rerun과
    #    결과 비교 가능성이 깨진다.
    stale_mapping_rows = int(facts.get("stale_mapping_rows") or 0)
    mapping_version = str(facts.get("current_mapping_version") or "unknown")
    checks.append(_check(
        "mapping_policy_current",
        ERROR if stale_mapping_rows else OK,
        (
            f"현재 매핑 정책과 불일치하는 행이 {stale_mapping_rows}개 있다"
            if stale_mapping_rows
            else f"모든 행이 현재 매핑 정책({mapping_version})이다"
        ),
        current_mapping_version=mapping_version,
        stale_rows=stale_mapping_rows,
    ))

    fiscal_sequence = facts.get("fiscal_sequence")
    if not isinstance(fiscal_sequence, dict):
        checks.append(_check(
            "fiscal_sequence",
            ERROR,
            "회계기간 순서 통계를 읽지 못했다",
        ))
    else:
        non_monotonic = int(fiscal_sequence.get("non_monotonic_rows") or 0)
        duplicate_periods = int(
            fiscal_sequence.get("duplicate_period_end_rows") or 0
        )
        fiscal_errors = non_monotonic + duplicate_periods
        checks.append(_check(
            "fiscal_sequence",
            ERROR if fiscal_errors else OK,
            (
                f"회계기간 순서·기간말 계약 위반 {fiscal_errors}행"
                if fiscal_errors
                else "회계기간 키가 기간말 순서와 일치한다"
            ),
            non_monotonic_rows=non_monotonic,
            duplicate_period_end_rows=duplicate_periods,
        ))

    unknown_equity_scopes = int(facts.get("unknown_equity_scope_rows") or 0)
    checks.append(_check(
        "equity_scope",
        ERROR if unknown_equity_scopes else OK,
        (
            f"자본 포함 범위를 식별하지 못한 행이 {unknown_equity_scopes}개다"
            if unknown_equity_scopes
            else "common_equity의 포함 범위가 모두 식별됐다"
        ),
        unknown_rows=unknown_equity_scopes,
    ))

    segment = facts.get("segment_integrity")
    if not isinstance(segment, dict):
        checks.append(_check(
            "segment_integrity_available",
            ERROR,
            "세그먼트 무결성 통계를 읽지 못했다",
        ))
    else:
        checks.append(_check(
            "segment_integrity_available",
            OK,
            "세그먼트 무결성 통계를 읽었다",
            metric_rows=int(segment.get("metric_rows") or 0),
            filing_rows=int(segment.get("filing_rows") or 0),
        ))
        segment_state = {
            "stale_mapping_filing_rows": int(
                segment.get("stale_mapping_filing_rows") or 0
            )
        }
        state_errors = sum(segment_state.values())
        checks.append(_check(
            "segment_filing_state",
            ERROR if state_errors else OK,
            (
                f"세그먼트 구버전 공시 상태 {state_errors}개"
                if state_errors
                else "세그먼트 공시 상태와 매핑 버전이 정상이다"
            ),
            **segment_state,
        ))

        missing_segment_states = int(
            segment.get("tracked_without_filing_rows") or 0
        )
        checks.append(_check(
            "segment_tracked_coverage",
            ERROR if missing_segment_states else OK,
            (
                f"세그먼트 처리 상태가 없는 추적 ticker {missing_segment_states}개"
                if missing_segment_states
                else "모든 추적 ticker에 세그먼트 처리 상태가 있다"
            ),
            missing_tickers=missing_segment_states,
        ))

        contract_keys = (
            "valueless_metric_rows",
            "unknown_classification_rows",
            "orphan_metric_rows",
            "nonparsed_metric_state_rows",
            "report_period_mismatch_rows",
            "future_metric_rows",
            "invalid_period_kind_rows",
            "invalid_derived_rows",
            "invalid_coverage_rows",
            "invalid_metric_metadata_rows",
            "invalid_filing_date_rows",
        )
        contract_errors = {
            key: int(segment.get(key) or 0) for key in contract_keys
        }
        error_count = sum(contract_errors.values())
        checks.append(_check(
            "segment_data_contract",
            ERROR if error_count else OK,
            (
                f"세그먼트 데이터 계약 위반 {error_count}건"
                if error_count
                else "세그먼트 값·기간·품질·계보 계약이 정상이다"
            ),
            **contract_errors,
        ))

    # 4. 추적 CIK가 있는데 wide 행이 전혀 없는 ticker는 성공 로그만으로 찾기 어렵다.
    missing_tickers = sorted(facts.get("missing_financial_tickers") or [])
    checks.append(_check(
        "tracked_coverage",
        ERROR if missing_tickers else OK,
        (
            f"기업 재무가 전혀 없는 추적 ticker {len(missing_tickers)}개"
            if missing_tickers
            else "CIK가 있는 모든 추적 ticker에 기업 재무가 있다"
        ),
        missing=missing_tickers,
    ))

    # 5. 수집이 멈췄는가. 실행 성공과 별개로 새 공시가 안 들어오는 상태가 있다.
    last_filed = facts.get("last_filed_at")
    if last_filed is None:
        checks.append(_check("collection_stalled", ERROR, "financial_versions가 비어 있다"))
    else:
        age = (today - last_filed).days
        severity = WARNING if age > stale_filing_days else OK
        checks.append(_check(
            "collection_stalled", severity,
            f"최근 공시가 {age}일 전이다",
            last_filed_at=last_filed.isoformat(), threshold_days=stale_filing_days))

    # 6. 원장 최신 기간이 멈추면 downstream 계산도 새 공시를 반영하지 못한다.
    latest_period = facts.get("latest_financial_period_end")
    if latest_period is None:
        checks.append(_check("financial_versions_stale", ERROR, "financial_versions가 비어 있다"))
    else:
        age = (today - latest_period).days
        severity = ERROR if age > stale_mv_days else OK
        checks.append(_check(
            "financial_versions_stale", severity,
            f"financial_versions 최신 분기가 {age}일 전이다",
            latest_period_end=latest_period.isoformat(), threshold_days=stale_mv_days))

    # 7. 직접 보고된 값에서 회계항등식(A = L + CE + MI + mezzanine)이 깨진 행.
    #
    # 0을 기대하면 안 된다. StockholdersEquity(모회사)만 태깅하고 비지배지분을
    # 따로 안 내는 회사(ARES·BX)는 저장된 값으로 복원할 수 없다 — 실측 2.4%가
    # 그 구조적 하한이다.
    #
    # 임계치는 "지금보다 눈에 띄게 나빠졌나"로 잡는다. 급등하면 매핑이 깨진 것이다.
    # 분모는 '검사 가능한 행'이다. 부채나 자본이 없는 행은 애초에 검사 대상이
    # 아니라, 전체 행으로 나누면 비율이 실제보다 작게 나온다.
    total = int(facts.get("balance_checkable_rows") or facts.get("row_count") or 0)
    broken = int(facts.get("balance_mismatch_rows") or 0)
    ratio = (broken / total) if total else 0.0
    checks.append(_check(
        "balance_identity",
        ERROR if ratio > BALANCE_MISMATCH_ERROR else
        WARNING if ratio > BALANCE_MISMATCH_WARN else OK,
        f"회계항등식 불일치 {broken}행 ({ratio:.1%})",
        rows=broken, total=total, baseline="비지배지분 미태깅으로 3% 내외가 정상"))

    # 8. 핵심 컬럼 충전율. 매핑이 깨지면 여기서 먼저 드러난다 — 실제로 EPS가
    #    5%까지 떨어진 채 몇 달을 갔다.
    for column, floor in (facts.get("fill_floors") or {}).items():
        actual = float((facts.get("fill_rates") or {}).get(column) or 0.0)
        checks.append(_check(
            f"fill_{column}",
            ERROR if actual < floor * 0.5 else WARNING if actual < floor else OK,
            f"{column} 충전율 {actual:.1f}% (기대 {floor:.0f}% 이상)",
            column=column, actual=actual, floor=floor))

    # 9. 발표 예정일에 세션이 안 붙으면 핀포인트 수집이 넓은 창으로 돌아간다.
    scheduled = int(facts.get("schedule_rows") or 0)
    unknown = int(facts.get("schedule_unknown_session") or 0)
    if scheduled:
        share = unknown / scheduled
        checks.append(_check(
            "session_classification",
            WARNING if share > 0.3 else OK,
            f"세션 미분류 {unknown}/{scheduled} ({share:.0%})",
            unknown=unknown, total=scheduled))

    return checks


def verify_integrity(
    *,
    repository,
    today: date,
    stale_filing_days: int,
    stale_mv_days: int,
) -> dict:
    """조회한 데이터 사실을 판정한다. 운영 오류는 DB에 기록하지 않는다."""
    facts = repository.collect_integrity_facts()
    checks = evaluate(
        facts, today,
        stale_filing_days=stale_filing_days,
        stale_mv_days=stale_mv_days,
    )
    return {"checks": checks, "facts": facts}
