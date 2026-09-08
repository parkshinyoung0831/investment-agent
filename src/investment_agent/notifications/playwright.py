"""알림 카드 HTML -> PNG 헤드리스 브라우저 캡처 공통 유틸리티.

Playwright Chromium을 사용해 렌더링된 HTML을 2x 해상도 PNG로 캡처한다.
로컬 Windows 환경의 한글 폰트 미인식 문제를 방지하기 위해 폰트 폴백을 지원한다.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import tempfile

from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

_WINDOWS_KR_FONT = pathlib.Path(r"C:\Windows\Fonts\NotoSansKR-VF.ttf")


def inject_windows_font_fallback(html: str) -> str:
    """Windows 로컬 환경에서 한글 폰트 누락을 방지하기 위한 @font-face를 주입한다."""
    if _WINDOWS_KR_FONT.exists() and "</head>" in html:
        font_face = (
            '<style>@font-face{font-family:"Card Noto Sans KR";'
            'src:url("file:///C:/Windows/Fonts/NotoSansKR-VF.ttf") format("truetype");'
            'font-weight:100 900;font-style:normal}'
            'body{font-family:"Card Noto Sans KR",Inter,"Noto Sans KR",system-ui,sans-serif}</style>'
        )
        return html.replace("</head>", f"{font_face}</head>", 1)
    return html


async def capture_html_to_png(
    html: str,
    *,
    viewport_width: int = 1080,
    prefix: str = "notify",
) -> str:
    """HTML 문자열을 헤드리스 브라우저로 렌더링해 임시 PNG 파일로 저장하고 경로를 반환한다."""
    from playwright.async_api import async_playwright  # 무거운 의존성 — 캡처 시점에만 지연 import

    prepared_html = inject_windows_font_fallback(html)
    out = pathlib.Path(tempfile.gettempdir()) / f"{prefix}_{abs(hash(html)) % 10**8}.png"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(
            viewport={"width": viewport_width, "height": 100},
            device_scale_factor=2,  # 2x 해상도로 선명하게 렌더
        )
        page = await ctx.new_page()
        await page.set_content(prepared_html, wait_until="networkidle")
        try:
            await page.evaluate("document.fonts.ready")
        except Exception:
            pass
        height = await page.evaluate("document.documentElement.scrollHeight")
        await page.set_viewport_size({"width": viewport_width, "height": int(height)})
        await page.screenshot(path=str(out), full_page=True)
        await browser.close()

    log.info("png shot: %s (%d bytes)", out, out.stat().st_size)
    return str(out)


def persist_png(png_path: str, *, kind: str, name: str) -> str:
    """임시 캡처를 dispatcher가 다시 열 수 있는 안정적인 경로로 옮긴다.

    dispatch는 enqueue보다 나중이고, 재시도는 그보다도 더 나중이다 — 그 사이에
    OS가 임시 디렉터리를 비우면 첨부가 사라진다. 옮길 때 `.tmp`를 거쳐 `os.replace`로
    바꾸는 것은 같은 카드를 다시 만들 때 dispatcher가 반쯤 쓰인 파일을 열지 않게 하기
    위해서다(같은 경로를 덮어쓴다).
    """
    source = pathlib.Path(png_path)
    if not source.is_file():
        raise FileNotFoundError(png_path)
    target = pathlib.Path("artifacts") / "notifications" / kind / f"{name}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return str(target)
