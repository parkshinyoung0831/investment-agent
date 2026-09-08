"""SEC 원본의 이상값은 그 행만 버린다 — 그 기업 전체를 버리지 않는다.

발행주식수는 시가총액과 주당 지표의 분모다. 틀린 값을 담느니 없는 게 낫다는 판단은
맞다. 다만 그 판단이 "전부 아니면 전무"일 이유는 없다 — 전에는 이상값이 하나라도
있으면 그 CIK 전체를 거절했고, 실측으로 **17개사의 발행주식수가 통째로 비었다.**

기준값을 자리표시자를 뺀 뒤 계산하는 것이 핵심이다. 그러지 않으면 자리표시자가
기준이 되어 **진짜 값이 이상값으로 걸린다** — 실제로 그런 CIK가 있었다.
"""
from __future__ import annotations

import unittest

from investment_agent.data.fundamentals.domain.services.parse_shares import (
    drop_implausible_share_rows,
)


def _row(value: int, index: int, class_key: str = "common") -> dict:
    return {
        "cik": "0000000001", "share_class_key": class_key,
        "as_of_date": f"2024-01-{index:02d}", "accession_no": f"a-{index}",
        "shares_outstanding": value,
    }


def _values(rows: list[dict]) -> list[int]:
    return [int(row["shares_outstanding"]) for row in rows]


class DropImplausibleSharesTest(unittest.TestCase):
    def test_a_placeholder_never_becomes_the_benchmark(self) -> None:
        """실측: benchmark=1,000 대 실제 1,071,666,977 — 진짜 값이 걸렸었다."""
        keep, dropped = drop_implausible_share_rows([_row(1_000, 1), _row(1_071_666_977, 2)])
        self.assertEqual([1_071_666_977], _values(keep))
        self.assertEqual([1_000], _values(dropped))

    def test_a_thousandfold_scale_error_is_dropped(self) -> None:
        keep, dropped = drop_implausible_share_rows([
            _row(94_348_252, 1), _row(94_000_000, 2), _row(93_000_000, 3),
            _row(89_932_185_000, 4),
        ])
        self.assertEqual(3, len(keep))
        self.assertEqual([89_932_185_000], _values(dropped))

    def test_repeated_placeholders_are_dropped_not_the_real_values(self) -> None:
        keep, dropped = drop_implausible_share_rows([
            _row(1_193_640_825, 1), _row(1_190_000_000, 2), _row(100, 3), _row(100, 4),
        ])
        self.assertEqual([1_190_000_000, 1_193_640_825], sorted(_values(keep)))
        self.assertEqual([100, 100], _values(dropped))

    def test_a_clean_series_loses_nothing(self) -> None:
        rows = [_row(100_000_000 + index, index) for index in range(1, 6)]
        keep, dropped = drop_implausible_share_rows(rows)
        self.assertEqual(len(rows), len(keep))
        self.assertEqual([], dropped)

    def test_classes_are_judged_separately(self) -> None:
        """클래스 B가 A보다 훨씬 작은 것은 정상이다 — 섞어 재면 B가 이상값이 된다."""
        rows = [
            _row(1_000_000_000, 1, "commonclassa"), _row(1_010_000_000, 2, "commonclassa"),
            _row(2_000_000, 3, "commonclassb"), _row(2_010_000, 4, "commonclassb"),
        ]
        keep, dropped = drop_implausible_share_rows(rows)
        self.assertEqual(4, len(keep))
        self.assertEqual([], dropped)

    def test_a_class_that_is_only_placeholders_keeps_nothing(self) -> None:
        """전부 자리표시자면 그 클래스에 대해 아는 것이 없다 — 지어내지 않는다."""
        keep, dropped = drop_implausible_share_rows([_row(100, 1), _row(100, 2)])
        self.assertEqual([], keep)
        self.assertEqual(2, len(dropped))


if __name__ == "__main__":
    unittest.main()
