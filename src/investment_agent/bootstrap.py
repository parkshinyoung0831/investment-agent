"""프로세스로 시작한 CLI만 거치는 자리.

여기서 두 가지를 한다 — 로컬 `.env`를 읽는 것과, 루트 로거를 JSON 한 줄로 맞추는
것. 뒤엣것이 빠지면 `logging`의 lastResort 처리기가 WARNING 위만 stderr로 흘리고
**INFO는 조용히 버린다**. 진행·결과 줄이 전부 INFO라서, 수천 행을 적재한 잡이
아무 일도 안 한 것처럼 보인다(13F 백필이 4,927행을 넣고 빈 로그를 남겼다).

라이브러리 경로에서는 부르지 않는다. `main()`을 직접 부르는 쪽의 로깅 설정까지
빼앗기 때문이다 — 그래서 `__main__` 블록에만 둔다.
"""
from __future__ import annotations

from investment_agent.platform.storage_paths import repository_root


def start_cli() -> None:
    """프로세스 진입점 준비. `__main__` 블록에서만 부른다."""
    from dotenv import load_dotenv

    from investment_agent.platform.logging import configure_logging

    load_dotenv(repository_root() / ".env", override=False)
    configure_logging()


__all__ = ["start_cli"]
