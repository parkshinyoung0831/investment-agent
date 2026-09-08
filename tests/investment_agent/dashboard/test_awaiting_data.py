"""빈 화면이 고장인지 데이터가 없는 건지 구분되게 한다.

지금까지는 그냥 비어 있어서, 코드가 죽은 것(호출자 0)과 아직 안 쌓인 것을
화면만 보고는 구분할 수 없었다.
"""
from __future__ import annotations

import unittest

from investment_agent.dashboard.components.ui import awaiting_message


class AwaitingMessageTest(unittest.TestCase):
    def test_message_names_what_is_missing_and_when_it_fills(self):
        text = awaiting_message(
            "판단 기록",
            reason="아직 저장된 판단이 없어요",
            fills_when="하네스가 분석을 한 번 끝내면 채워져요",
        )

        self.assertIn("판단 기록", text)
        self.assertIn("아직 저장된 판단이 없어요", text)
        self.assertIn("하네스가 분석을 한 번 끝내면 채워져요", text)

    def test_it_never_reads_like_an_error(self):
        text = awaiting_message("x", reason="비었어요", fills_when="곧 채워져요")

        for scary in ("오류", "실패", "에러", "Error"):
            self.assertNotIn(scary, text)

    def test_blank_reason_is_rejected_rather_than_shown_empty(self):
        with self.assertRaises(ValueError):
            awaiting_message("x", reason="  ", fills_when="곧")

    def test_blank_fill_condition_is_rejected(self):
        with self.assertRaises(ValueError):
            awaiting_message("x", reason="비었어요", fills_when="")


if __name__ == "__main__":
    unittest.main()
