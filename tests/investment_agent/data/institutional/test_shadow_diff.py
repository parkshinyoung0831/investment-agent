"""shadow 대조 로직(shadow_diff.compare) 단위 테스트. 외부 의존성 없음."""
from __future__ import annotations

import unittest

from investment_agent.data.institutional.domain import shadow_diff
from investment_agent.data.institutional.domain.models import RawPosition


def _row(cusip, value, qty, qtype="SH", kind="SHARES", issuer="X"):
    return RawPosition(
        issuer_name=issuer,
        cusip=cusip,
        reported_value=value,
        quantity=qty,
        quantity_type=qtype,
        position_kind=kind,
    )


class CompareTest(unittest.TestCase):
    def test_identical_rows_match(self):
        rows = [_row("037833100", 100, 10), _row("594918104", 50, 5, kind="PUT")]
        diff = shadow_diff.compare("acc", rows, list(rows))
        self.assertTrue(diff.matched)
        self.assertIsNone(diff.reason())

    def test_order_independent_match(self):
        a = [_row("037833100", 100, 10), _row("594918104", 50, 5)]
        b = [_row("594918104", 50, 5), _row("037833100", 100, 10)]
        self.assertTrue(shadow_diff.compare("acc", a, b).matched)

    def test_aggregates_duplicate_keys(self):
        # 같은 분석 키가 여러 행으로 쪼개져도(예: OtherManager 분할) 키별 합계가
        # 같으면 일치로 본다. 단, 라인 수는 원본 행 기준이라 양쪽 행 수가 같아야 한다.
        custom = [_row("037833100", 60, 6), _row("037833100", 40, 4)]
        shadow = [_row("037833100", 40, 4), _row("037833100", 60, 6)]
        self.assertTrue(shadow_diff.compare("acc", custom, shadow).matched)

    def test_same_totals_but_different_line_count_flagged(self):
        # 키별 합계는 같지만 원본 행 수가 다르면 line_count 불일치로 잡는다.
        custom = [_row("037833100", 60, 6), _row("037833100", 40, 4)]
        shadow = [_row("037833100", 100, 10)]
        diff = shadow_diff.compare("acc", custom, shadow)
        self.assertFalse(diff.matched)
        self.assertIn("line_count", diff.reason())

    def test_line_count_mismatch(self):
        custom = [_row("037833100", 100, 10)]
        shadow = [_row("037833100", 100, 10), _row("594918104", 50, 5)]
        diff = shadow_diff.compare("acc", custom, shadow)
        self.assertFalse(diff.matched)
        self.assertIn("line_count", diff.reason())
        self.assertEqual(diff.only_in_shadow, (("594918104", "SHARES", "SH"),))

    def test_value_total_mismatch(self):
        custom = [_row("037833100", 100, 10)]
        shadow = [_row("037833100", 999, 10)]
        diff = shadow_diff.compare("acc", custom, shadow)
        self.assertFalse(diff.matched)
        self.assertIn("value_total", diff.reason())
        self.assertEqual(len(diff.key_mismatches), 1)

    def test_quantity_mismatch_same_value(self):
        custom = [_row("037833100", 100, 10)]
        shadow = [_row("037833100", 100, 11)]
        diff = shadow_diff.compare("acc", custom, shadow)
        self.assertFalse(diff.matched)
        self.assertEqual(len(diff.key_mismatches), 1)

    def test_put_call_distinguishes_keys(self):
        custom = [_row("037833100", 100, 10, kind="SHARES")]
        shadow = [_row("037833100", 100, 10, kind="PUT")]
        diff = shadow_diff.compare("acc", custom, shadow)
        self.assertFalse(diff.matched)
        self.assertTrue(diff.only_in_custom and diff.only_in_shadow)

    def test_value_tolerance_one(self):
        # 키별·총합 모두 ±1까지는 일치로 본다(정수 반올림 여유).
        custom = [_row("037833100", 100, 10)]
        shadow = [_row("037833100", 101, 10)]
        self.assertTrue(shadow_diff.compare("acc", custom, shadow).matched)

    def test_errored_diff(self):
        rows = [_row("037833100", 100, 10)]
        diff = shadow_diff.errored("acc", rows, "boom")
        self.assertFalse(diff.matched)
        self.assertIn("boom", diff.reason())
        self.assertEqual(diff.custom_line_count, 1)

    def test_payload_is_json_serializable(self):
        import json

        custom = [_row("037833100", 100, 10)]
        shadow = [_row("594918104", 50, 5)]
        payload = shadow_diff.compare("acc", custom, shadow).as_payload()
        json.dumps(payload)  # JSON 로그 metrics에 실을 수 있어야 한다.


if __name__ == "__main__":
    unittest.main()
