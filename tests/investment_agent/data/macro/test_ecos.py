"""ECOS 클라이언트가 전체 행과 통계 계약을 보존하는지 검증한다."""
from __future__ import annotations

from datetime import date
import unittest
from unittest import mock

from investment_agent.data.macro.infrastructure.sources import ecos


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


def _payload(rows: list[dict], total: int) -> dict:
    return {"StatisticSearch": {"list_total_count": total, "row": rows}}


def _row(day: str, value: str, *, name: str = "원/일본엔(100엔)") -> dict:
    return {
        "STAT_CODE": "731Y001",
        "ITEM_CODE1": "0000002",
        "ITEM_NAME1": name,
        "UNIT_NAME": "원",
        "TIME": day,
        "DATA_VALUE": value,
    }


class EcosClientTest(unittest.TestCase):
    @mock.patch.dict("os.environ", {"ECOS_API_KEY": "test-key"})
    @mock.patch.object(ecos, "_PAGE_SIZE", 2)
    @mock.patch.object(ecos.requests, "get")
    def test_fetch_paginates_until_total_count(self, get):
        get.side_effect = [
            _Response(_payload([_row("20260805", "905.16"), _row("20260806", "903.72")], 3)),
            _Response(_payload([_row("20260807", "895.51")], 3)),
        ]

        result = ecos._fetch_one(
            "731Y001",
            "0000002",
            "daily",
            date(2026, 8, 5),
            date(2026, 8, 7),
            expected_item_name="원/일본엔(100엔)",
            expected_unit="원",
        )

        self.assertEqual(result.tolist(), [905.16, 903.72, 895.51])
        self.assertIn("/1/2/731Y001/", get.call_args_list[0].args[0])
        self.assertIn("/3/4/731Y001/", get.call_args_list[1].args[0])

    @mock.patch.dict("os.environ", {"ECOS_API_KEY": "test-key"})
    @mock.patch.object(ecos.requests, "get")
    def test_fetch_rejects_changed_item_name(self, get):
        get.return_value = _Response(_payload([_row("20260807", "895.51", name="변경된 항목")], 1))

        with self.assertRaisesRegex(ValueError, "item name contract mismatch"):
            ecos._fetch_one(
                "731Y001",
                "0000002",
                "daily",
                date(2026, 8, 7),
                date(2026, 8, 7),
                expected_item_name="원/일본엔(100엔)",
                expected_unit="원",
            )


if __name__ == "__main__":
    unittest.main()
