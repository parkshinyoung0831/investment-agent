"""캡처가 실패해도 Chromium을 닫고, 임시 파일명은 프로세스와 무관하다(NT-06/PB-7)."""
from __future__ import annotations

import asyncio
import pathlib
import sys
import types
import unittest
from unittest import mock

from investment_agent.notifications import playwright as capture


class _Page:
    def __init__(self, browser) -> None:
        self._browser = browser

    async def set_content(self, *_a, **_k): ...
    async def evaluate(self, *_a, **_k): return 100
    async def set_viewport_size(self, *_a, **_k): ...

    async def screenshot(self, **kwargs):
        if self._browser.fail_screenshot:
            raise RuntimeError("boom")
        pathlib.Path(kwargs["path"]).write_bytes(b"png")


class _Context:
    def __init__(self, browser) -> None:
        self._browser = browser

    async def new_page(self): return _Page(self._browser)

    async def close(self):
        self._browser.contexts_closed += 1


class _Browser:
    def __init__(self, fail_screenshot: bool) -> None:
        self.fail_screenshot = fail_screenshot
        self.closed = False
        self.contexts_closed = 0

    def is_connected(self) -> bool:
        return not self.closed

    async def new_context(self, **_k): return _Context(self)

    async def close(self):
        self.closed = True


class _Chromium:
    def __init__(self, world) -> None:
        self._world = world

    async def launch(self):
        browser = _Browser(self._world.fail_screenshot)
        self._world.browsers.append(browser)
        return browser


class _PW:
    def __init__(self, world) -> None:
        self.chromium = _Chromium(world)

    async def start(self): return self
    async def stop(self): ...


class _World:
    """가짜 Playwright 세계. 몇 번 브라우저를 띄웠고 어떻게 닫았는지 센다."""

    def __init__(self) -> None:
        self.fail_screenshot = False
        self.browsers: list[_Browser] = []

    def modules(self):
        module = types.ModuleType("playwright.async_api")
        module.async_playwright = lambda: _PW(self)
        package = types.ModuleType("playwright")
        package.async_api = module
        return {"playwright": package, "playwright.async_api": module}


class CaptureCleanupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.world = _World()
        host = capture._BrowserHost()
        patches = (mock.patch.dict(sys.modules, self.world.modules()), mock.patch.object(capture, "_HOST", host))
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(host.close)

    def _shoot(self, html: str = "<html><head></head><body>x</body></html>") -> str:
        return asyncio.run(capture.capture_html_to_png(html, prefix="unit_test_capture"))

    def test_browser_is_closed_when_the_screenshot_fails(self) -> None:
        self.world.fail_screenshot = True
        with self.assertRaises(RuntimeError):
            self._shoot()
        self.assertTrue(self.world.browsers[0].closed, "실패한 캡처가 Chromium을 남기면 안 된다")

    def test_the_browser_is_reused_across_cards_that_each_start_their_own_event_loop(self) -> None:
        first, second = self._shoot("<html><head></head><body>a</body></html>"), self._shoot("<html><head></head><body>b</body></html>")
        self.assertEqual(1, len(self.world.browsers), "카드마다 Chromium을 새로 띄우지 않는다")
        self.assertEqual(2, self.world.browsers[0].contexts_closed, "카드마다 컨텍스트는 새로 열고 닫는다")
        for path in (first, second):
            pathlib.Path(path).unlink(missing_ok=True)

    def test_after_a_failed_capture_the_next_card_gets_a_fresh_browser(self) -> None:
        self.world.fail_screenshot = True
        with self.assertRaises(RuntimeError):
            self._shoot()
        self.world.fail_screenshot = False
        path = self._shoot("<html><head></head><body>ok</body></html>")
        self.assertEqual(2, len(self.world.browsers))
        self.assertTrue(self.world.browsers[0].closed)
        self.assertFalse(self.world.browsers[1].closed)
        pathlib.Path(path).unlink(missing_ok=True)


class PersistPngTest(unittest.TestCase):
    """dispatcher가 나중에 다시 여는 파일은 실행 폴더와 무관한 자리에 있어야 하고, 임시 캡처는 남기지 않는다."""

    def test_the_persisted_path_is_absolute_under_the_repository_and_the_temp_capture_is_removed(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as elsewhere:
            source = Path(elsewhere) / "shot.png"
            source.write_bytes(b"png")
            with mock.patch.object(capture, "repository_artifact_root", return_value=Path(elsewhere) / "artifacts"):
                target = Path(capture.persist_png(str(source), kind="unit", name="one"))
            self.assertTrue(target.is_absolute())
            self.assertEqual(b"png", target.read_bytes())
            self.assertFalse(source.exists(), "옮긴 뒤 임시 캡처는 지운다")
            self.assertEqual(Path(elsewhere) / "artifacts" / "notifications" / "unit" / "one.png", target)

    def test_font_fallback_is_injected_once(self) -> None:
        html = "<html><head></head><body></body></html>"
        font = mock.Mock(**{"as_uri.return_value": "file:///fonts/NotoSansKR-VF.ttf"})
        with mock.patch.object(capture, "_local_korean_font", return_value=font):
            once = capture.inject_windows_font_fallback(html)
            twice = capture.inject_windows_font_fallback(once)
        self.assertEqual(1, once.count("@font-face"))
        self.assertEqual(once, twice)

    def test_no_installed_font_leaves_the_html_untouched(self) -> None:
        html = "<html><head></head><body></body></html>"
        with mock.patch.object(capture, "_local_korean_font", return_value=None):
            self.assertEqual(html, capture.inject_windows_font_fallback(html))


if __name__ == "__main__":
    unittest.main()
