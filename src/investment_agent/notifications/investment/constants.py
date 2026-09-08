"""자동매매 알림이 공유하는 고정값."""
from __future__ import annotations

# notifications.outbox를 macro·macro releases·gurus와 나눠 쓰는 구분자.
PIPELINE = "ai_investor"
# 하루에 보낼 종목 심층 카드 수의 기본값. 전 종목을 보내면 읽히지 않는다.
DEFAULT_TOP_N = 5
# 체결 보고에서 되돌아볼 시간. 하네스는 분 단위로 돌지만 안전망은 하루 한 번이다.
DEFAULT_TRADE_LOOKBACK_HOURS = 26

__all__ = ["DEFAULT_TOP_N", "DEFAULT_TRADE_LOOKBACK_HOURS", "PIPELINE"]
