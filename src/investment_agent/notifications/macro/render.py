"""매크로 카드 렌더 — HTML 템플릿 채우기 + 헤드리스 브라우저로 PNG 캡처.

매크로 코어 알림 전용 렌더 경로다. 전략 알림은 Discord 임베드 +
QuickChart URL을 쓰므로 이 모듈을 쓰지 않는다. macro 코어의 HTML 렌더는
macro 패키지가 자체 render.py로 소유한다.
- Jinja2     : HTML 템플릿에 값 채우기 (ENV·render)
- Playwright : 헤드리스 브라우저로 화면 캡처 (shoot_png)
"""
from __future__ import annotations
import pathlib
from typing import Any

import jinja2

from investment_agent.reporting.services.macro.palette import TOKENS

from investment_agent.notifications.playwright import capture_html_to_png
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

# templates/ 폴더를 바라보는 Jinja2 환경 (모듈 로드 시 1회 생성).
ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(pathlib.Path(__file__).parent / "templates")),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)
ENV.globals["tokens"] = TOKENS


def render(template_name: str, ctx: dict[str, Any]) -> str:
    """매크로 템플릿에 ctx를 채워 HTML 문자열을 반환."""
    return ENV.get_template(template_name).render(**ctx)


async def shoot_png(html: str, *, viewport_width: int = 1080) -> str:
    """HTML을 브라우저로 열어 PNG로 캡처하고 파일 경로를 반환."""
    return await capture_html_to_png(html, viewport_width=viewport_width, prefix="notify_macro")
