"""회사별 세그먼트 형식 보존과 품질 판정 규칙을 검증한다."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from investment_agent.data.fundamentals.domain.services import assess_segment_quality as quality
from investment_agent.data.fundamentals.domain.services import build_segment_metrics as wide
from investment_agent.data.fundamentals.domain.services import classify_dimensions as metrics
from investment_agent.data.fundamentals.domain.taxonomy import segment_concepts as concepts
from investment_agent.data.fundamentals.domain.taxonomy import segment_metrics as columns
from investment_agent.data.fundamentals.infrastructure.supabase import segment_metrics as db


def _row(
    *,
    name: str,
    revenue: float,
    axis: str = "BusinessSegments",
    segment_type: str = "business",
    method: str = "standard",
    concept_method: str = "edgartools",
    dimension_count: int = 1,
    secondary_axis: str | None = None,
    secondary_member: str | None = None,
) -> dict:
    return {
        "cik": "0000000001",
        "fiscal_year": 2026,
        "fiscal_period": "Q2",
        "period_kind": "quarter",
        "axis": axis,
        "member": name,
        "segment_type": segment_type,
        "classification_method": method,
        "concept_method": concept_method,
        "dimension_count": dimension_count,
        "secondary_axis": secondary_axis,
        "secondary_member": secondary_member,
        "revenue": revenue,
    }


class DimensionPreservationTest(unittest.TestCase):
    def test_apple_member_names_keep_product_brand_casing(self):
        self.assertEqual(metrics.display_member_name("aapl:IPhoneMember"), "iPhone")
        self.assertEqual(metrics.display_member_name("aapl:IPadMember"), "iPad")
        self.assertEqual(metrics.display_member_name("aapl:ServiceMember"), "Services")

    def test_custom_axis_is_preserved_and_classified_heuristically(self):
        dimensions = {
            "goog:ProductsAndPlatformsAxis": "goog:GoogleCloudMember",
            "goog:RegionAxis": "goog:UnitedStatesMember",
        }

        selected = metrics.select_segment_axis(dimensions)
        normalized = metrics.canonical_segment_dimensions(dimensions)

        self.assertIsNotNone(selected)
        self.assertEqual(selected.segment_type, "product")
        self.assertEqual(selected.classification_method, "heuristic")
        self.assertEqual(selected.raw_axis, "goog:ProductsAndPlatformsAxis")
        self.assertEqual(len(normalized), 2)

    def test_unrecognized_axis_is_kept_as_unknown(self):
        selected = metrics.select_segment_axis({"acme:ManagementViewAxis": "acme:AlphaMember"})

        self.assertIsNotNone(selected)
        self.assertEqual(selected.segment_type, "unknown")
        self.assertEqual(selected.raw_member, "acme:AlphaMember")

    def test_database_registry_has_priority_over_heuristic(self):
        registry = {
            "ProductsAndPlatforms": {
                "axis_category": "business",
                "is_core": True,
                "include_in_revenue_pct": True,
            }
        }

        selected = metrics.select_segment_axis(
            {"goog:ProductsAndPlatformsAxis": "goog:GoogleCloudMember"},
            registry,
        )

        self.assertEqual(selected.segment_type, "business")
        self.assertEqual(selected.classification_method, "registry")

    def test_company_revenue_extension_tag_is_accepted_but_cost_is_not(self):
        self.assertEqual(
            concepts.resolve_concept("goog:GoogleCloudRevenue"),
            ("revenue", "candidate"),
        )
        self.assertIsNone(concepts.to_column_key("goog:GoogleCloudCostOfRevenue"))

    def test_edgartools_is_the_default_revenue_dictionary(self):
        self.assertEqual(
            concepts.resolve_concept(
                "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
            ),
            ("revenue", "edgartools"),
        )

    def test_standard_segment_metrics_keep_their_meaning(self):
        profit = concepts.resolve_concept_details("us-gaap:OperatingIncomeLoss")
        cost = concepts.resolve_concept_details("us-gaap:CostOfGoodsAndServicesSold")
        assets = concepts.resolve_concept_details("us-gaap:Assets")

        self.assertEqual(profit["column_key"], "profit_loss")
        self.assertEqual(profit["measure_kind"], "operating_income")
        self.assertIsNone(cost["column_key"])
        self.assertEqual(assets["column_key"], "assets")

    def test_database_concept_registry_has_priority(self):
        key, method = concepts.resolve_concept(
            "goog:CloudMetric",
            {"CloudMetric": "revenue"},
        )

        self.assertEqual((key, method), ("revenue", "override"))

    def test_inactive_database_concept_blocks_heuristic_fallback(self):
        key, method = concepts.resolve_concept(
            "goog:GoogleCloudRevenue",
            {"GoogleCloudRevenue": None},
        )

        self.assertEqual((key, method), (None, "override"))

    def test_edgartools_gap_is_an_explicit_override(self):
        self.assertEqual(
            concepts.resolve_concept(
                "us-gaap:RevenueFromExternalCustomers",
                {"RevenueFromExternalCustomers": "revenue"},
            ),
            ("revenue", "override"),
        )

    def test_member_name_is_human_readable(self):
        self.assertEqual(metrics.display_member_name("goog:GoogleCloudMember"), "Google Cloud")

    def test_wide_row_keeps_raw_and_normalized_dimensions(self):
        dimensions = {
            "goog:ProductsAndPlatformsAxis": "goog:GoogleCloudMember",
            "goog:RegionAxis": "goog:UnitedStatesMember",
        }
        selected = metrics.select_segment_axis(dimensions)
        fact = {
            "context_id": "ctx",
            "concept_qname": "goog:GoogleCloudRevenue",
            "axis": selected.axis,
            "member": selected.member,
            "raw_axis": selected.raw_axis,
            "raw_member": selected.raw_member,
            "segment_type": selected.segment_type,
            "classification_method": selected.classification_method,
            "dimensions": dimensions,
            "normalized_dimensions": metrics.canonical_segment_dimensions(dimensions),
            "dimensions_hash": "raw-dimensions-hash",
            "dimension_path": "raw path",
            "period_start": "2026-04-01",
            "period_end": "2026-06-30",
            "is_instant": False,
            "period_kind": "quarter",
            "fiscal_year": 2026,
            "fiscal_period": "Q2",
            "period_key": "2026Q2",
            "unit": "USD",
            "value": 100,
        }

        rows, unmapped = wide.to_segment_wide_rows(
            "TEST",
            {"accession_no": "ACC", "accepted_date": "2026-08-01", "report_date": "2026-06-30"},
            [fact],
            "quarter",
        )

        self.assertEqual(unmapped, [])
        self.assertEqual(rows[0]["dimensions"], dimensions)
        self.assertEqual(rows[0]["dimension_count"], 2)
        self.assertEqual(rows[0]["raw_axis"], "goog:ProductsAndPlatformsAxis")
        self.assertEqual(rows[0]["display_name"], "Google Cloud")

    def test_wide_row_pivots_revenue_and_operating_income(self):
        selected = metrics.select_segment_axis(
            {"us-gaap:BusinessSegmentsAxis": "test:CloudMember"}
        )
        base = {
            "context_id": "ctx", "axis": selected.axis, "member": selected.member,
            "raw_axis": selected.raw_axis, "raw_member": selected.raw_member,
            "segment_type": selected.segment_type,
            "classification_method": selected.classification_method,
            "dimensions": {"us-gaap:BusinessSegmentsAxis": "test:CloudMember"},
            "normalized_dimensions": {"BusinessSegments": "Cloud"},
            "dimensions_hash": "hash", "dimension_path": "path",
            "period_start": "2026-04-01", "period_end": "2026-06-30",
            "is_instant": False, "period_kind": "quarter",
            "fiscal_year": 2026, "fiscal_period": "Q2", "period_key": "2026Q2",
            "unit": "USD",
        }
        facts = [
            {**base, "concept_qname": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "value": 100},
            {**base, "concept_qname": "us-gaap:OperatingIncomeLoss", "value": 25},
        ]

        rows, _unmapped = wide.to_segment_wide_rows(
            "TEST", {"accession_no": "ACC", "accepted_date": "2026-08-01", "report_date": "2026-06-30"},
            facts, "quarter",
        )

        self.assertEqual(rows[0]["revenue"], 100)
        self.assertEqual(rows[0]["profit_loss"], 25)
        self.assertEqual(rows[0]["profit_measure_kind"], "operating_income")
        self.assertEqual(rows[0]["metric_methods"]["profit_loss"], "edgartools")

    def test_operating_segments_qualifier_keeps_business_axis_single_dimension(self):
        dimensions = {
            "srt:ConsolidationItemsAxis": "us-gaap:OperatingSegmentsMember",
            "us-gaap:StatementBusinessSegmentsAxis": "pg:BeautySegmentMember",
        }
        selected = metrics.select_segment_axis(dimensions)
        fact = {
            "context_id": "ctx",
            "concept_qname": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
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
            "period_start": "2025-07-01",
            "period_end": "2026-06-30",
            "is_instant": False,
            "period_kind": "annual",
            "fiscal_year": 2026,
            "fiscal_period": "FY",
            "period_key": "2026FY",
            "unit": "USD",
            "value": 16_023,
        }

        rows, unmapped = wide.to_segment_wide_rows(
            "PG",
            {"accession_no": "ACC", "accepted_date": "2026-08-01", "report_date": "2026-06-30"},
            [fact],
            "annual",
        )

        self.assertEqual(unmapped, [])
        self.assertEqual(rows[0]["dimension_count"], 1)
        self.assertEqual(rows[0]["dimensions"], dimensions)

    def test_other_secondary_dimensions_remain_cross_tabs(self):
        dimensions = {
            "us-gaap:StatementBusinessSegmentsAxis": "test:CloudMember",
            "us-gaap:StatementGeographicalAxis": "us-gaap:UnitedStatesMember",
        }

        self.assertEqual(metrics.segment_dimension_count(dimensions), 2)

    def test_select_segment_axes_extracts_primary_and_secondary_for_two_axes(self):
        dimensions = {
            "us-gaap:ProductOrServiceAxis": "aapl:IPhoneMember",
            "us-gaap:StatementGeographicalAxis": "us-gaap:AmericasMember",
        }

        primary, secondary = metrics.select_segment_axes(dimensions)

        self.assertEqual(primary.segment_type, "product")
        self.assertEqual(primary.member, "IPhone")
        self.assertIsNotNone(secondary)
        self.assertEqual(secondary.segment_type, "geographic")
        self.assertEqual(secondary.member, "Americas")

    def test_select_segment_axes_has_no_secondary_for_single_axis(self):
        primary, secondary = metrics.select_segment_axes(
            {"us-gaap:StatementBusinessSegmentsAxis": "test:CloudMember"}
        )

        self.assertEqual(primary.segment_type, "business")
        self.assertIsNone(secondary)

    def test_select_segment_axes_ignores_scope_qualifier_for_depth(self):
        dimensions = {
            "srt:ConsolidationItemsAxis": "us-gaap:OperatingSegmentsMember",
            "us-gaap:StatementBusinessSegmentsAxis": "pg:BeautySegmentMember",
        }

        primary, secondary = metrics.select_segment_axes(dimensions)

        self.assertEqual(primary.segment_type, "business")
        self.assertIsNone(secondary)

    def test_product_operating_income_and_duration_assets_are_rejected(self):
        self.assertFalse(
            columns.is_compatible("profit_loss", "product", "quarter")
        )
        self.assertFalse(
            columns.is_compatible("assets", "business", "quarter")
        )


class QualityAssessmentTest(unittest.TestCase):
    def test_standard_single_axis_with_matching_total_is_verified(self):
        rows = [_row(name="A", revenue=60), _row(name="B", revenue=40)]

        result = quality.assess_rows(rows, {("0000000001", 2026, "Q2"): {"revenue": 100}})

        self.assertTrue(all(row["quality_status"] == "verified" for row in result))
        self.assertTrue(all(row["coverage_ratio"] == 1.0 for row in result))

    def test_zero_company_metric_is_partial_not_a_crash(self):
        """회사 지표가 0이면 커버리지 비율을 낼 수 없다.

        None인 채로 임계값 비교에 들어가면 TypeError로 그 배치의 분기 파일
        전체가 실패하므로, partial로 끊고 이유를 남긴다.
        """
        rows = [_row(name="A", revenue=60), _row(name="B", revenue=40)]

        result = quality.assess_rows(rows, {("0000000001", 2026, "Q2"): {"revenue": 0}})

        self.assertTrue(all(row["quality_status"] == "partial" for row in result))
        self.assertTrue(
            all("company_metric_zero" in row["quality_reasons"] for row in result)
        )
        self.assertTrue(all(row["coverage_ratio"] is None for row in result))

    def test_heuristic_axis_is_partial_even_when_total_matches(self):
        rows = [_row(name="A", revenue=100, axis="CustomSegments", method="heuristic")]

        result = quality.assess_rows(rows, {("0000000001", 2026, "Q2"): {"revenue": 100}})

        self.assertEqual(result[0]["quality_status"], "partial")
        self.assertIn("heuristic_classification", result[0]["quality_reasons"])

    def test_cross_dimension_and_unknown_axis_are_unsafe(self):
        rows = [
            _row(
                name="A",
                revenue=100,
                segment_type="unknown",
                method="unknown",
                dimension_count=2,
            )
        ]

        result = quality.assess_rows(rows, {("0000000001", 2026, "Q2"): {"revenue": 100}})

        self.assertEqual(result[0]["quality_status"], "unsafe")
        self.assertIn("unknown_axis", result[0]["quality_reasons"])
        self.assertIn("cross_dimension", result[0]["quality_reasons"])

    def test_cross_dimension_is_not_added_to_coverage_total(self):
        rows = [
            _row(name="A", revenue=100),
            _row(name="A by region", revenue=100, dimension_count=2),
        ]

        result = quality.assess_rows(rows, {("0000000001", 2026, "Q2"): {"revenue": 100}})

        self.assertEqual(result[0]["coverage_ratio"], 1.0)
        self.assertEqual(result[0]["quality_status"], "verified")
        self.assertEqual(result[1]["quality_status"], "unsafe")

    def test_candidate_concept_is_partial(self):
        result = quality.assess_rows(
            [_row(name="A", revenue=100, concept_method="candidate")],
            {("0000000001", 2026, "Q2"): {"revenue": 100}},
        )

        self.assertEqual(result[0]["quality_status"], "partial")
        self.assertIn("candidate_concept", result[0]["quality_reasons"])

    def test_unmapped_concept_is_unsafe(self):
        result = quality.assess_rows(
            [_row(name="A", revenue=100, concept_method="unmapped")],
            {("0000000001", 2026, "Q2"): {"revenue": 100}},
        )

        self.assertEqual(result[0]["quality_status"], "unsafe")
        self.assertIn("unmapped_concept", result[0]["quality_reasons"])

    def test_large_total_mismatch_is_unsafe(self):
        result = quality.assess_rows(
            [_row(name="A", revenue=200)],
            {("0000000001", 2026, "Q2"): {"revenue": 100}},
        )

        self.assertEqual(result[0]["quality_status"], "unsafe")
        self.assertEqual(result[0]["coverage_ratio"], 2.0)

    def test_parent_product_total_is_excluded_when_children_reconcile(self):
        rows = [
            _row(name="Product", revenue=80, segment_type="product", axis="ProductOrService"),
            _row(name="Services", revenue=20, segment_type="product", axis="ProductOrService"),
            _row(name="Phone", revenue=50, segment_type="product", axis="ProductOrService"),
            _row(name="Mac", revenue=20, segment_type="product", axis="ProductOrService"),
            _row(name="Tablet", revenue=10, segment_type="product", axis="ProductOrService"),
        ]

        result = quality.assess_rows(rows, {("0000000001", 2026, "Q2"): {"revenue": 100}})

        self.assertEqual(result[0]["quality_status"], "unsafe")
        self.assertIn("overlapping_aggregate", result[0]["quality_reasons"])
        self.assertTrue(all(row["coverage_ratio"] == 1.0 for row in result))
        self.assertTrue(all(row["quality_status"] == "verified" for row in result[1:]))

    def test_two_dimensional_children_are_verified_when_sum_matches_parent(self):
        rows = [
            _row(name="iPhone", revenue=100, axis="ProductOrService", segment_type="product"),
            _row(
                name="iPhone", revenue=60, axis="ProductOrService", segment_type="product",
                dimension_count=2, secondary_axis="Geographical", secondary_member="Americas",
            ),
            _row(
                name="iPhone", revenue=40, axis="ProductOrService", segment_type="product",
                dimension_count=2, secondary_axis="Geographical", secondary_member="Europe",
            ),
        ]

        result = quality.assess_rows(rows, {("0000000001", 2026, "Q2"): {"revenue": 100}})

        self.assertTrue(all(row["quality_status"] == "verified" for row in result))

    def test_two_dimensional_children_are_partial_within_partial_range_mismatch(self):
        rows = [
            _row(name="iPhone", revenue=100, axis="ProductOrService", segment_type="product"),
            _row(
                name="iPhone", revenue=60, axis="ProductOrService", segment_type="product",
                dimension_count=2, secondary_axis="Geographical", secondary_member="Americas",
            ),
        ]

        result = quality.assess_rows(rows, {("0000000001", 2026, "Q2"): {"revenue": 100}})

        self.assertEqual(result[1]["quality_status"], "partial")
        self.assertIn("cross_dimension_sum_mismatch", result[1]["quality_reasons"])

    def test_two_dimensional_children_are_unsafe_when_sum_grossly_mismatches_parent(self):
        rows = [
            _row(name="iPhone", revenue=100, axis="ProductOrService", segment_type="product"),
            _row(
                name="iPhone", revenue=10, axis="ProductOrService", segment_type="product",
                dimension_count=2, secondary_axis="Geographical", secondary_member="Americas",
            ),
        ]

        result = quality.assess_rows(rows, {("0000000001", 2026, "Q2"): {"revenue": 100}})

        self.assertEqual(result[1]["quality_status"], "unsafe")
        self.assertIn("cross_dimension_sum_mismatch", result[1]["quality_reasons"])

    def test_two_dimensional_child_without_matching_parent_is_partial(self):
        rows = [
            _row(
                name="iPhone", revenue=60, axis="ProductOrService", segment_type="product",
                dimension_count=2, secondary_axis="Geographical", secondary_member="Americas",
            ),
        ]

        result = quality.assess_rows(rows, {("0000000001", 2026, "Q2"): 100})

        self.assertEqual(result[0]["quality_status"], "partial")
        self.assertIn("no_dimensional_parent", result[0]["quality_reasons"])

    def test_profit_quality_is_independent_from_revenue(self):
        row = _row(name="Cloud", revenue=100)
        row.update({
            "profit_loss": 20,
            "profit_measure_kind": "operating_income",
            "metric_methods": {"revenue": "edgartools", "profit_loss": "edgartools"},
        })

        result = quality.assess_rows(
            [row],
            {("0000000001", 2026, "Q2"): {"revenue": 100, "operating_income_loss": 20}},
        )[0]

        self.assertEqual(result["quality_status"], "verified")
        self.assertEqual(result["profit_quality_status"], "verified")
        self.assertEqual(result["metric_quality"]["profit_loss"]["coverage_ratio"], 1.0)


class SchemaContractTest(unittest.TestCase):
    def test_compact_projection_discards_raw_and_unsafe_values(self):
        row = {
            "cik": "0000000001", "accession_no": "ACC", "fiscal_year": 2026,
            "fiscal_period": "Q2", "period_kind": "quarter",
            "period_end": "2026-06-30", "segment_hash": "HASH",
            "segment_type": "business", "axis": "BusinessSegments",
            "member": "Cloud", "display_name": "Cloud",
            "classification_method": "standard", "dimension_count": 1,
            "concept_method": "edgartools",
            "metric_methods": {"revenue": "edgartools", "profit_loss": "candidate"},
            "revenue": 100, "quality_status": "verified", "coverage_ratio": 1,
            "profit_loss": 20, "profit_measure_kind": "operating_income",
            "profit_measure_label": "영업이익", "profit_quality_status": "unsafe",
            "profit_coverage_ratio": 2, "assets": None,
            "assets_quality_status": "unsafe", "assets_coverage_ratio": None,
            "dimensions": {"BusinessSegments": "Cloud"},
            "source_contexts": {"revenue": "ctx"},
        }

        compact = db.compact_rows([row])[0]

        self.assertEqual(compact["revenue"], 100)
        self.assertIsNone(compact["profit_loss"])
        # 등급을 정하는 데 쓰인 입력(분류·추출 경로)은 저장하지 않는다. 결과 등급만 남는다.
        for dropped in ("classification_method", "revenue_method", "profit_method",
                        "display_name", "period_kind", "depth", "profit_measure_label"):
            self.assertNotIn(dropped, compact)
        self.assertNotIn("dimensions", compact)
        self.assertNotIn("source_contexts", compact)
        self.assertNotIn("quality_reasons", compact)
        self.assertNotIn("updated_at", compact)

    def test_compact_projection_rejects_cross_dimensions(self):
        row = {
            "cik": "0000000001", "accession_no": "ACC", "fiscal_year": 2026,
            "fiscal_period": "Q2", "period_kind": "quarter",
            "period_end": "2026-06-30", "segment_hash": "HASH",
            "segment_type": "business", "axis": "BusinessSegments",
            "member": "Cloud", "classification_method": "standard",
            "dimension_count": 2, "revenue": 100,
            "quality_status": "verified", "profit_quality_status": "unsafe",
            "assets_quality_status": "unsafe",
        }
        self.assertEqual(db.compact_rows([row]), [])

    def test_compact_projection_persists_well_formed_two_dimensional_child(self):
        row = {
            "cik": "0000000001", "accession_no": "ACC", "fiscal_year": 2026,
            "fiscal_period": "Q2", "period_kind": "quarter",
            "period_end": "2026-06-30", "segment_hash": "HASH2",
            "segment_type": "product", "axis": "ProductOrService",
            "member": "IPhone", "display_name": "iPhone",
            "classification_method": "standard", "dimension_count": 2,
            "secondary_axis": "Geographical", "secondary_member": "Americas",
            "concept_method": "edgartools",
            "metric_methods": {"revenue": "edgartools"},
            "revenue": 60, "quality_status": "verified", "coverage_ratio": 1.0,
            "profit_loss": None, "profit_measure_kind": None,
            "profit_measure_label": None, "profit_quality_status": "unsafe",
            "profit_coverage_ratio": None, "assets": None,
            "assets_quality_status": "unsafe", "assets_coverage_ratio": None,
        }

        compact = db.compact_rows([row])[0]

        # 2차원임을 알리는 별도 컬럼은 없다 — secondary_* 가 채워진 것이 곧 2차원이다.
        self.assertNotIn("depth", compact)
        self.assertEqual(compact["secondary_axis"], "Geographical")
        self.assertEqual(compact["secondary_member"], "Americas")
        self.assertEqual(compact["revenue"], 60)
        # 커버리지는 1차원 분할의 성질이라 2차원 자식에는 남기지 않는다.
        self.assertIsNone(compact["coverage_ratio"])


class CompanyBaselineTest(unittest.TestCase):
    def test_annual_segment_baseline_sums_discrete_quarters(self):
        quarterly = [
            {
                "cik": "0000801243", "fiscal_year": 2026, "fiscal_period": period,
                "revenue": revenue, "operating_income_loss": income,
                "assets": assets,
            }
            for period, revenue, income, assets in (
                ("Q1", 22, 6, 100),
                ("Q2", 21, 5, 101),
                ("Q3", 20, 4, 102),
                ("Q4", 19, 3, 103),
            )
        ]
        rows = [{"cik": "0000801243", "fiscal_year": 2026, "fiscal_period": "FY"}]

        with mock.patch.object(db, "select_all_paged", return_value=quarterly):
            result = db._company_metrics_for(rows)

        self.assertEqual(
            result[("0000801243", 2026, "FY")],
            {"revenue": 82.0, "operating_income_loss": 18.0, "assets": 103},
        )


class SegmentSnapshotReadTest(unittest.TestCase):
    def test_snapshot_filters_future_filings_before_processing_lookup(self):
        responses = [
            [{"ticker": "AAPL", "cik": "0000000001"}],
            [
                {
                    "accession_no": "future",
                    "cik": "0000000001",
                    "form_type": "10-Q",
                    "report_date": "2026-09-30",
                    "filing_date": "2026-09-30",
                },
                {
                    "accession_no": "current",
                    "cik": "0000000001",
                    "form_type": "10-Q",
                    "report_date": "2026-06-30",
                    "filing_date": "2026-07-31",
                },
            ],
            [{"accession_no": "current", "status": "parsed", "updated_at": "2026-08-01T00:00:00+00:00"}],
            [{"accession_no": "current", "fiscal_year": 2026, "fiscal_period": "Q2", "revenue": 100}],
        ]
        with mock.patch.object(db, "select_all_paged", side_effect=responses) as paged:
            result = db.segment_snapshot_as_of(
                "AAPL", datetime(2026, 8, 21, tzinfo=timezone.utc)
            )

        self.assertEqual([row["accession_no"] for row in result["filings"]], ["current"])
        self.assertEqual([row["accession_no"] for row in result["metrics"]], ["current"])
        self.assertEqual(paged.call_count, 4)

    def test_company_baseline_read_failure_aborts_partial_segment_write(self):
        rows = [{"cik": "0000801243", "fiscal_year": 2026, "fiscal_period": "FY"}]
        with (
            mock.patch.object(
                db, "select_all_paged", side_effect=RuntimeError("database unavailable")
            ),
            self.assertRaisesRegex(RuntimeError, "database unavailable"),
        ):
            db._company_metrics_for(rows)

    def test_schema_persists_only_compact_core_metrics(self):
        sql = Path("db/postgres/v1/30_fundamentals.sql").read_text(encoding="utf-8")
        metric_table = sql.split(
            "CREATE TABLE IF NOT EXISTS fundamentals.segment_metrics", 1
        )[1].split("CREATE INDEX", 1)[0]

        for column in (
            # SEC 좌표
            "cik", "fiscal_year", "fiscal_period", "period_end", "accession_no",
            # 세그먼트 좌표 — 1차원은 axis/member, 2차원은 여기에 secondary_* 가 붙는다
            "segment_type", "axis", "member", "secondary_axis", "secondary_member",
            # 숫자의 성격과 등급
            "is_derived", "quality_status", "coverage_ratio",
            "profit_loss", "profit_measure_kind", "assets",
        ):
            self.assertIn(column, metric_table)
        for removed in (
            # 다른 컬럼에서 그대로 유도되는 값은 저장하지 않는다.
            "period_kind",             # fiscal_period = 'FY' 인가
            "depth",                   # secondary_axis 가 있는가
            "display_name",            # display_member_name(member)
            "profit_measure_label",    # profit_measure_kind 의 표기
            # 등급을 정할 때 쓰는 입력. 결과 등급만 남긴다.
            "classification_method", "revenue_method", "profit_method",
            # 예전에 이미 걷어낸 것들
            "assets_method",
            "profit_coverage_ratio",
            "assets_coverage_ratio",
            "updated_at timestamptz",
            "normalized_dimensions",
            "source_contexts",
            "cost_of_revenue",
        ):
            self.assertNotIn(removed, metric_table)
        self.assertNotIn("segment_revenue_source", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS fundamentals.segment_metrics", sql)
        self.assertIn(
            "PRIMARY KEY (cik, accession_no, fiscal_year, fiscal_period, segment_hash)",
            sql,
        )
        self.assertNotIn("reconciliation_diff", metric_table)
        # 세그먼트 공시 상태는 company와 같은 filing_processing을 content_type으로 나눠 쓴다.
        self.assertIn("content_type    text NOT NULL CHECK (content_type IN ('company', 'segments'))", sql)
        self.assertNotIn("segment_filing_runs", sql)
        # 1차원/2차원 구분은 secondary_* 짝의 유무 하나로만 표현된다.
        self.assertIn("segment_secondary_pair_check", metric_table)
        self.assertIn("segment_coverage_scope_check", metric_table)
        self.assertNotIn("segment_metrics_period_kind_check", sql)
        self.assertNotIn("segment_metrics_depth_check", sql)


class DerivedQuartersCarryNoBalances(unittest.TestCase):
    """파생 분기는 잔액(instant)을 들고 오지 않는다.

    Q4는 FY에서 Q1~Q3를 빼서 만든다. 그 차감은 유량에만 뜻이 있고 잔액에는 없다.
    FY 행을 통째로 복사해 만들기 때문에 비우지 않으면 같은 period_end의 assets가
    FY와 파생 Q4 두 곳에 남아, 스키마의 invalid_derived_rows가 이것을 센다.
    """

    def _seg(self, fiscal_period: str, revenue: float, assets: float | None) -> dict:
        return {
            "cik": "0000320193",
            "fiscal_year": 2025,
            "fiscal_period": fiscal_period,
            "period_end": "2025-09-27",
            "period_key": f"2025{fiscal_period}",
            "period_kind": "annual" if fiscal_period == "FY" else "quarter",
            "accession_no": "0000320193-25-000001",
            "segment_type": "business",
            "segment_hash": "a" * 40,
            "axis": "BusinessSegments",
            "member": "AmericasSegment",
            "revenue": revenue,
            "profit_loss": None,
            "assets": assets,
            "is_derived": False,
        }

    def test_q4_derived_from_annual_drops_assets_but_keeps_flow(self) -> None:
        derived = wide.derive_q4_rows(
            annual=[self._seg("FY", 400.0, 1000.0)],
            q1=[self._seg("Q1", 100.0, 900.0)],
            q2=[self._seg("Q2", 100.0, 950.0)],
            q3=[self._seg("Q3", 100.0, 980.0)],
        )

        self.assertEqual(len(derived), 1)
        row = derived[0]
        self.assertTrue(row["is_derived"])
        self.assertEqual(row["fiscal_period"], "Q4")
        self.assertAlmostEqual(row["revenue"], 100.0)
        for column in columns.INSTANT_COLUMNS:
            self.assertIsNone(row[column], f"{column} must not be derived")


if __name__ == "__main__":
    unittest.main()
