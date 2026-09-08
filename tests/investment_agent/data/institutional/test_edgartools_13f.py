"""edgartools shadow 파서 wrapper와 운영 파서의 결과 일치(parity) 테스트.

edgartools가 설치되어 있지 않으면 wrapper는 EdgartoolsUnavailable을 던지므로
해당 테스트는 skip한다(선택 의존성).
"""
from __future__ import annotations

import builtins
import unittest
from pathlib import Path
from unittest import mock

from investment_agent.data.institutional.domain import shadow_diff
from investment_agent.data.institutional.infrastructure.sources import edgartools_13f
from investment_agent.data.institutional.domain.parser import parse_information_table

_FIXTURES = Path(__file__).parent / "fixtures"


import importlib.util

def _edgartools_installed() -> bool:
    return importlib.util.find_spec("edgar") is not None


@unittest.skipUnless(_edgartools_installed(), "edgartools not installed")
class EdgartoolsWrapperTest(unittest.TestCase):
    def setUp(self):
        self.xml = (_FIXTURES / "infotable_basic.xml").read_text(encoding="utf-8")

    def test_maps_columns_to_raw_positions(self):
        rows = edgartools_13f.parse_information_table(self.xml, source_format="xml")
        self.assertEqual(len(rows), 3)
        by_cusip = {r.cusip: r for r in rows}

        apple = by_cusip["037833100"]
        self.assertEqual(apple.reported_value, 123456)  # 원본(미환산) 값 유지
        self.assertEqual(apple.quantity, 1000)
        self.assertEqual(apple.quantity_type, "SH")
        self.assertEqual(apple.position_kind, "SHARES")

        msft = by_cusip["594918104"]
        self.assertEqual(msft.position_kind, "PUT")  # putCall=Put → PUT

        note = by_cusip["11111111A"]
        self.assertEqual(note.quantity_type, "PRN")  # Type=Principal → PRN

    def test_parity_with_custom_parser(self):
        custom = parse_information_table(self.xml)
        shadow = edgartools_13f.parse_information_table(self.xml, source_format="xml")
        diff = shadow_diff.compare("acc-parity", custom, shadow)
        self.assertTrue(diff.matched, msg=diff.reason())

    def test_unsupported_format_rejected(self):
        with self.assertRaises(ValueError):
            edgartools_13f.parse_information_table(self.xml, source_format="pdf")


class WrapperUnavailableTest(unittest.TestCase):
    """edgartools 미설치/지연 import 경로. 설치 여부와 무관하게 동작해야 한다."""

    def test_version_helper_returns_str_or_none(self):
        value = edgartools_13f.edgartools_version()
        self.assertTrue(value is None or isinstance(value, str))

    def test_import_failure_raises_edgartools_unavailable(self):
        # edgar.thirteenf import가 실패하면 EdgartoolsUnavailable로 변환되어
        # ETL이 shadow 대조만 건너뛸 수 있어야 한다(설치돼 있어도 강제 실패시킴).
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "edgar.thirteenf" or name.startswith("edgar."):
                raise ImportError("forced: edgartools missing")
            return real_import(name, *args, **kwargs)

        with mock.patch.object(builtins, "__import__", side_effect=fake_import):
            with self.assertRaises(edgartools_13f.EdgartoolsUnavailable):
                edgartools_13f.parse_information_table(
                    "<informationTable/>", source_format="xml"
                )


class WrapperNormalizerTest(unittest.TestCase):
    """edgartools 출력 컬럼을 운영 모델로 정규화하는 순수 헬퍼. 의존성 불필요."""

    def test_quantity_type_normalizes(self):
        self.assertEqual(edgartools_13f._quantity_type("Shares"), "SH")
        self.assertEqual(edgartools_13f._quantity_type("PRN"), "PRN")
        self.assertEqual(edgartools_13f._quantity_type("Principal"), "PRN")
        with self.assertRaises(ValueError):
            edgartools_13f._quantity_type("BONDS")

    def test_position_kind_normalizes(self):
        self.assertEqual(edgartools_13f._position_kind(""), "SHARES")
        self.assertEqual(edgartools_13f._position_kind("Put"), "PUT")
        self.assertEqual(edgartools_13f._position_kind("call"), "CALL")
        with self.assertRaises(ValueError):
            edgartools_13f._position_kind("SWAP")

    def test_to_int_coerces_and_rejects(self):
        self.assertEqual(edgartools_13f._to_int("123.0", "Value"), 123)
        self.assertEqual(edgartools_13f._to_int("", "Value"), 0)
        self.assertEqual(edgartools_13f._to_int("nan", "Value"), 0)
        with self.assertRaises(ValueError):
            edgartools_13f._to_int("abc", "Value")


if __name__ == "__main__":
    unittest.main()
