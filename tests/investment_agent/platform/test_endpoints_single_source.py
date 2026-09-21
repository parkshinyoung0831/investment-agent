"""외부 provider 기준 주소는 `platform/endpoints.py` 한 곳에만 적는다(HC-9).

모듈마다 다시 적으면 API 버전을 올릴 때 일부만 고쳐져 어떤 경로는 옛 버전으로 조용히 계속 돈다.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from investment_agent.platform import endpoints

SRC = Path(__file__).resolve().parents[3] / "src" / "investment_agent"
ENDPOINTS_FILE = SRC / "platform" / "endpoints.py"


def _declared() -> dict[str, str]:
    return {name: value for name, value in vars(endpoints).items() if name.isupper() and isinstance(value, str)}


class EndpointsSingleSourceTest(unittest.TestCase):
    def test_no_module_restates_a_declared_address(self) -> None:
        offenders: list[str] = []
        for path in sorted(SRC.rglob("*.py")):
            if path == ENDPOINTS_FILE:
                continue
            text = path.read_text(encoding="utf-8")
            for name, value in _declared().items():
                for match in re.finditer(re.escape(value), text):
                    line = text.count("\n", 0, match.start()) + 1
                    offenders.append(f"{path.relative_to(SRC).as_posix()}:{line} {name}")
        self.assertEqual([], offenders)

    def test_declared_addresses_are_https_and_unique(self) -> None:
        values = list(_declared().values())
        self.assertTrue(values)
        self.assertEqual(len(values), len(set(values)))
        for value in values:
            self.assertTrue(value.startswith("https://"), value)


if __name__ == "__main__":
    unittest.main()
