"""기업 전체 wide 재무 행의 불변조건을 검증하고 이상값을 격리한다."""
from __future__ import annotations

from investment_agent.platform.logging import get_logger
from investment_agent.data.fundamentals.domain.policies import BALANCE_TOLERANCE
from investment_agent.data.fundamentals.domain.services.balance_identity import non_liability_claims
from investment_agent.data.fundamentals.domain.taxonomy.financial_columns import CORE_COLUMNS

log = get_logger(__name__)


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
