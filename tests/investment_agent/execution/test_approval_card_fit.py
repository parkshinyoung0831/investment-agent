"""승인 카드의 주문 목록이 Discord field 한도를 넘어도 어떤 주문이 안 보이는지 알 수 있어야 한다."""
from __future__ import annotations

import unittest

from investment_agent.execution.approval.card import _FIELD_LIMIT, _fit_field


class FitFieldTest(unittest.TestCase):
    def test_a_short_list_is_shown_unchanged(self):
        lines = ["BUY  `AAPL` 1주", "SELL `MSFT` 2주"]
        self.assertEqual("\n".join(lines), _fit_field(lines))

    def test_an_overlong_list_keeps_whole_lines_and_states_how_many_are_hidden(self):
        lines = [f"BUY  `T{index:03d}` 10주 @ $123.45 ≈ $1,234.50" for index in range(60)]
        shown = _fit_field(lines)
        self.assertLessEqual(len(shown), _FIELD_LIMIT)
        body, _, tail = shown.rpartition("\n")
        kept = body.split("\n")
        self.assertEqual(lines[: len(kept)], kept, "줄 단위로 앞에서부터 담아야 한다")
        self.assertIn(f"외 {len(lines) - len(kept)}건", tail)
        self.assertLess(len(kept), len(lines))

    def test_every_line_is_either_shown_or_counted(self):
        for count in (20, 25, 26, 40, 200):
            lines = [f"SELL `T{index:03d}` 3주 @ $99.99 ≈ $299.97" for index in range(count)]
            shown = _fit_field(lines)
            self.assertLessEqual(len(shown), _FIELD_LIMIT, count)
            if len("\n".join(lines)) <= _FIELD_LIMIT:
                self.assertEqual("\n".join(lines), shown)
                continue
            body, _, tail = shown.rpartition("\n")
            hidden = int(tail.split("외 ")[1].split("건")[0])
            self.assertEqual(count, len(body.split("\n")) + hidden, count)


if __name__ == "__main__":
    unittest.main()
