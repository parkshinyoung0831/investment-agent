"""기업 전체 wide 재무 행의 불변조건을 검증하고 이상값을 격리한다."""
from __future__ import annotations

import math

from investment_agent.platform.logging import get_logger
from investment_agent.data.fundamentals.domain.policies import (
    AVERAGE_SHARES_SCALE_FACTOR,
    BALANCE_TOLERANCE,
    NON_NEGATIVE_FLOW_COLUMNS,
    PROFIT_OVER_REVENUE_TOLERANCE,
    REVENUE_TO_ASSETS_FLOOR,
    UNIT_SCALE_LOG_TOLERANCE,
)
from investment_agent.data.fundamentals.domain.services.balance_identity import non_liability_claims
from investment_agent.data.fundamentals.domain.taxonomy.financial_columns import CORE_COLUMNS

log = get_logger(__name__)

# (평균 주식수 컬럼, 그 주식수로 나눈 보고 EPS 컬럼)
_SHARES_EPS_PAIRS = (
    ("shares_average", "eps_basic_gaap"),
    ("shares_fully_diluted_average", "eps_diluted_gaap"),
)
_INCOME_COLUMNS = ("net_income_to_common_shareholders", "net_income")
# 정의상 매출을 넘을 수 없는 이익 컬럼. 순이익은 일부러 뺀다(정책 상수 주석 참고).
_PROFIT_BOUNDED_BY_REVENUE = ("gross_profit", "operating_income_loss")


def _is_unit_scale(ratio: float) -> bool:
    """배수가 1,000의 거듭제곱(천·백만 단위 오류)에 가까운가."""
    thirds = math.log10(ratio) / 3.0
    return abs(thirds - round(thirds)) <= UNIT_SCALE_LOG_TOLERANCE


def _scale_mismatch(row: dict, shares_column: str, eps_column: str) -> dict | None:
    """평균 주식수가 보고 EPS·순이익과 자릿수 단위로 어긋나면 그 근거를 돌려준다.

    귀속 순이익이 다른 개념에 매핑돼 있을 수 있어 순이익 후보를 둘 다 본다. 어느 후보와도
    맞지 않을 때만 주식수를 의심한다 — 한쪽만 틀린 행(UNH)을 주식수 오류로 오판하지 않는다.
    ``is_unit_scale``은 어긋난 배수(순이익 후보 중 하나라도)가 1,000의 거듭제곱인지다: 그렇다면 원천의 단위 오류라
    주식수가 틀린 것이고(MCD·COP·KO), 아니라면 분할 전후 값을 섞은 파생 산술(AMZN·NFLX의
    Q4)이라 어느 쪽이 틀렸는지 알 수 없다.
    """
    shares, eps = row.get(shares_column), row.get(eps_column)
    if shares is None or shares <= 0 or not eps:
        return None
    ratios = {}
    for column in _INCOME_COLUMNS:
        income = row.get(column)
        if income:
            ratios[column] = shares / abs(income / eps)
    if not ratios:
        return None
    factor = AVERAGE_SHARES_SCALE_FACTOR
    if any(1.0 / factor <= ratio <= factor for ratio in ratios.values()):
        return None
    return {"column": shares_column, "value": shares, eps_column: eps,
            "ratio_to_implied_shares": ratios,
            "is_unit_scale": any(_is_unit_scale(ratio) for ratio in ratios.values())}


def _profit_above_revenue(row: dict) -> dict | None:
    """매출을 넘는 이익 컬럼이 있으면 ``{컬럼: 값}``을, 없으면 `None`을 돌려준다."""
    revenue = row.get("revenue")
    if revenue is None or revenue <= 0:
        return None
    limit = revenue * (1.0 + PROFIT_OVER_REVENUE_TOLERANCE)
    over = {
        column: row[column]
        for column in _PROFIT_BOUNDED_BY_REVENUE
        if row.get(column) is not None and row[column] > limit
    }
    return over or None


