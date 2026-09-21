"""알림 카드 HTML -> PNG 헤드리스 브라우저 캡처 공통 유틸리티.

Playwright Chromium을 사용해 렌더링된 HTML을 2x 해상도 PNG로 캡처한다.
로컬 Windows 환경의 한글 폰트 미인식 문제를 방지하기 위해 폰트 폴백을 지원한다.
"""
from __future__ import annotations

import asyncio
import atexit
import hashlib
import os
import pathlib
import shutil
import tempfile
import threading
from typing import Any

from investment_agent.platform.logging import get_logger
from investment_agent.platform.storage_paths import repository_artifact_root

log = get_logger(__name__)

_KR_FONT_FILE = "NotoSansKR-VF.ttf"
_FONT_FAMILY = "Card Noto Sans KR"


def _local_korean_font() -> pathlib.Path | None:
    """이 컴퓨터에 설치된 Noto Sans KR 파일. Windows·macOS 로컬에서만 찾고, Actions는 fonts-noto-cjk를 쓴다."""
    directories = (
        pathlib.Path("C:/Windows/Fonts"),
        pathlib.Path.home() / "Library" / "Fonts",
        pathlib.Path("/Library/Fonts"),
    )
    for directory in directories:
        candidate = directory / _KR_FONT_FILE
        if candidate.is_file():
            return candidate
    return None


def inject_windows_font_fallback(html: str) -> str:
    """로컬 환경에서 한글 폰트 누락을 방지하기 위한 @font-face를 주입한다. 이미 주입했으면 그대로 둔다."""
    if _FONT_FAMILY in html or "</head>" not in html:
        return html
    font = _local_korean_font()
    if font is None:
        return html
    font_face = (
        f'<style>@font-face{{font-family:"{_FONT_FAMILY}";'
        f'src:url("{font.as_uri()}") format("truetype");'
        'font-weight:100 900;font-style:normal}'
        f'body{{font-family:"{_FONT_FAMILY}",Inter,"Noto Sans KR",system-ui,sans-serif}}</style>'
    )
    return html.replace("</head>", f"{font_face}</head>", 1)


class _BrowserHost:
    """프로세스 동안 Chromium 하나를 재사용한다.

    카드마다 `asyncio.run`으로 새 이벤트 루프를 만들어도 브라우저는 그 루프에 묶이지 않도록, Playwright와 브라우저는
    항상 이 전용 스레드의 루프에서만 만들고 쓴다. 호출 쪽 루프는 결과만 기다린다. 카드마다 새 컨텍스트를 쓰므로
    카드끼리 쿠키·상태를 공유하지 않고, 캡처가 어떤 이유로든 실패하면 브라우저 상태를 알 수 없어 버리고 다음
    카드가 새로 띄운다(장당 약 0.55초 절감 vs 실패가 다음 카드로 번지지 않게 하는 격리).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._playwright: Any = None
        self._browser: Any = None
        self._is_exit_registered = False

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None or self._thread is None or not self._thread.is_alive():
                loop = asyncio.new_event_loop()
                thread = threading.Thread(target=loop.run_forever, name="playwright-host", daemon=True)
                thread.start()
                self._loop, self._thread = loop, thread
            if not self._is_exit_registered:
                atexit.register(self.close)
                self._is_exit_registered = True
            return self._loop

    async def _browser_instance(self) -> Any:
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        await self._discard()
        from playwright.async_api import async_playwright  # 무거운 의존성 — 캡처 시점에만 지연 import

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch()
        return self._browser

    async def _discard(self) -> None:
        browser, playwright = self._browser, self._playwright
        self._browser = self._playwright = None
        if browser is not None:
            try:
                await browser.close()
            except Exception:  # noqa: BLE001 - 이미 죽은 브라우저를 닫다 나는 오류가 다음 카드를 막으면 안 된다
                log.warning("chromium close failed", exc_info=True)
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:  # noqa: BLE001
                log.warning("playwright stop failed", exc_info=True)

    async def _shoot(self, html: str, out: pathlib.Path, viewport_width: int) -> None:
        browser = await self._browser_instance()
        try:
            ctx = await browser.new_context(
                viewport={"width": viewport_width, "height": 100},
                device_scale_factor=2,  # 2x 해상도로 선명하게 렌더
            )
            try:
                page = await ctx.new_page()
                await page.set_content(html, wait_until="networkidle")
                try:
                    await page.evaluate("document.fonts.ready")
                except Exception:  # noqa: BLE001 - 폰트 대기 실패는 캡처를 막지 않는다
                    pass
                height = await page.evaluate("document.documentElement.scrollHeight")
                await page.set_viewport_size({"width": viewport_width, "height": int(height)})
                await page.screenshot(path=str(out), full_page=True)
            finally:
                await ctx.close()
        except BaseException:
            await self._discard()  # 캡처가 실패하면 Chromium 프로세스를 남기지 않고 다음 카드가 새로 띄운다
            raise

    async def shoot(self, html: str, out: pathlib.Path, viewport_width: int) -> None:
        future = asyncio.run_coroutine_threadsafe(self._shoot(html, out, viewport_width), self._ensure_loop())
        await asyncio.wrap_future(future)

    def close(self) -> None:
        """프로세스 종료 때 브라우저를 닫는다."""
        loop, thread = self._loop, self._thread
        if loop is None or thread is None or loop.is_closed() or not thread.is_alive():
            return
        try:
            asyncio.run_coroutine_threadsafe(self._discard(), loop).result(timeout=15)
        except Exception:  # noqa: BLE001 - 종료 중의 정리 실패는 알림 결과를 가리지 않는다
            log.warning("chromium shutdown failed", exc_info=True)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)


_HOST = _BrowserHost()


async def capture_html_to_png(
    html: str,
    *,
    viewport_width: int = 1080,
    prefix: str = "notify",
) -> str:
    """HTML 문자열을 헤드리스 브라우저로 렌더링해 임시 PNG 파일로 저장하고 경로를 반환한다."""
    prepared_html = inject_windows_font_fallback(html)
    # `hash()`는 프로세스마다 시드가 달라, 같은 카드를 다시 만들어도 같은 파일을 덮어쓰지 못한다.
    digest = hashlib.sha256(html.encode("utf-8")).hexdigest()[:16]
    out = pathlib.Path(tempfile.gettempdir()) / f"{prefix}_{digest}.png"
    await _HOST.shoot(prepared_html, out, viewport_width)
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
    # 실행 폴더가 저장소 루트가 아니어도 dispatcher가 같은 파일을 다시 열 수 있게 절대 경로로 둔다.
    target = repository_artifact_root() / "notifications" / kind / f"{name}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    if source.resolve() != target.resolve():
        source.unlink(missing_ok=True)  # 임시 캡처가 %TEMP%에 쌓이지 않게 옮긴 뒤 지운다
    return str(target)
