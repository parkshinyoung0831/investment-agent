"""기관 보유 신고(13F).

정정에는 **전체 재신고**와 **누락 추가** 두 종류가 있고 처리가 정반대다. 그 구분은
`holdings.effective_filings`가 한 곳에서 한다 — 각자 판단하면 한쪽은 두 배로 세고
다른 쪽은 절반을 잃는다.
"""
from __future__ import annotations

import os

POLL_WINDOW_DAYS = int(os.environ.get("GURUS_POLL_WINDOW_DAYS", "7"))
HISTORICAL_START_DATE = os.environ.get("GURUS_HISTORICAL_START_DATE", "2014-01-01")
