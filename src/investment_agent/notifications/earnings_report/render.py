"""실적 카드 렌더 — HTML 템플릿 채우기 + 헤드리스 브라우저로 PNG 캡처.

macro/render.py와 같은 경로지만 펀더멘탈 전용 templates/를 바라본다. 각 알림 패키지가
자기 렌더와 templates/를 소유한다. Jinja2로 HTML을 채우고 Playwright로 화면을 캡처한다.
"""
from __future__ import annotations

import pathlib
from typing import Any

import jinja2

from investment_agent.platform.logging import get_logger
from investment_agent.notifications.playwright import capture_html_to_png, inject_windows_font_fallback

log = get_logger(__name__)

ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(pathlib.Path(__file__).parent / "templates")),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(template_name: str, ctx: dict[str, Any]) -> str:
    """펀더멘탈 템플릿에 ctx를 채워 HTML 문자열을 반환."""
    html = ENV.get_template(template_name).render(**ctx)
    return inject_windows_font_fallback(html)


async def shoot_png(html: str, *, viewport_width: int = 1080) -> str:
    """HTML을 브라우저로 열어 PNG로 캡처하고 파일 경로를 반환."""
    return await capture_html_to_png(html, viewport_width=viewport_width, prefix="notify_fund")