def check_core_wide(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """잘못된 값은 비우고 ``(clean_rows, anomalies)``를 돌려준다."""
    anomalies: list[dict] = []
    clean_rows: list[dict] = []
    for original in rows:
        row = dict(original)
        cik = str(row.get("cik") or "")
        if len(cik) != 10 or not cik.isdigit() or "ticker" in row:
            raise ValueError("company financial rows must be keyed only by 10-digit CIK")
        if not any(row.get(column) is not None for column in CORE_COLUMNS):
            anomalies.append({
                "cik": cik,
                "fiscal_year": row["fiscal_year"],
                "fiscal_period": row["fiscal_period"],
                "reason": "no_financial_metrics",
                "detail": {},
                "filed_at": row.get("filed_at"),
            })
            continue
        for column in ("shares_average", "shares_fully_diluted_average"):
            value = row.get(column)
            if value is None or value > 0:
                continue
            anomalies.append({
                "cik": cik,
                "fiscal_year": row["fiscal_year"],
                "fiscal_period": row["fiscal_period"],
                "reason": "nonpositive_average_shares",
                "detail": {"column": column, "value": value},
                "filed_at": row.get("filed_at"),
            })
            row[column] = None

        for shares_column, eps_column in _SHARES_EPS_PAIRS:
            mismatch = _scale_mismatch(row, shares_column, eps_column)
            if mismatch is None:
                continue
            # 단위 오류면 주식수만, 아니면 어느 쪽이 틀렸는지 알 수 없으니 둘 다 비운다.
            # 틀린 숫자가 카드에 나가는 것보다 빈칸이 낫다.
            cleared = [shares_column] if mismatch["is_unit_scale"] else [shares_column, eps_column]
            anomalies.append({
                "cik": cik,
                "fiscal_year": row["fiscal_year"],
                "fiscal_period": row["fiscal_period"],
                "reason": (
                    "average_shares_scale_mismatch" if mismatch["is_unit_scale"]
                    else "per_share_basis_mismatch"
                ),
                "detail": {**mismatch, "cleared": cleared},
                "filed_at": row.get("filed_at"),
            })
            for column in cleared:
                row[column] = None

        # 정의상 음수가 될 수 없는 유량이 음수면 부호 규칙이 다른 태그가 잡힌 것이다.
        for column in sorted(NON_NEGATIVE_FLOW_COLUMNS):
            value = row.get(column)
            if value is None or value >= 0:
                continue
            anomalies.append({
                "cik": cik,
                "fiscal_year": row["fiscal_year"],
                "fiscal_period": row["fiscal_period"],
                "reason": "negative_nonnegative_flow",
                "detail": {"column": column, "value": value, "cleared": [column]},
                "filed_at": row.get("filed_at"),
            })
            row[column] = None

        # 매출이 총자산에 비해 턱없이 작으면 총매출이 아니라 하위 매출 항목이다(정책 상수 주석 참고).
        revenue, assets_value = row.get("revenue"), row.get("assets")
        if revenue is not None and assets_value and assets_value > 0 and (
            revenue / assets_value < REVENUE_TO_ASSETS_FLOOR
        ):
            anomalies.append({
                "cik": cik,
                "fiscal_year": row["fiscal_year"],
                "fiscal_period": row["fiscal_period"],
                "reason": "revenue_below_asset_floor",
                "detail": {"revenue": revenue, "assets": assets_value, "cleared": ["revenue"]},
                "filed_at": row.get("filed_at"),
            })
            row["revenue"] = None

        # 매출이 총이익·영업이익보다 작으면 매출이 총계가 아니다. 이익 쪽은 다른 태그에서 오므로
        # 맞는 값으로 보고 매출만 비운다 — 총매출의 0.4~30%인 하위 항목이 카드 마진·성장률에 나가는 것보다 빈칸이 낫다.
        exceeded = _profit_above_revenue(row)
        if exceeded is not None:
            anomalies.append({
                "cik": cik,
                "fiscal_year": row["fiscal_year"],
                "fiscal_period": row["fiscal_period"],
                "reason": "revenue_below_profit",
                "detail": {"revenue": row["revenue"], **exceeded, "cleared": ["revenue"]},
                "filed_at": row.get("filed_at"),
            })
            row["revenue"] = None

        # 회계항등식 A = L + 보통주 자본 + 우선주 + 비지배지분 + 메자닌. liabilities_and_equity
        # 컬럼은 두지 않는다 — assets와 실측 23,849/23,851행이 동일한 순수 중복이었다.
        # 메자닌은 반드시 더한다. 명시적으로 상환가능한 지분은 부채에도 영구자본에도 없는
        # 중간 계층이라, 빼면 DVA·UDR·SPGI 같은 종목이 구조적으로 어긋난다.
        assets = row.get("assets")
        liabilities = row.get("liabilities")
        equity_side = None
        if (
            liabilities is not None
            and row.get("common_equity") is not None
            and not row.get("is_liabilities_derived", False)
        ):
            claims = non_liability_claims(row)
            equity_side = liabilities + claims if claims is not None else None
        if assets and equity_side is not None and (
            abs(assets - equity_side) / abs(assets) > BALANCE_TOLERANCE
        ):
            anomalies.append({
                "cik": cik,
                "fiscal_year": row["fiscal_year"],
                "fiscal_period": row["fiscal_period"],
                "reason": "balance_mismatch",
                "detail": {
                    "assets": assets,
                    "liabilities_plus_equity": equity_side,
                },
                "filed_at": row.get("filed_at"),
            })
        clean_rows.append(row)

    clean_rows, collisions = _reject_period_collisions(clean_rows)
    anomalies.extend(collisions)
    _per_share_from_income(clean_rows)
    if anomalies:
        log.warning("fundamentals anomalies recorded: %d", len(anomalies))
    return clean_rows, anomalies


def _reject_period_collisions(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """같은 회계기간말에 서로 다른 분기 라벨이 붙은 행을 모두 뺀다.

    한 기간말은 한 분기다. 둘이면 회계력 판정이 어긋난 것이고, 어느 라벨이 맞는지는
    알 수 없으므로 어느 쪽도 저장하지 않는다(저장소 키가 `(cik, period_end)`다).
    """
    labels: dict[tuple[str, str], set[tuple[int, str]]] = {}
    for row in rows:
        key = (str(row["cik"]), str(row.get("period_end")))
        labels.setdefault(key, set()).add((int(row["fiscal_year"]), str(row["fiscal_period"])))
    colliding = {key for key, found in labels.items() if len(found) > 1}
    if not colliding:
        return rows, []
    kept: list[dict] = []
    anomalies: list[dict] = []
    for row in rows:
        key = (str(row["cik"]), str(row.get("period_end")))
        if key not in colliding:
            kept.append(row)
            continue
        anomalies.append({
            "cik": key[0],
            "fiscal_year": row["fiscal_year"],
            "fiscal_period": row["fiscal_period"],
            "reason": "period_label_conflict",
            "detail": {"period_end": key[1], "labels": sorted(labels[key])},
            "filed_at": row.get("filed_at"),
        })
    return kept, anomalies


# 한 회사의 분기 가중평균 주식수는 분기마다 크게 움직이지 않는다. 중앙값에서 이 배수 넘게
# 벗어난 분기의 주식수로는 EPS를 만들지 않는다 — 천·백만 단위 오류는 1,000배로 벌어진다.
_SHARES_MEDIAN_FACTOR = 10.0


def _per_share_from_income(rows: list[dict]) -> None:
    """보고된 EPS가 없는 분기(대개 Q4)는 순이익÷같은 분기 가중평균 주식수로 만든다.

    검증을 마친 뒤에 만든다. 이렇게 만든 EPS는 자기 입력과 늘 맞으므로, 주식수 단위 오류를
    잡는 `_scale_mismatch`가 그 오류를 볼 수 없다. 그래서 같은 회사의 다른 분기 주식수 중앙값과
    자릿수가 다른 주식수로는 만들지 않는다. 분자는 보통주 귀속 순이익(우선주 배당 차감)이 있으면
    그것, 없으면 모회사 귀속 순이익이다.
    """
    shares_by_cik: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        for column in ("shares_average", "shares_fully_diluted_average"):
            value = row.get(column)
            if value and value > 0:
                shares_by_cik.setdefault((str(row["cik"]), column), []).append(float(value))
    medians = {
        key: sorted(values)[len(values) // 2] for key, values in shares_by_cik.items()
    }
    for row in rows:
        numerator_column = (
            "net_income_to_common_shareholders"
            if row.get("net_income_to_common_shareholders") is not None
            else "net_income"
        )
        numerator = row.get(numerator_column)
        for eps_column, shares_column in (
            ("eps_basic_gaap", "shares_average"),
            ("eps_diluted_gaap", "shares_fully_diluted_average"),
        ):
            shares = row.get(shares_column)
            if row.get(eps_column) is not None or numerator is None or not shares or shares <= 0:
                continue
            median = medians.get((str(row["cik"]), shares_column))
            if median and not 1 / _SHARES_MEDIAN_FACTOR <= shares / median <= _SHARES_MEDIAN_FACTOR:
                continue
            row[eps_column] = numerator / shares
            manifests = row.get("source_manifest") or {}
            manifests[eps_column] = {
                "raw_tag": None,
                "accession_no": row.get("accession_no"),
                "period_end": row.get("period_end"),
                "is_derived": True,
                "derivation": {"formula": f"{numerator_column} / {shares_column}"},
            }
            row["source_manifest"] = manifests
