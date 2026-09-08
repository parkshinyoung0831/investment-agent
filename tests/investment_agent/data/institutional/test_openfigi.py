"""CUSIP/CINS OpenFIGI 조회의 식별자 타입·fallback 계약을 검증한다."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from investment_agent.data.institutional import persistence as db
from investment_agent.data.institutional.infrastructure.sources import openfigi


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> list[dict]:
        return [{}]


class OpenFigiIdentifierTest(unittest.TestCase):
    def test_share_class_ticker_uses_universe_hyphen_notation(self):
        result = openfigi._result_for(
            "084670702",
            "CUSIP",
            {"data": [{"ticker": "BRK/B", "figi": "BBG000DWG505"}]},
            source="openfigi_primary",
        )

        self.assertEqual(result.ticker, "BRK-B")

    def test_primary_request_uses_cusip_and_cins_id_types(self):
        with mock.patch.object(openfigi.requests, "post", return_value=_Response()) as post:
            openfigi._map_batch([("037833100", "CUSIP"), ("G5960L103", "CINS")])

        jobs = post.call_args.kwargs["json"]
        self.assertEqual(jobs[0]["idType"], "ID_CUSIP")
        self.assertEqual(jobs[1]["idType"], "ID_CINS")

    def test_cins_fallback_keeps_original_identifier_type(self):
        primary = {
            "G5960L103": openfigi.MappingResult(
                "G5960L103", "CINS", None, None, "not_found", "openfigi_primary"
            )
        }
        fallback = {
            "G5960L103": openfigi.MappingResult(
                "G5960L103", "CUSIP", "CHUBB", "BBG000000001", "mapped",
                "openfigi_fallback",
            )
        }
        with mock.patch.object(
            openfigi, "_request_jobs", side_effect=[(primary, 1), (fallback, 1)]
        ) as request:
            result, requests_made = openfigi.map_identifiers(["G5960L103"])

        self.assertEqual(requests_made, 2)
        self.assertEqual(result["G5960L103"].identifier_type, "CINS")
        self.assertEqual(result["G5960L103"].ticker, "CHUBB")
        self.assertEqual(request.call_args_list[1].args[0], [("G5960L103", "CUSIP")])

    def test_ambiguous_tickers_are_not_silently_chosen(self):
        result = openfigi._result_for(
            "G5960L103",
            "CINS",
            {"data": [{"ticker": "AAA"}, {"ticker": "BBB"}]},
            source="openfigi_primary",
        )
        self.assertEqual(result.mapping_status, "ambiguous")
        self.assertIsNone(result.ticker)

    def test_unresolved_fallback_is_recorded_in_source(self):
        primary = {
            "037833100": openfigi.MappingResult(
                "037833100", "CUSIP", None, None, "not_found", "openfigi_primary"
            )
        }
        fallback = {
            "037833100": openfigi.MappingResult(
                "037833100", "CINS", None, None, "not_found", "openfigi_fallback"
            )
        }
        with mock.patch.object(
            openfigi, "_request_jobs", side_effect=[(primary, 1), (fallback, 1)]
        ):
            result, _requests_made = openfigi.map_identifiers(["037833100"])

        self.assertEqual(
            result["037833100"].source,
            "openfigi_primary+openfigi_fallback",
        )

    def test_not_found_remains_explainable_and_retries_after_ttl(self):
        now = datetime(2026, 8, 27, tzinfo=timezone.utc)
        row = {
            "mapping_status": "not_found",
            "updated_at": (now - timedelta(days=31)).isoformat(),
        }
        self.assertTrue(db.mapping_is_due(row, now=now))
        row["updated_at"] = (now - timedelta(days=29)).isoformat()
        self.assertFalse(db.mapping_is_due(row, now=now))

    def test_unknown_cached_status_is_not_treated_as_a_provider_error_cache(self):
        now = datetime(2026, 8, 27, tzinfo=timezone.utc)
        row = {
            "mapping_status": "unexpected_legacy_value",
            "updated_at": (now - timedelta(days=31)).isoformat(),
        }
        self.assertTrue(db.mapping_is_due(row, now=now))

    def test_historical_mapping_is_not_requeried(self):
        self.assertFalse(db.mapping_is_due({
            "mapping_status": "historical",
            "updated_at": "2020-01-01T00:00:00+00:00",
        }))

    def test_each_batch_uses_the_shared_rate_limiter(self):
        with mock.patch.object(openfigi, "_throttle") as throttle, mock.patch.object(
            openfigi.requests, "post", return_value=_Response()
        ):
            openfigi._map_batch([("037833100", "CUSIP")])

        throttle.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
