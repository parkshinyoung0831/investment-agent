"""SEC us-gaap 태그를 프로젝트 표준 재무 컬럼으로 매핑한다.

edgartools의 ``gaap_mappings.json``을 기본 사전으로 사용하고, 명시적 정책과
우선순위로 한 공시 안에서 같은 컬럼에 겹친 fact를 결정적으로 선택한다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from investment_agent.platform.logging import get_logger
from investment_agent.data.fundamentals.domain.taxonomy.financial_columns import ALL_WIDE_COLUMNS

log = get_logger(__name__)

_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")
_NONWORD = re.compile(r"[^0-9a-zA-Z]+")
_DATA = Path(__file__).resolve().parents[2] / "data" / "gaap_mappings.json"
_MIN_CONFIDENCE = 0.20

# 사전은 폭넓은 후보군을 제공하고, 아래 정책은 투자 지표에 사용할 회계적
# 의미를 고정한다. 정책 버전은 영속 wide row에 남긴다.
#
# 값을 바꾸면 그 이전 정책으로 만든 행은 낡은 것이 되고 재처리 대상이 된다.
# 그래서 날짜가 아니라 세대 번호다 — 정책이 실제로 달라질 때만 v2로 올린다.
SEMANTIC_POLICY_VERSION = "v1"


@dataclass(frozen=True)
class ColumnPolicy:
    """중요 wide 컬럼의 허용 태그와 결정적 우선순위."""

    priority: dict[str, int]
    units: frozenset[str] = frozenset({"USD"})
    reject_conflict: bool = True


COLUMN_POLICIES: dict[str, ColumnPolicy] = {
    # 대차대조표 총계는 정확한 총계 태그만 허용한다. 사전 fallback이 총계를
    # 보고하지 않는 보험사에서 UnearnedPremiums 같은 부분 부채를 liabilities로
    # 채운 사례가 있었고, 그 값은 자산의 3%뿐인데도 정상 수치처럼 저장됐다.
    "assets": ColumnPolicy({
        "Assets": 10,
    }),
    "liabilities": ColumnPolicy({
        "Liabilities": 10,
    }),
    # 실제 희석주식수와 basic=diluted 통합 태그만 허용한다. edgartools 사전은
    # 전환주식 발행량 같은 기간 활동 태그도 이 잔액에 보내므로 단위 검사만으로는
    # 오염을 막을 수 없다.
    "shares_fully_diluted_average": ColumnPolicy({
        "WeightedAverageNumberOfDilutedSharesOutstanding": 10,
        "WeightedAverageNumberOfShareOutstandingBasicAndDiluted": 20,
    }, units=frozenset({"shares"})),
    "eps_basic_gaap": ColumnPolicy({
        "EarningsPerShareBasic": 10,
        "IncomeLossFromContinuingOperationsPerBasicShare": 20,
    }, units=frozenset({"USD/shares", "pure", "USD", "shares"})),
    "eps_diluted_gaap": ColumnPolicy({
        "EarningsPerShareDiluted": 10,
        "IncomeLossFromContinuingOperationsPerDilutedShare": 20,
    }, units=frozenset({"USD/shares", "pure", "USD", "shares"})),
    "common_equity": ColumnPolicy({
        "CommonStockholdersEquity": 10,
        "StockholdersEquity": 20,
        "PartnersCapitalIncludingPortionAttributableToNoncontrollingInterest": 80,
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": 90,
        "LimitedLiabilityCompanyLlcMembersEquityIncludingPortionAttributableToNoncontrollingInterest": 100,
    }),
    "cash_and_cash_equivalents": ColumnPolicy({
        "CashAndCashEquivalentsAtCarryingValue": 10,
    }),
    # 단기투자자산. 현금과 따로 저장해 뷰가 둘을 더해 EV·순부채를 만든다.
    # 합산 태그(CashCashEquivalentsAndShortTermInvestments)를 쓰는 회사는 495개 중
    # 8개뿐이라 그 하나만 보면 현금성자산이 사실상 늘 비어 EV가 과대평가된다.
    "short_term_investments": ColumnPolicy({
        "ShortTermInvestments": 10,
        "MarketableSecuritiesCurrent": 20,
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent": 30,
        "OtherShortTermInvestments": 40,
    }),
    "total_debt_including_current": ColumnPolicy({
        "DebtAndCapitalLeaseObligations": 10,
        "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities": 20,
    }),
    # 아래 정책들은 변환 source manifest 실측에서 사전 rank 동률이
    # 잦고, 알파벳 tie-break가 회계적으로 다른 개념을 고르던 컬럼들이다.
    # 총계 태그를 우선하고, 현금흐름표 항목·부분항목·무관 손익은 후보에서 제외한다.

    # 총 법인세비용. DeferredIncomeTaxExpenseBenefit(이연분)과 IncomeTaxesPaid*(현금
    # 납부액)는 개념이 달라 제외 — 실측 30.7%가 이연분으로 채워지고 있었다.
    "income_taxes": ColumnPolicy({
        "IncomeTaxExpenseBenefit": 10,
        "IncomeTaxExpenseBenefitContinuingOperations": 20,
    }),
    # 손익계산서 이자비용. GainsLossesOnExtinguishmentOfDebt(부채상환손익)·
    # InterestPaid*(현금흐름표)·순액 태그는 제외 — 실측 17.9%가 상환손익이었다.
    "interest_expense": ColumnPolicy({
        "InterestExpense": 10,
        "InterestExpenseNonoperating": 20,
        "InterestAndDebtExpense": 30,
        "InterestExpenseDebt": 40,
        "InterestExpenseBorrowings": 50,
        "InterestExpenseOperating": 60,
        "FinancingInterestExpense": 70,
        "InterestExpenseOther": 80,
        "FinanceLeaseInterestExpense": 90,
    }),
    # 매출원가 총계. LaborAndRelatedExpense(인건비)처럼 부분 원가는 제외.
    "cost_of_goods_and_services_sold": ColumnPolicy({
        "CostOfGoodsAndServicesSold": 10,
        "CostOfRevenue": 20,
        "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization": 30,
    }),
    # EBITDA 브릿지에 쓰이므로 상각까지 포함한 넓은 개념을 우선한다.
    "depreciation_amortization_cf": ColumnPolicy({
        "DepreciationDepletionAndAmortization": 10,
        "DepreciationAmortizationAndAccretionNet": 20,
        "DepreciationAndAmortization": 30,
        "CostDepreciationAmortizationAndDepletion": 40,
        "Depreciation": 50,
    }),
    # 매출. 카지노·유지보수 같은 개별 매출 라인은 총매출 대용이 될 수 없어 제외.
    "revenue": ColumnPolicy({
        "RevenueFromContractWithCustomerExcludingAssessedTax": 10,
        "Revenues": 20,
        "RevenueFromContractWithCustomerIncludingAssessedTax": 30,
        "RevenuesNetOfInterestExpense": 40,
        "RegulatedAndUnregulatedOperatingRevenue": 50,
        "SalesAndOtherOperatingRevenueIncludingSalesBasedTaxes": 60,
        "SalesRevenueNet": 70,
        "SalesRevenueGoodsNet": 80,
    }),
    # 현금흐름표 3대 총계. 사전은 배당 지급·리스부채 증감·기타 재무활동 같은 개별
    # 라인아이템까지 이 컬럼으로 보낸다. 총계 태그가 있는 공시에서는 is_total 랭크가
    # 이겨서 드러나지 않지만, 총계를 태깅하지 않은 공시에서는 라인아이템 하나가
    # 총계 자리를 조용히 차지한다. 총계 태그만 허용한다.
    "net_cash_from_operating_activities": ColumnPolicy({
        "NetCashProvidedByUsedInOperatingActivities": 10,
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations": 20,
        "CashFlowsFromUsedInOperatingActivities": 30,
    }),
    "net_cash_from_investing_activities": ColumnPolicy({
        "NetCashProvidedByUsedInInvestingActivities": 10,
        "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations": 20,
        "CashFlowsFromUsedInInvestingActivities": 30,
    }),
    "net_cash_from_financing_activities": ColumnPolicy({
        "NetCashProvidedByUsedInFinancingActivities": 10,
        "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations": 20,
        "CashFlowsFromUsedInFinancingActivities": 30,
    }),
    # 보통주 배당 '지급액'(현금흐름표). 사전은 지급액 태그를 재무활동 총계로 보내고,
    # 자본변동표의 '선언액'(DividendsCommonStockCash 등)을 이 컬럼에 채워 넣는다 —
    # 개념이 달라 dividend_yield가 선언액 기준이 된다. 지급액 태그만 허용한다.
    # PaymentsOfDividends는 우선주·비지배 배당까지 포함한 총액이라, 보통주 전용
    # 태그가 없는 공시(AAPL·JPM·NEE 등)에서만 차선책으로 쓴다.
    "common_dividends_paid": ColumnPolicy({
        "PaymentsOfDividendsCommonStock": 10,
        "PaymentsOfDividends": 20,
        "DividendsPaidClassifiedAsFinancingActivities": 30,
    }),
    # 보통주 자사주 매입 현금유출. 우선주·상환우선주·비지배지분 재매입은 주주환원
    # 수익률의 분자가 아니라서 제외한다.
    "stock_repurchase_payments": ColumnPolicy({
        "PaymentsForRepurchaseOfCommonStock": 10,
        "PaymentsForRepurchaseOfEquity": 20,
        "PaymentsToAcquireOrRedeemEntitysShares": 30,
        "PurchaseOfTreasuryShares": 40,
    }),
    # 유형자산 취득 현금유출. CapitalExpendituresIncurredButNotYetPaid는 미지급
    # 발생액 주석이라 현금유출이 아니다 — capital_expenses 검증에서
    # 동률 42건이 전부 이 태그와의 충돌이었다.
    "capital_expenses": ColumnPolicy({
        "PaymentsToAcquirePropertyPlantAndEquipment": 10,
        "PaymentsToAcquireProductiveAssets": 20,
        "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": 30,
        "PaymentsToAcquireOtherPropertyPlantAndEquipment": 40,
        "PaymentsToAcquireOtherProductiveAssets": 50,
    }),
    # 인수 현금유출. 유기적 성장과 인수 성장을 가르고, 진짜 FCF에서 뺀다.
    "acquisitions_net_of_cash": ColumnPolicy({
        "PaymentsToAcquireBusinessesNetOfCashAcquired": 10,
        "PaymentsToAcquireBusinessesAndInterestInAffiliatesNetOfCashAcquired": 20,
        "PaymentsToAcquireBusinessesGross": 30,
    }),
    # 장기차입 조달·상환. 자본배분(차입 vs 자사주 vs 배당) 분해에 쓴다.
    "long_term_debt_issued": ColumnPolicy({
        "ProceedsFromIssuanceOfLongTermDebt": 10,
        "ProceedsFromNotesPayable": 20,
        "ProceedsFromIssuanceOfSeniorLongTermDebt": 30,
    }),
    "long_term_debt_repaid": ColumnPolicy({
        "RepaymentsOfLongTermDebt": 10,
        "RepaymentsOfNotesPayable": 20,
        "RepaymentsOfSeniorDebt": 30,
    }),
    # 판관비. 매출총이익에서 영업이익으로 내려가는 핵심 라인이라 영업레버리지의
    # 분모다. G&A·판매비 부분항목은 총계를 대체하지 못하므로 제외한다.
    "selling_general_and_admin_expenses": ColumnPolicy({
        "SellingGeneralAndAdministrativeExpense": 10,
        "GeneralAndAdministrativeExpense": 20,
    }),
    # 비지배지분 귀속 손익(기간). minority_interest_balance(잔액)와 다른 축이다.
    "minority_interest_income": ColumnPolicy({
        "NetIncomeLossAttributableToNoncontrollingInterest": 10,
        "ProfitLossAttributableToNoncontrollingInterest": 20,
    }),
    # 영구자본 안의 비지배지분 잔액만 허용한다. 사전이 VIE의 연결 자산·부채
    # carrying amount를 이 컬럼으로 보내 회계항등식 양쪽을 오염시키던 매핑은 제외한다.
    "minority_interest_balance": ColumnPolicy({
        "DerivedNoncontrollingInterestFromTotalEquity": 5,
        "MinorityInterest": 10,
        "NoncontrollingInterests": 20,
        "MembersEquityAttributableToNoncontrollingInterest": 30,
        "NonredeemableNoncontrollingInterest": 40,
        "PartnersCapitalAttributableToNoncontrollingInterest": 50,
        "MinorityInterestInNetAssetsOfConsolidatedEntities": 60,
        "MinorityInterestInJointVentures": 70,
        "MinorityInterestInOperatingPartnerships": 80,
        "MinorityInterestInLimitedPartnerships": 90,
    }),
    # 유형자산 순액. 자산집약도와 capex/감가상각 배수의 분모.
    "property_plant_equipment_net": ColumnPolicy({
        "PropertyPlantAndEquipmentNet": 10,
        "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization": 20,
        "RealEstateInvestmentPropertyNet": 30,
    }),
    # 영업권·무형자산. 유형장부가치(tangible book value)를 만들려면 둘을 따로 빼야
    # 한다. 합산 태그(IntangibleAssetsNetIncludingGoodwill)는 분해가 안 돼 제외.
    "goodwill": ColumnPolicy({
        "Goodwill": 10,
    }),
    "intangible_assets_excluding_goodwill": ColumnPolicy({
        "IntangibleAssetsNetExcludingGoodwill": 10,
        "FiniteLivedIntangibleAssetsNet": 20,
    }),
    # 운용리스 사용권자산. 부채(operating_lease_*_debt_equivalent)의 자산 쪽 짝이다.
    "operating_lease_right_of_use_asset": ColumnPolicy({
        "OperatingLeaseRightOfUseAsset": 10,
    }),
    # 메자닌(임시) 자본. 명시적으로 상환가능한 비지배지분·우선주는 부채도
    # 영구자본도 아닌 중간 계층이다. 저장하지 않으면
    # 회계항등식이 구조적으로 깨지고(실측 35개 종목), EV에서도 보통주보다 앞선
    # 청구권이 빠진다. 사전은 이 태그들을 스키마에 없는 키로 보내 전량 버렸다.
    "mezzanine_equity": ColumnPolicy({
        "DerivedMezzanineEquityFromBalanceTotals": 4,
        "DerivedMezzanineEquityFromComponents": 5,
        "DerivedMezzanineEquityFromSpacTrust": 6,
        "TemporaryEquityCarryingAmount": 10,
        "TemporaryEquityCarryingAmountIncludingPortionAttributableToNoncontrollingInterests": 20,
        "RedeemableNoncontrollingInterestEquityCarryingAmount": 30,
        "TemporaryEquityCarryingAmountAttributableToParent": 40,
        "TemporaryEquityCarryingAmountAttributableToNoncontrollingInterest": 50,
        "RedeemableNoncontrollingInterestEquityCommonCarryingAmount": 60,
        "RedeemableNoncontrollingInterestEquityPreferredCarryingAmount": 70,
        "RedeemableNoncontrollingInterestEquityOtherCarryingAmount": 80,
        "RedeemableNoncontrollingInterestEquityFairValue": 90,
        "RedeemableNoncontrollingInterestEquityCommonFairValue": 100,
        "RedeemableNoncontrollingInterestEquityOtherFairValue": 110,
    }),
    "assets_held_in_trust": ColumnPolicy({
        "AssetsHeldInTrust": 10,
        "AssetsHeldInTrustNoncurrent": 20,
    }),
    # 주당 선언 배당금. 지급 총액(common_dividends_paid)과 달리 주당 기준이라
    # 배당성향·배당성장률에 쓴다. FSDS는 uom=USD, companyfacts는 USD/shares로 준다.
    "dividends_declared_per_share": ColumnPolicy({
        "CommonStockDividendsPerShareDeclared": 10,
        "CommonStockDividendsPerShareCashPaid": 20,
    }, units=frozenset({"USD/shares", "USD"})),

    # mapping_conflict 해결을 위한 우선순위 정책:
    # is_total(총계 여부) → confidence → company_count(학습 표본에서 그 태그를 쓴 회사 수)
    # 순으로 정렬하고, 대조계정·처분전 총액·주석 공시성 항목(감가상각누계액, 대손충당금 등)을
    # 제외하여 변별력을 확보한다. 정책이 정의되지 않은 컬럼은 동률 시 값을 버린다.
    "real_estate_investments": ColumnPolicy({
        "RealEstateInvestmentPropertyNet": 10,
        "RealEstateInvestmentPropertyAtCost": 20,
    }),
    "net_loans_and_leases": ColumnPolicy({
        "LoansAndLeasesReceivableNetReportedAmount": 10,
        "FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss": 20,
        "LoansAndLeasesReceivableNetOfDeferredIncome": 30,
        "FinancingReceivableExcludingAccruedInterestBeforeAllowanceForCreditLoss": 40,
    }),
    # 예금총액만 저장한다. 이자부·무이자부·정기예금은 서로 더해야 하는 구성항목이라
    # 그중 하나를 총액으로 선택하는 것보다 값을 비워두는 편이 정확하다. 공정가치
    # 주석도 장부금액과 의미가 달라 제외한다.
    "total_deposits": ColumnPolicy({
        "Deposits": 10,
    }),
    "trade_receivables": ColumnPolicy({
        "AccountsReceivableNetCurrent": 10,
        "ReceivablesNetCurrent": 20,
        "TradeAndOtherCurrentReceivables": 30,
        "AccountsAndOtherReceivablesNetCurrent": 40,
        "AccountsReceivableNet": 50,
        "NotesAndLoansReceivableNetCurrent": 60,
        "LoansReceivableHeldForSaleAmount": 70,
        "UnbilledReceivablesCurrent": 80,
        "AccountsNotesAndLoansReceivableNetCurrent": 90,
        "AccountsAndNotesReceivableNet": 100,
        "PremiumsReceivableAtCarryingValue": 110,
        "ReceivablesFromCustomers": 120,
        "TradeReceivables": 130,
        "UnbilledContractsReceivable": 140,
        "FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLossCurrent": 150,
        "ReceivablesLongTermContractsOrPrograms": 160,
        "OilAndGasJointInterestBillingReceivablesCurrent": 170,
        "AccountsReceivableGross": 180,
        "BilledContractReceivables": 190,
        "ContractsReceivableClaimsAndUncertainAmounts": 200,
        "AccountsReceivableBilledForLongTermContractsOrPrograms": 210,
        "ContractReceivableRetainage": 220,
        "GovernmentContractReceivable": 230,
        "GovernmentContractReceivableProgessPaymentsOffset": 240,
    }),
    "inventories": ColumnPolicy({
        "InventoryNet": 10,
        "Inventories": 20,
        "InventoryGross": 30,
        "InventoryFinishedGoodsNetOfReserves": 40,
        "InventoryRawMaterialsAndSupplies": 50,
        "InventoryFinishedGoods": 60,
        "InventoryWorkInProcess": 70,
        "OtherInventorySupplies": 80,
        "EnergyRelatedInventory": 90,
        "InventoryRawMaterials": 100,
        "FIFOInventoryAmount": 110,
        "InventoryNetOfAllowancesCustomerAdvancesAndProgressBillings": 120,
        "RetailRelatedInventoryMerchandise": 130,
        "OtherInventoryNetOfReserves": 140,
        "InventoryFinishedGoodsAndWorkInProcess": 150,
        "InventoryFinishedGoodsAndWorkInProcessNetOfReserves": 160,
        "EnergyRelatedInventoryCoal": 170,
        "InventoryCrudeOilProductsAndMerchandise": 180,
        "InventoryForLongTermContractsOrPrograms": 190,
        "InventoryWorkInProcessAndRawMaterials": 200,
        "RetailRelatedInventory": 210,
        "AgriculturalRelatedInventory": 220,
        "InventoryOreStockpilesOnLeachPads": 230,
        "InventoryWorkInProcessAndRawMaterialsNetOfReserves": 240,
        "InventoryWorkInProcessNetOfReserves": 250,
        "InventoryRawMaterialsNetOfReserves": 260,
        "InventoryRawMaterialsAndSuppliesNetOfReserves": 270,
        "EnergyRelatedInventoryNaturalGasInStorage": 280,
        "EnergyRelatedInventoryGasStoredUnderground": 290,
        "EnergyRelatedInventoryOtherFossilFuel": 300,
        "OtherInventory": 310,
        "InventoryAdjustments": 320,
        "InventoryPartsAndComponentsNetOfReserves": 330,
        "OtherInventoryInTransit": 340,
        "CrudeOilAndNaturalGasLiquids": 350,
        "EnergyRelatedInventoryPropaneGas": 360,
        "InventorySuppliesNetOfReserves": 370,
        "AirlineRelatedInventory": 380,
        "AirlineRelatedInventoryAircraftFuel": 390,
        "AirlineRelatedInventoryAircraftParts": 400,
        "EnergyRelatedInventoryChemicals": 410,
        "EnergyRelatedInventoryPetroleum": 420,
        "InventoryRawMaterialsAndPurchasedPartsNetOfReserves": 430,
        "OtherInventoriesSpareParts": 440,
        "OtherInventoryCapitalizedCosts": 450,
        "AgriculturalRelatedInventoryFeedAndSupplies": 460,
        "AgriculturalRelatedInventoryGrowingCrops": 470,
        "AgriculturalRelatedInventoryPlantMaterial": 480,
        "EnergyRelatedInventoryNaturalGasLiquids": 490,
        "OtherInventoryDemo": 500,
        "OtherInventoryInventoryAtOffSitePremises": 510,
        "OtherInventoryMaterialsSuppliesAndMerchandiseUnderConsignment": 520,
        "OtherInventoryPurchasedGoods": 530,
        "OtherInventoryScrap": 540,
        "OtherInventoryWarehouse": 550,
        "RetailRelatedInventoryPackagingAndOtherSupplies": 560,
    }),
    "long_term_debt": ColumnPolicy({
        "LongTermDebtNoncurrent": 10,
        "FinanceLeaseLiabilityNoncurrent": 20,
        "LongTermNotesPayable": 30,
        "LongTermDebt": 40,
        "LongTermDebtAndCapitalLeaseObligations": 50,
        "LongtermBorrowings": 60,
        "ConvertibleLongTermNotesPayable": 70,
        "NotesPayable": 80,
        "LongTermLoansPayable": 90,
        "LongTermLineOfCredit": 100,
        "NotesPayableRelatedPartiesNoncurrent": 110,
        "OtherLongTermDebtNoncurrent": 120,
        "SecuredLongTermDebt": 130,
        "LongTermLoansFromBank": 140,
        "UnsecuredDebt": 150,
        "SeniorNotes": 160,
        "OtherLongTermDebt": 170,
        "SeniorLongTermNotes": 180,
        "JuniorSubordinatedNotes": 190,
        "UnsecuredLongTermDebt": 200,
        "LongTermNotesAndLoans": 210,
        "SubordinatedLongTermDebt": 220,
        "NotesPayableToBank": 230,
        "MediumTermNotes": 240,
        "TransfersAccountedForAsSecuredBorrowingsAssociatedLiabilitiesCarryingAmount": 250,
        "LongtermFederalHomeLoanBankAdvancesNoncurrent": 260,
        "OtherLongTermNotesPayable": 270,
        "CapitalLeaseObligationsNoncurrent": 280,
        "NotesPayableToBankNoncurrent": 290,
        "OtherLoansPayableLongTerm": 300,
        "ConvertibleSubordinatedDebtNoncurrent": 310,
        "ConstructionLoanNoncurrent": 320,
        "JuniorSubordinatedLongTermNotes": 330,
        "LongTermTransitionBond": 340,
        "MediumtermNotesNoncurrent": 350,
        "CommercialPaperNoncurrent": 360,
        "SpecialAssessmentBondNoncurrent": 370,
        "UnamortizedLossReacquiredDebtNoncurrent": 380,
        "JuniorSubordinatedDebentureOwedToUnconsolidatedSubsidiaryTrustNoncurrent": 390,
        "LongTermPollutionControlBond": 400,
        "NoncurrentBorrowings": 410,
    }),
    "short_term_debt": ColumnPolicy({
        "NotesPayableCurrent": 10,
        "ConvertibleNotesPayableCurrent": 20,
        "ShortTermBorrowings": 30,
        "FinanceLeaseLiabilityCurrent": 40,
        "NotesPayableRelatedPartiesClassifiedCurrent": 50,
        "LoansPayableCurrent": 60,
        "LinesOfCreditCurrent": 70,
        "ConvertibleDebtCurrent": 80,
        "DebtCurrent": 90,
        "LineOfCredit": 100,
        "ShorttermBorrowings": 110,
        "OtherNotesPayableCurrent": 120,
        "LoansPayable": 130,
        "ConvertibleNotesPayable": 140,
        "OtherShortTermBorrowings": 150,
        "SecuredDebtCurrent": 160,
        "OtherLoansPayableCurrent": 170,
        "ConvertibleDebt": 180,
        "DebtLongtermAndShorttermCombinedAmount": 190,
        "NotesAndLoansPayableCurrent": 200,
        "OtherNotesPayable": 210,
        "NotesAndLoansPayable": 220,
        "SeniorNotesCurrent": 230,
        "DebtInstrumentCarryingAmount": 240,
        "UnsecuredDebtCurrent": 250,
        "WarehouseAgreementBorrowings": 260,
        "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities": 270,
        "CapitalLeaseObligations": 280,
        "ShortTermBankLoansAndNotesPayable": 290,
        "LoansPayableToBankCurrent": 300,
        "OtherLongTermDebtCurrent": 310,
        "BankOverdrafts": 320,
        "NotesPayableToBankCurrent": 330,
        "CapitalLeaseObligationsCurrent": 340,
        "ShortTermNonBankLoansAndNotesPayable": 350,
        "CommercialPaper": 360,
        "BridgeLoan": 370,
        "BankLoans": 380,
        "ConvertibleSubordinatedDebtCurrent": 390,
        "SubordinatedDebtCurrent": 400,
        "FederalHomeLoanBankAdvancesCurrent": 410,
        "ConstructionLoan": 420,
        "LongTermConstructionLoanCurrent": 430,
        "BorrowingsUnderGuaranteedInvestmentAgreements": 440,
        "LongtermTransitionBondCurrent": 450,
        "JuniorSubordinatedNotesCurrent": 460,
        "LongTermCommercialPaperCurrent": 470,
        "LongtermCommercialPaperCurrentAndNoncurrent": 480,
        "LongtermPollutionControlBondCurrent": 490,
        "MediumtermNotesCurrent": 500,
        "CurrentBorrowings": 510,
        "JuniorSubordinatedDebentureOwedToUnconsolidatedSubsidiaryTrustCurrent": 520,
        "SpecialAssessmentBondCurrent": 530,
    }),
    # "AndAccruedLiabilities" 계열은 confidence·company_count가 더 높지만 매입채무
    # 외 발생비용까지 섞인 넓은 개념이라, 이 컬럼의 한글 정의(COLUMNS.md: 공급업체
    # 매입대금)에 정확히 맞는 "Trade"·순수 AccountsPayable 태그를 실측 순위보다 앞에 둔다.
    "trade_payables": ColumnPolicy({
        "AccountsPayableCurrent": 10,
        "AccountsPayableTradeCurrent": 20,
        "TradeAndOtherCurrentPayables": 30,
        "AccountsPayableAndAccruedLiabilitiesCurrent": 40,
        "AccountsPayableAndOtherAccruedLiabilitiesCurrent": 50,
        "AccountsPayableAndAccruedLiabilitiesCurrentAndNoncurrent": 60,
        "AccountsPayableRelatedPartiesCurrent": 70,
        "AccountsPayableCurrentAndNoncurrent": 80,
        "AccountsPayableAndOtherAccruedLiabilities": 90,
        "AccountsPayableOtherCurrent": 100,
        "AccountsPayableTradeCurrentAndNoncurrent": 110,
        "TradeAndOtherCurrentPayablesToTradeSuppliers": 120,
        "AccountsPayableUnderwritersPromotersAndEmployeesOtherThanSalariesAndWagesCurrent": 130,
        "ProgramRightsObligationsCurrent": 140,
        "OilAndGasSalesPayableCurrent": 150,
        "AccruedParticipationLiabilitiesDueInNextOperatingCycle": 160,
        "EnergyMarketingAccountsPayable": 170,
        "GasImbalancePayableCurrent": 180,
        "GasPurchasePayableCurrent": 190,
        "SupplierFinanceProgramObligationCurrent": 200,
        "OilAndGasSalesPayableCurrentAndNoncurrent": 210,
    }),
}
# longterm_investments는 정책을 만들지 않는다 — CORE_COLUMNS에 없는 column_key라
# allowed_keys 필터에서 이미 걸러진다. 정책을 넣어도 절대 호출되지 않는다.

# 정책이 없는 wide 컬럼의 기대 단위. 사전이 금액 태그를 주식수 컬럼으로 보내는 식의
# 단위 불일치를 막는다. wide 컬럼이 아니면 어차피 뒤에서 버려지므로 검사하지 않는다.
_SHARE_UNIT_COLUMNS: frozenset[str] = frozenset({
    "shares_average",
    "shares_fully_diluted_average",
})
_DEFAULT_UNITS: frozenset[str] = frozenset({"USD"})

# 제한현금 포함 현금과 총액 이연법인세는 EV·순자산 지표에 바로 쓰면 의미가
# 달라진다. 별도 컬럼 정책을 추가하기 전에는 wide 적재 후보에서 제외한다.
EXCLUDED_TAGS: frozenset[str] = frozenset({
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    "DeferredTaxAssetsGrossNoncurrent",
    "DeferredTaxLiabilitiesGrossNoncurrent",
})


def _snake(name: str) -> str:
    """CamelCase나 라벨 형태의 문자열을 snake_case로 바꾼다."""
    s = _CAMEL.sub("_", name)
    s = _NONWORD.sub("_", s)
    return s.strip("_").lower()


# 분석 뷰가 특정 컬럼을 요구하는 스키마 수준의 예외만 최소한으로 둔다.
CORE_OVERRIDES: dict[str, str] = {
    "ProfitLoss": "net_income",
    "StockholdersEquity": "common_equity",
    "CommonStockholdersEquity": "common_equity",
    "DebtAndCapitalLeaseObligations": "total_debt_including_current",
    "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities": "total_debt_including_current",
    "RevenuesNetOfInterestExpense": "revenue",
    "RegulatedAndUnregulatedOperatingRevenue": "revenue",
    "SalesAndOtherOperatingRevenueIncludingSalesBasedTaxes": "revenue",
    "CashAndCashEquivalentsAtCarryingValue": "cash_and_cash_equivalents",
    "ShortTermInvestments": "short_term_investments",
    "MarketableSecuritiesCurrent": "short_term_investments",
    "AvailableForSaleSecuritiesDebtSecuritiesCurrent": "short_term_investments",
    "OtherShortTermInvestments": "short_term_investments",
    # 자사주 매입 현금유출 — dict은 PaymentsForRepurchaseOfCommonStock을
    # equity_expense_income_buyback_issued(우리 스키마 미사용)로 보내 자사주 컬럼이 빈다.
    "PaymentsForRepurchaseOfCommonStock": "stock_repurchase_payments",
    "PaymentsForRepurchaseOfEquity": "stock_repurchase_payments",
    # 배당 '지급액' 두 태그의 사전 목적지가 각각 재무활동 총계와 비지배지분
    # 분배금이라, 보통주 배당 컬럼에는 한 건도 도달하지 못했다.
    "PaymentsOfDividendsCommonStock": "common_dividends_paid",
    "PaymentsOfDividends": "common_dividends_paid",
    # 아래 계정들은 사전이 우리 스키마에 없는 column key로 보내 전량 폐기됐다.
    # 추적 495개사 기준 실제 보고 회사 수를 괄호에 적는다.
    "SellingGeneralAndAdministrativeExpense": "selling_general_and_admin_expenses",  # 271
    "GeneralAndAdministrativeExpense": "selling_general_and_admin_expenses",
    "Goodwill": "goodwill",  # 414
    "IntangibleAssetsNetExcludingGoodwill": "intangible_assets_excluding_goodwill",  # 266
    "FiniteLivedIntangibleAssetsNet": "intangible_assets_excluding_goodwill",
    "PropertyPlantAndEquipmentNet": "property_plant_equipment_net",  # 325
    "OperatingLeaseRightOfUseAsset": "operating_lease_right_of_use_asset",  # 226
    "NetIncomeLossAttributableToNoncontrollingInterest": "minority_interest_income",  # 234
    "ProfitLossAttributableToNoncontrollingInterest": "minority_interest_income",
    "PaymentsToAcquireBusinessesNetOfCashAcquired": "acquisitions_net_of_cash",  # 253
    "PaymentsToAcquireBusinessesAndInterestInAffiliatesNetOfCashAcquired": "acquisitions_net_of_cash",
    "PaymentsToAcquireBusinessesGross": "acquisitions_net_of_cash",
    "ProceedsFromIssuanceOfLongTermDebt": "long_term_debt_issued",  # 190
    "ProceedsFromNotesPayable": "long_term_debt_issued",
    "ProceedsFromIssuanceOfSeniorLongTermDebt": "long_term_debt_issued",
    "RepaymentsOfLongTermDebt": "long_term_debt_repaid",  # 210
    "RepaymentsOfNotesPayable": "long_term_debt_repaid",
    "RepaymentsOfSeniorDebt": "long_term_debt_repaid",
    # 메자닌 자본 — 사전 목적지가 temporary_and_mezzanine_financing 등 스키마에
    # 없는 키라 전량 폐기되던 명시적 temporary/redeemable 태그를 보존한다.
    "RedeemableNoncontrollingInterestEquityCarryingAmount": "mezzanine_equity",
    "TemporaryEquityCarryingAmount": "mezzanine_equity",
    "TemporaryEquityCarryingAmountIncludingPortionAttributableToNoncontrollingInterests": "mezzanine_equity",
    "TemporaryEquityCarryingAmountAttributableToParent": "mezzanine_equity",
    "TemporaryEquityCarryingAmountAttributableToNoncontrollingInterest": "mezzanine_equity",
    "RedeemableNoncontrollingInterestEquityCommonCarryingAmount": "mezzanine_equity",
    "RedeemableNoncontrollingInterestEquityPreferredCarryingAmount": "mezzanine_equity",
    "RedeemableNoncontrollingInterestEquityOtherCarryingAmount": "mezzanine_equity",
    "RedeemableNoncontrollingInterestEquityFairValue": "mezzanine_equity",
    "RedeemableNoncontrollingInterestEquityCommonFairValue": "mezzanine_equity",
    "RedeemableNoncontrollingInterestEquityOtherFairValue": "mezzanine_equity",
    # 영속 컬럼이 아닌 변환 보조 fact다. SPAC의 신탁자산이 총자산 대부분임을
    # 확인한 경우에만 누락된 상환가능 주식 잔액을 복원한다.
    "AssetsHeldInTrust": "assets_held_in_trust",
    "AssetsHeldInTrustNoncurrent": "assets_held_in_trust",
    # 연결 영구자본 안의 비지배지분. 총자본과 모회사 자본이 함께 있으면 변환기가
    # 그 차이를 우선 사용하고, 아래 태그들은 총계 차이를 만들 수 없을 때만 쓴다.
    "MinorityInterestInNetAssetsOfConsolidatedEntities": "minority_interest_balance",
    "MinorityInterestInJointVentures": "minority_interest_balance",
    "MinorityInterestInOperatingPartnerships": "minority_interest_balance",
    "MinorityInterestInLimitedPartnerships": "minority_interest_balance",
    "CommonStockDividendsPerShareDeclared": "dividends_declared_per_share",  # 234
    "CommonStockDividendsPerShareCashPaid": "dividends_declared_per_share",
    "EarningsPerShareBasic": "eps_basic_gaap",
    "EarningsPerShareDiluted": "eps_diluted_gaap",
}

# 모회사 자본(StockholdersEquity)을 보고하지 않고 총자본(비지배 포함)만 쓰는 회사
# (예: CAT)를 위한 common_equity fallback. CORE_OVERRIDES(rank -1)보다 우선순위를
# 낮춰(rank 0), 둘 다 있으면 모회사 자본을 택하고, 모회사 태그가 없으면 총자본을
# 잔액으로 채택한다(없으면 AOCI 같은 기간항목이 잘못 채워짐).
EQUITY_FALLBACK_OVERRIDES: dict[str, str] = {
    "PartnersCapitalIncludingPortionAttributableToNoncontrollingInterest": "common_equity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": "common_equity",
    "LimitedLiabilityCompanyLlcMembersEquityIncludingPortionAttributableToNoncontrollingInterest": "common_equity",
}


def _load_maps() -> tuple[dict[str, str], dict[str, str], dict[str, int]]:
    """원시 태그 매핑, 표준 컬럼 매핑, 충돌 우선순위를 읽는다."""
    standard_tags: dict[str, str] = {}
    column_keys: dict[str, str] = {}
    ranks: dict[str, int] = {}

    try:
        mappings = json.loads(_DATA.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError) as exc:
        log.warning("failed to load gaap_mappings.json (%s); using snake_case fallback", exc)
        mappings = {}

    for tag, info in mappings.items():
        tags = info.get("standard_tags") or []
        if not tags:
            continue
        confidence = float(info.get("confidence", 0) or 0)
        if confidence < _MIN_CONFIDENCE:
            continue

        standard_tag = str(tags[0])
        standard_tags[tag] = standard_tag
        column_keys[tag] = _snake(standard_tag)
        ranks[tag] = (0 if info.get("is_total") else 1000) + int((1.0 - confidence) * 100)

    # CF 감가상각·주식보상 addback을 _cf 컬럼으로 모은다(EBITDA·현금흐름 브릿지가 사용).
    # edgartools dict은 이를 depreciation_expense/stock_based_compensation_expense로
    # 보내는데, 그 컬럼은 fundamentals 스키마에서 쓰이지 않아 EBITDA에 D&A가 한 번도
    # 안 더해졌다(ebitda_ttm = 영업이익).
    cf_remap = {
        "depreciation_expense": "depreciation_amortization_cf",
        "stock_based_compensation_expense": "stock_based_compensation_cf",
    }
    for tag, key in list(column_keys.items()):
        if key in cf_remap:
            column_keys[tag] = cf_remap[key]

    for tag, key in CORE_OVERRIDES.items():
        standard_tags[tag] = key
        column_keys[tag] = key
        ranks[tag] = -1

    for tag, key in EQUITY_FALLBACK_OVERRIDES.items():
        standard_tags[tag] = key
        column_keys[tag] = key
        ranks[tag] = 0  # parent(rank -1)보다 덜, dict 오염 매핑(rank ≥ 1000)보다 우선

    return standard_tags, column_keys, ranks


STANDARD_TAG_MAP, CONCEPT_MAP, _CONCEPT_RANK = _load_maps()


def to_standard_tag(tag: str) -> str | None:
    """edgartools 표준 태그를 반환하며 사전에 없으면 ``None``을 돌려준다."""
    return STANDARD_TAG_MAP.get(tag)


def to_column_key(tag: str) -> str:
    """원시 us-gaap 태그에 대응하는 프로젝트 컬럼명을 반환한다."""
    return CONCEPT_MAP.get(tag) or _snake(tag)


def is_excluded_tag(tag: str) -> bool:
    """투자 지표 의미가 불명확해 자동 적재하지 않을 SEC 태그인지 반환한다."""
    return tag in EXCLUDED_TAGS


def policy_priority(tag: str, column_key: str) -> int:
    """컬럼 정책 우선순위가 있으면 사전 rank보다 우선한다."""
    policy = COLUMN_POLICIES.get(column_key)
    if policy is not None:
        return policy.priority.get(tag, 1_000_000)
    return concept_rank(tag)


def policy_accepts(tag: str, column_key: str, unit: str | None) -> bool:
    """정책이 태그와 단위를 허용하는지 반환한다.

    정책이 있는 컬럼은 화이트리스트 + 단위로 판정하고, 없는 wide 컬럼은 단위만
    검사한다(금액 태그가 주식수 컬럼에 섞여 들어가는 것을 막는다).
    """
    policy = COLUMN_POLICIES.get(column_key)
    if policy is not None:
        return tag in policy.priority and unit in policy.units
    if is_excluded_tag(tag):
        return False
    if column_key in ALL_WIDE_COLUMNS:
        expected = (
            frozenset({"shares"})
            if column_key in _SHARE_UNIT_COLUMNS
            else _DEFAULT_UNITS
        )
        return unit in expected
    return True


def policy_rejects_conflict(column_key: str) -> bool:
    """동률 후보가 남았을 때 값을 버려야 하는 컬럼인지 반환한다.

    정책이 없는 컬럼도 기본은 '버린다'. 동률을 임의 규칙(예: 태그 이름 알파벳 순)으로
    깨면 회계적으로 다른 개념을 계통적으로 집는다 — 이연법인세를 총법인세로,
    부채상환손익을 이자비용으로. 틀린 값보다 빈 값이 안전하고, 무엇이 걸렸는지는
    JSON 검증 로그에 남는다.
    """
    policy = COLUMN_POLICIES.get(column_key)
    if policy is None:
        return True
    return policy.reject_conflict


def concept_rank(tag: str) -> int:
    """원시 태그의 충돌 우선순위를 반환하며 작은 값이 우선한다."""
    return _CONCEPT_RANK.get(tag, 1_000_000)
