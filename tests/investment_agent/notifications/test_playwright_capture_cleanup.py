"""캡처가 실패해도 Chromium을 닫고, 임시 파일명은 프로세스와 무관하다(NT-06/PB-7)."""
from __future__ import annotations

import asyncio
import sys
import types
import unittest
from unittest import mock

from investment_agent.notifications import playwright as capture


class _Page:
    async def set_content(self, *_a, **_k): ...
    async def evaluate(self, *_a, **_k): return 100
    async def set_viewport_size(self, *_a, **_k): ...
    async def screenshot(self, **_k): raise RuntimeError("boom")


class _Context:
    async def new_page(self): return _Page()


class _Browser:
    closed = False

    async def new_context(self, **_k): return _Context()

    async def close(self):
        _Browser.closed = True


class _Chromium:
    async def launch(self): return _Browser()


class _PW:
    chromium = _Chromium()

    async def __aenter__(self): return self
    async def __aexit__(self, *_a): return False


def _fake_module():
    module = types.ModuleType("playwright.async_api")
    module.async_playwright = lambda: _PW()
    package = types.ModuleType("playwright")
    package.async_api = module
    return {"playwright": package, "playwright.async_api": module}


class CaptureCleanupTest(unittest.TestCase):
    def test_browser_is_closed_when_the_screenshot_fails(self) -> None:
        _Browser.closed = False
        with mock.patch.dict(sys.modules, _fake_module()):
            with self.assertRaises(RuntimeError):
                asyncio.run(capture.capture_html_to_png("<html><head></head></html>"))
        self.assertTrue(_Browser.closed)


if __name__ == "__main__":
    unittest.main()
