"""투자 판단 reporting read model의 현재 v1·원문 차단 계약 테스트."""
from __future__ import annotations

import unittest
from pathlib import Path

from investment_agent.platform.serialization import canonical_json
from investment_agent.reporting.services.investment import (
    build_decision_case_read_model,
    build_decision_cases_read_model,
    normalize_role_analyses,
)


def _digest() -> dict:
    return {
        "ticker": "AAPL",
        "as_of_at": "2026-09-04T12:00:00+00:00",
        "source_kind": "live_shadow",
        "evidence_count": 2,
        "domain_counts": {"fundamentals": 1, "news": 1},
        "source_counts": {"SEC": 1, "yfinance": 1},
        "latest_available_at": {"news": "2026-09-04T11:00:00+00:00"},
        "latest_filed_at": {},
        "external_evidence_ids": ["EXT-1"],
        "missing_data": ["analyst estimates"],
        "warnings": ["macro stale"],
        "role_analysis_count": 1,
    }


def _manifest() -> dict:
    return {
        "artifact_id": "decision-evidence-abc",
        "artifact_kind": "decision_evidence",
        "sha256": "a" * 64,
        "uri": "artifact://decision-evidence/aa/" + "a" * 64 + ".json",
        "code_commit": "abc123",
        "schema_version": 1,
        "created_at": "2026-09-04T12:01:00+00:00",
        "byte_size": 1234,
    }


class DecisionCaseReadModelTest(unittest.TestCase):
    def test_current_view_row_exposes_artifact_metadata_without_storage_json(self) -> None:
        model = build_decision_case_read_model({
            "case_key": "case-1",
            "ticker": "AAPL",
            "evidence_uri": _manifest()["uri"],
            "evidence_sha256": _manifest()["sha256"],
            "evidence_byte_size": _manifest()["byte_size"],
            "evidence_schema_version": "1",
            "final_decision": {"action": "watch", "evidence_digest": _digest()},
        })

        self.assertEqual(model["evidence_storage"], "artifact")
        self.assertEqual(model["evidence_digest"]["evidence_count"], 2)
        self.assertEqual(model["evidence_manifest"]["sha256"], "a" * 64)
        self.assertEqual(model["role_summaries"], [])

    def test_current_decision_does_not_expose_raw_evidence(self) -> None:
        raw_secret = "원문-비공개-" * 100
        model = build_decision_case_read_model({
            "case_key": "case-2",
            "final_decision": {
                "action": "watch",
                "evidence_digest": {"warnings": ["macro stale"]},
            },
        })

        serialized = canonical_json(model)
        self.assertEqual(model["evidence_storage"], "missing")
        self.assertEqual(model["evidence_digest"]["warnings"], ["macro stale"])
        self.assertEqual(model["evidence_items"], [])
        self.assertEqual(model["role_summaries"], [])
        self.assertNotIn("payload", serialized)
        self.assertNotIn(raw_secret, serialized)

    def test_artifact_error_keeps_navigable_state_without_leaking_raw_data(self) -> None:
        model = build_decision_case_read_model({
            "final_decision": {
                "evidence_artifact_error": "EvidenceArtifactError: disk unavailable",
            },
        })

        self.assertEqual(model["evidence_storage"], "artifact_error")
        self.assertIn("disk unavailable", model["evidence_artifact_error"])
        self.assertNotIn("secret", canonical_json(model))

    def test_manifest_numeric_metadata_is_safe_for_display(self) -> None:
        manifest = _manifest()
        manifest["schema_version"] = "not-an-integer"
        manifest["byte_size"] = "not-an-integer"
        model = build_decision_case_read_model({
            "evidence_manifest": manifest,
            "final_decision": {"evidence_digest": _digest()},
        })

        self.assertIsNone(model["evidence_manifest"]["schema_version"])
        self.assertIsNone(model["evidence_manifest"]["byte_size"])

    def test_list_conversion_keeps_order_and_role_contract(self) -> None:
        rows = build_decision_cases_read_model([
            {"case_key": "a"},
            {"case_key": "b"},
        ])
        self.assertEqual([row["case_key"] for row in rows], ["a", "b"])
        self.assertEqual(
            [row["role"] for row in normalize_role_analyses({
                "market_report": "시장",
                "investment_debate_state": {"bull_history": "상승", "bear_history": ""},
            })],
            ["market_analyst", "bull"],
        )

    def test_dashboard_and_notification_use_the_shared_contract(self) -> None:
        root = Path(__file__).resolve().parents[3]
        dashboard_db = (root / "src/investment_agent/dashboard/db.py").read_text(encoding="utf-8")
        notification_db = (root / "src/investment_agent/reporting/notifications/investment/db.py").read_text(encoding="utf-8")
        approval_page = (root / "src/investment_agent/dashboard/app_pages/ai_approval.py").read_text(
            encoding="utf-8"
        )
        intelligence_page = (
            root / "src/investment_agent/dashboard/app_pages/intelligence.py"
        ).read_text(encoding="utf-8")

        self.assertIn("build_decision_cases_read_model(case_rows)", dashboard_db)
        self.assertIn("build_decision_case_read_model(row)", notification_db)
        self.assertNotIn('get("evidence_bundle")', approval_page)
        self.assertNotIn('get("evidence_bundle")', intelligence_page)


if __name__ == "__main__":
    unittest.main()
