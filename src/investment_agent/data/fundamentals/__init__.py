"""SEC 공시에서 나온 재무 사실.

**정정이 원본을 지우지 않는다.** 같은 기간에 원본과 정정이 나란히 남고, 무엇이
"그 시점의 최신"인지는 저장이 아니라 조회가 정한다(`versions`).
"""
from __future__ import annotations

BACKFILL_YEARS = 10
