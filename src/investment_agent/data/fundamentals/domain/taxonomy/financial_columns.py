"""영구 저장이 허용된 기업 전체 재무 wide 컬럼 집합.

SEC fact는 변환 중에만 long 형태로 다루며, 이 목록에 없는 값은 표준화 후 폐기한다.

업종 전용 보조 계정 23종은 두 기준 모두에서 탈락해 제거했다 — 뷰·카드·대시보드
어디에서도 읽지 않았고, 업종을 고르게 덮은 45종목 2,167분기 실측에서 11종이
정확히 0.0%였다. 은행 4계정(net_interest_income·provision_for_credit_losses·
net_loans_and_leases·total_deposits)는 financials에 직접 저장하므로
CORE에 남긴다. 매출 세부 분해는 segment_metrics가 담당한다.
"""
from __future__ import annotations

CORE_COLUMNS: tuple[str, ...] = (
    "revenue",
    "cost_of_goods_and_services_sold",
    "gross_profit",
    "research_and_development_expenses",
    "selling_general_and_admin_expenses",
    "operating_income_loss",
    "interest_expense",
    "pretax_income_loss",
    "income_taxes",
    "net_income",
    "minority_interest_income",
    "net_income_to_common_shareholders",
    "eps_basic_gaap",
    "eps_diluted_gaap",
    "dividends_declared_per_share",
    "assets",
    "current_assets_total",
    "cash_and_cash_equivalents",
    "short_term_investments",
    "trade_receivables",
    "inventories",
    "property_plant_equipment_net",
    "goodwill",
    "intangible_assets_excluding_goodwill",
    "operating_lease_right_of_use_asset",
    "liabilities",
    "current_liabilities_total",
    "trade_payables",
    "short_term_debt",
    "current_portion_of_long_term_debt",
    "long_term_debt",
    "total_debt_including_current",
    "common_equity",
    "minority_interest_balance",
    "mezzanine_equity",
    "preferred_stock",
    "retained_earnings",
    "net_cash_from_operating_activities",
    "net_cash_from_investing_activities",
    "net_cash_from_financing_activities",
    "depreciation_amortization_cf",
    "stock_based_compensation_cf",
    "capital_expenses",
    "acquisitions_net_of_cash",
    "stock_repurchase_payments",
    "common_dividends_paid",
    "long_term_debt_issued",
    "long_term_debt_repaid",
    "operating_lease_current_debt_equivalent",
    "operating_lease_non_current_debt_equivalent",
    "shares_average",
    "shares_fully_diluted_average",
    # 은행 및 금융 핵심 계정
    "net_interest_income",
    "provision_for_credit_losses",
    "net_loans_and_leases",
    "total_deposits",
)

# 시점(instant) 성격의 대차대조표 컬럼. 같은 분기 키에 손익·AOCI 변동 같은
# 기간(duration) 항목이 매핑 과포함으로 섞여 들어와도, periodize가 이 컬럼들은
# 시점값을 우선 채택해 잔액 오염을 막는다(예: GOOGL common_equity =
# StockholdersEquity 478B 채택, ReclassificationFromAoci −139M 배제).
BALANCE_COLUMNS: frozenset[str] = frozenset({
    "assets", "current_assets_total",
    "cash_and_cash_equivalents", "short_term_investments",
    "trade_receivables", "inventories",
    "property_plant_equipment_net", "goodwill", "intangible_assets_excluding_goodwill",
    "operating_lease_right_of_use_asset",
    "liabilities", "current_liabilities_total", "trade_payables",
    "short_term_debt", "current_portion_of_long_term_debt", "long_term_debt",
    "total_debt_including_current",
    "common_equity", "minority_interest_balance", "mezzanine_equity",
    "preferred_stock", "retained_earnings",
    "operating_lease_current_debt_equivalent", "operating_lease_non_current_debt_equivalent",
    "net_loans_and_leases", "total_deposits",
})

ALL_WIDE_COLUMNS: frozenset[str] = frozenset(CORE_COLUMNS)

# 변환 중 회계적 분류를 검증하는 보조 fact. 영속 wide schema에는 저장하지 않는다.
# SPAC의 AssetsHeldInTrust가 확인될 때만 미보고 상환가능 주식 잔액을 회계항등식으로
# 복원하는 데 사용한다.
TRANSFORMATION_ONLY_COLUMNS: frozenset[str] = frozenset({
    "assets_held_in_trust",
})

COMPANYFACT_COLUMNS: frozenset[str] = (
    ALL_WIDE_COLUMNS | TRANSFORMATION_ONLY_COLUMNS
)

# XBRL 수치와 함께 영속화하는 품질 메타데이터. 수치 목록과 분리해야
# 컬럼 충전율·TTM 집계가 boolean을 재무 계정으로 오인하지 않는다.
PERSISTED_METADATA_COLUMNS: frozenset[str] = frozenset({
    "common_equity_scope",
    "is_liabilities_derived",
})
