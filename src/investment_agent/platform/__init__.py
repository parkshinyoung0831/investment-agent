"""기술 공통 코드만 두는 자리.

여기에 **도메인 규칙을 넣지 않는다** — SEC 공시 규칙, ticker 정규화, 재무 계산,
Toss 인증은 전부 자기 도메인 패키지에 있어야 한다.

기준은 간단하다. *"투자와 무관한 다른 프로젝트에 그대로 복사해도 말이 되는가."*
말이 되면 platform, 아니면 도메인이다.

이 패키지도 import 부작용이 없다. 설정은 `investment_agent.config.load_config()`가
진입점에서 한 번 읽고, 필요한 곳에 **인자로** 건넨다.
"""
from __future__ import annotations
