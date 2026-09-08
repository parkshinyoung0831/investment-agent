"""macro: 매크로 시장 지표 알림 묶음 (core·watch).

데이터 조회와 outbox 선점은 이 패키지의 `core.py`·`watch.py`가 담당한다.
공용 계약: investment_agent.reporting.services.macro — 계산·판정·표현 SSOT
표시:     render.py    — HTML 렌더
알림:     core.py(매일) · watch.py(평일 매시) — 각각 run() 하나만 노출
진입점(__main__)이 --kind로 run()을 골라 실행한다. 발송 도구는 notifications.channels에 있다.
"""
from __future__ import annotations
