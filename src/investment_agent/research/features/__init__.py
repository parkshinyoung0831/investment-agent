"""일간 기술지표 ETL과 PIT feature layer (RSI·MACD → local ResearchStore).

시세 입력은 v1 market, 산출물은 Research 전용 local DuckDB다. 외부 API는 호출하지
않으며, 모델 feature는 고정 컬럼·결측 표식·feature version 계약을 따른다.
"""
from __future__ import annotations

# 일간 기술지표 ETL 파라미터.
RSI_LENGTH = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# 저장 구간 앞에 긴 고정 warmup을 두어 재귀 EMA seed가 저장값의 수치 정밀도에
# 영향을 주지 않게 한다. 약 3년(750 거래일)이면 Wilder(14)의 잔여 seed 영향도
# double precision보다 작다.
STORAGE_DAYS = 730
BACKFILL_WARMUP_TRADING_DAYS = 750
ROLLING_DAYS = STORAGE_DAYS * 252 // 365 + BACKFILL_WARMUP_TRADING_DAYS

# PIT feature layer contracts share this package with the local ETL helpers.
from investment_agent.research.features.layer import (
    FEATURE_VERSION,
    REQUIRED_BARS,
    FeatureBundle,
    FeatureLayer,
)
from investment_agent.research.contracts import FeatureRecord
from investment_agent.research.rl.contracts import FeatureSnapshot

__all__ = [
    "BACKFILL_WARMUP_TRADING_DAYS",
    "BACKFILL_YEARS",
    "FEATURE_VERSION",
    "FeatureBundle",
    "FeatureLayer",
    "FeatureRecord",
    "FeatureSnapshot",
    "MACD_FAST",
    "MACD_SIGNAL",
    "MACD_SLOW",
    "REQUIRED_BARS",
    "ROLLING_DAYS",
    "RSI_LENGTH",
    "STORAGE_DAYS",
]

# 기본 백필 시작일 계산용 기간. 실제 계산에는 위 고정 워밍업을 함께 사용한다.
BACKFILL_YEARS = 2
# 한 요청이 과도하게 커지지 않으면서 HTTP 왕복을 줄이는 원자 UPSERT 크기.
_UPSERT_BATCH = 5000
