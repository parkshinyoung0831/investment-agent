"""전역 거래 스위치 두 개를 읽는 규칙의 유일한 자리.

실주문 게이트(`execution/safety/control.py`), 하네스 stage 게이트, 안전 점검, 대시보드가 같은 환경변수를
각자 다른 낱말 집합으로 읽으면 화면은 "OFF"라 하는데 게이트는 막혀 있는 일이 생긴다. 모두 이 규칙을 쓴다.

* `TRADING_KILL_SWITCH`는 정확히 `off`여야 풀린다. 없거나 빈 값이거나 오타면 **켜진 것**이다.
* `TOSS_LIVE_ENABLED`는 정확히 `true`여야 켜진다. 없거나 `1`·`yes`·오타면 꺼진 것이다.

두 방향이 반대인 것은 의도다. 둘 다 "모르겠으면 주문하지 않는" 쪽으로 읽힌다. 코드가 이 값을 쓰지 않는다.
"""
from __future__ import annotations

KILL_SWITCH_FLAG = "TRADING_KILL_SWITCH"
LIVE_FLAG = "TOSS_LIVE_ENABLED"


def kill_switch_on(raw: str | None) -> bool:
    return (raw or "on").strip().lower() != "off"


def live_enabled(raw: str | None) -> bool:
    return (raw or "false").strip().lower() == "true"
