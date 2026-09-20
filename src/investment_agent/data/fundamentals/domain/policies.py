"""fundamentals 도메인 전체에서 공유하는 결정적 정책값."""
from __future__ import annotations

BALANCE_TOLERANCE = 0.01

# 평균 주식수가 같은 행의 보고 EPS·순이익에서 역산한 주식수와 이 배수 넘게 어긋나면
# 단위(백만·천) 오류로 본다. 실측 오류는 1,000배·1,000,000배였고, EPS가 센트로 반올림되는
# 것과 연속영업 EPS·총순이익의 차이는 한 자릿수 배수 안에서 끝나므로 두 자릿수로 잡는다.
AVERAGE_SHARES_SCALE_FACTOR = 100.0

# 어긋난 배수의 log10을 3으로 나눈 값이 정수에서 이 안에 있으면 "천·백만 단위 오류"로 본다.
# 0.05 = 배수가 1000^k의 약 0.7~1.4배 안. 실측 오류 108행이 전부 이 안에 있고, 분할 전후 값을 섞은
# 파생값(AMZN 2022-Q4 0.097, NFLX 2025-Q4 0.316)은 0.097 이상으로 떨어져 있어 폭 0.05가 둘을 가른다.
UNIT_SCALE_LOG_TOLERANCE = 0.05

# 총이익·영업이익은 정의상 매출을 넘을 수 없다. 넘는다면 매출이 총계가 아니라 하위 매출 항목이라는
# 신호다(리츠·은행에서 실측). 두 값은 서로 다른 태그에서 오고 각자 반올림되므로 0.1% 안의 어긋남은 잡음이다.
# 순이익은 비교하지 않는다 — 자산운용사·매각이익이 있는 기업은 순이익이 매출보다 클 수 있다(KKR·EMR).
PROFIT_OVER_REVENUE_TOLERANCE = 0.001

# 정의상 음수가 될 수 없는 기간 유량(매출·비용·현금 유출)이다. FY − (Q1+Q2+Q3)로 복원한 Q4가
# 음수면 산술이 아니라 두 값의 기준이 다르다는 뜻이다 — 스핀오프로 FY만 재작성되고 분기는 옛 기준인 경우
# (DLTR·DD·WDC)나 기간마다 다른 태그가 선택된 경우. 순이익·현금흐름 총계는 음수가 정상이라 넣지 않는다.
NON_NEGATIVE_FLOW_COLUMNS = frozenset({
    "revenue",
    "cost_of_goods_and_services_sold",
    "research_and_development_expenses",
    "selling_general_and_admin_expenses",
    "capital_expenses",
    "stock_repurchase_payments",
    "common_dividends_paid",
    "long_term_debt_issued",
    "long_term_debt_repaid",
})
