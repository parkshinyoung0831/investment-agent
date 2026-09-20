"""기업 전체 wide 재무 행의 불변조건을 검증하고 이상값을 격리한다."""
from __future__ import annotations

import math

from investment_agent.platform.logging import get_logger
from investment_agent.data.fundamentals.domain.policies import (
    AVERAGE_SHARES_SCALE_FACTOR,
    BALANCE_TOLERANCE,
    PROFIT_OVER_REVENUE_TOLERANCE,
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

        # 회계항등식 A = L + 자본. liabilities_and_equity 컬럼은 두지 않는다 —
        # assets와 실측 23,849/23,851행이 동일한 순수 중복이었다.
        #
        # 우선주는 더하지 않는다. `preferred_stock`은 이미 `common_equity`
        # (StockholdersEquity) 안에 들어 있어 또 더하면 이중계상이다 — 실측 PSA는
        # A 20.21 = L 10.87 + E 9.25 + MI 0.09로 정확히 닫히는데, 우선주 4.35를
        # 더하는 바람에 21.5% 불일치로 잡히고 있었다.
        #
        # 메자닌 자본은 반대로 반드시 더한다. 명시적으로 상환가능한 지분은
        # 부채에도 영구자본에도 없는 중간 계층이라, 빼면 DVA·UDR·SPGI 같은 종목이
        # 구조적으로 어긋난다.
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

    if anomalies:
        log.warning("fundamentals anomalies recorded: %d", len(anomalies))
    return clean_rows, anomalies
