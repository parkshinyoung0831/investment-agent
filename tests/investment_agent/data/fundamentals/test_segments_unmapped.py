"""컬럼으로 매핑되지 않아 버려지는 세그먼트 concept을 보고하는지 검증한다.

매핑 실패 fact는 적재되지 않고 사라지는데, 무엇이 얼마나 빠지는지 알 수 없으면
``segments.concept_registry``를 언제 보강해야 하는지 판단할 수 없다.
"""
from __future__ import annotations

import unittest

from investment_agent.data.fundamentals.domain.services import build_segment_metrics as wide
from investment_agent.data.fundamentals.domain.services import classify_dimensions as metrics

_FILING = {
    "accession_no": "ACC",
    "accepted_date": "2026-08-01",
    "report_date": "2026-06-30",
}


def _fact(concept_qname: str, value: float = 100.0) -> dict:
    dimensions = {"us-gaap:StatementBusinessSegmentsAxis": "acme:CloudMember"}
    selected = metrics.select_segment_axis(dimensions)
    return {
        "context_id": "ctx",
        "concept_qname": concept_qname,
        "axis": selected.axis,
        "member": selected.member,
        "raw_axis": selected.raw_axis,
        "raw_member": selected.raw_member,
        "segment_type": selected.segment_type,
        "classification_method": selected.classification_method,
        "dimensions": dimensions,
        "normalized_dimensions": metrics.canonical_segment_dimensions(dimensions),
        "dimensions_hash": "hash",
        "dimension_path": "path",
        "period_start": "2026-04-01",
        "period_end": "2026-06-30",
        "is_instant": False,
        "period_kind": "quarter",
        "fiscal_year": 2026,
        "fiscal_period": "Q2",
        "period_key": "2026Q2",
        "unit": "USD",
        "value": value,
    }


class UnmappedConceptReporting(unittest.TestCase):
    def test_unmapped_concept_is_reported_not_silently_dropped(self):
        rows, unmapped = wide.to_segment_wide_rows(
            "TEST",
            _FILING,
            [_fact("acme:SomeConceptWeDoNotMap")],
            "quarter",
        )

        self.assertEqual(rows, [])
        self.assertEqual(unmapped, ["SomeConceptWeDoNotMap"])

    def test_mapped_concept_reports_nothing(self):
        rows, unmapped = wide.to_segment_wide_rows(
            "TEST",
            _FILING,
            [_fact("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax")],
            "quarter",
        )

        self.assertEqual(unmapped, [])
        self.assertEqual(rows[0]["revenue"], 100)

    def test_unmapped_names_are_deduplicated_and_sorted(self):
        _rows, unmapped = wide.to_segment_wide_rows(
            "TEST",
            _FILING,
            [
                _fact("acme:ZebraConcept"),
                _fact("acme:AlphaConcept"),
                _fact("other:ZebraConcept"),
            ],
            "quarter",
        )

        self.assertEqual(unmapped, ["AlphaConcept", "ZebraConcept"])


if __name__ == "__main__":
    unittest.main()
