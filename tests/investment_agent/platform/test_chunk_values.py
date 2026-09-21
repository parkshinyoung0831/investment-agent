"""`in` 목록 분할은 비어 있는 값만 버린다 — 0과 False 같은 값이 조용히 사라지면 그 행은 조회에서 빠진다."""
from __future__ import annotations

import unittest

from investment_agent.platform.db.postgres import chunk_values


class ChunkValuesTest(unittest.TestCase):
    def test_integer_zero_is_kept(self):
        self.assertEqual([["0", "1"]], chunk_values([1, 0]))

    def test_none_and_blank_strings_are_dropped(self):
        self.assertEqual([["A"]], chunk_values([None, "", "  ", "A"]))

    def test_values_are_deduplicated_and_sorted_before_chunking(self):
        self.assertEqual([["1", "2"], ["3"]], chunk_values([3, 1, 2, 1], size=2))


if __name__ == "__main__":
    unittest.main()
