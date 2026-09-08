"""판단 근거 artifact와 DB digest 계약 테스트."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from investment_agent.platform.serialization import canonical_json
from investment_agent.trading.evidence.artifacts import (
    EvidenceArtifactError,
    EvidenceArtifactStore,
    archive_case_evidence,
    build_evidence_digest,
)


def _bundle() -> dict:
    return {
        "ticker": "AAPL",
        "as_of_at": "2026-09-04T12:00:00+00:00",
        "source_kind": "live_shadow",
        "evidence": [
            {
                "evidence_id": "fundamentals-1",
                "domain": "fundamentals",
                "source": "SEC",
                "available_at": "2026-08-01T12:00:00+00:00",
                "payload": {
                    "raw_text": "DB digest에 들어가면 안 되는 긴 원문",
                    "filings": [{"filed_at": "2026-08-01T12:00:00+00:00"}],
                },
            },
            {
                "evidence_id": "market-1",
                "domain": "market",
                "source": "market.prices",
                "available_at": "2026-09-03T21:00:00+00:00",
                "payload": {"close": 100.0},
            },
        ],
        "external_evidence": [
            {"manifest_id": "EXT-NEWS-1", "raw_text": "외부 원문"},
            {"manifest_id": "EXT-NEWS-1"},
        ],
        "missing_data": ["analyst estimates"],
        "warnings": ["macro stale"],
    }


class EvidenceArtifactStoreTest(unittest.TestCase):
    def test_write_is_content_addressed_idempotent_and_verified_on_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = EvidenceArtifactStore(directory)
            first = store.write_case(
                case_key="case-1",
                evidence_bundle=_bundle(),
                role_analyses=[{"role": "bull", "summary": "근거 요약"}],
                code_commit="abc123",
            )
            second = store.write_case(
                case_key="case-1",
                evidence_bundle=_bundle(),
                role_analyses=[{"role": "bull", "summary": "근거 요약"}],
                code_commit="abc123",
            )

            self.assertEqual(first.artifact_id, second.artifact_id)
            self.assertEqual(first.uri, second.uri)
            self.assertEqual(first.sha256, second.sha256)
            payload = store.read(first)
            self.assertEqual(payload["case_key"], "case-1")
            self.assertEqual(payload["evidence_bundle"]["ticker"], "AAPL")
            self.assertEqual(payload["role_analyses"][0]["role"], "bull")
            self.assertEqual(
                first.sha256,
                hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest(),
            )
            self.assertEqual(list(Path(directory).rglob("*.tmp")), [])

    def test_corrupt_existing_artifact_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = EvidenceArtifactStore(directory)
            manifest = store.write_case(
                case_key="case-1",
                evidence_bundle=_bundle(),
                role_analyses=[],
            )
            relative = manifest.uri.removeprefix("artifact://")
            (Path(directory) / relative).write_text("corrupt", encoding="utf-8")

            with self.assertRaises(EvidenceArtifactError):
                store.write_case(
                    case_key="case-1",
                    evidence_bundle=_bundle(),
                    role_analyses=[],
                )

    def test_read_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = EvidenceArtifactStore(directory)
            manifest = store.write_case(
                case_key="case-1",
                evidence_bundle=_bundle(),
                role_analyses=[],
            )
            escaped = type(manifest)(
                **{**manifest.to_dict(), "uri": "artifact://../outside.json"}
            )
            with self.assertRaises(EvidenceArtifactError):
                store.read(escaped)


class EvidenceDigestTest(unittest.TestCase):
    def test_digest_is_bounded_and_contains_no_raw_payload(self) -> None:
        digest = build_evidence_digest(_bundle(), [{"role": "bull"}])

        self.assertEqual(digest["domain_counts"], {"fundamentals": 1, "market": 1})
        self.assertEqual(digest["source_counts"], {"SEC": 1, "market.prices": 1})
        self.assertEqual(digest["external_evidence_ids"], ["EXT-NEWS-1"])
        self.assertEqual(
            digest["latest_filed_at"]["fundamentals"],
            "2026-08-01T12:00:00+00:00",
        )
        self.assertEqual(digest["role_analysis_count"], 1)
        serialized = canonical_json(digest)
        self.assertNotIn("긴 원문", serialized)
        self.assertNotIn("외부 원문", serialized)

    def test_successful_archive_keeps_only_manifest_and_digest_in_db_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = EvidenceArtifactStore(directory)
            archived = archive_case_evidence(
                case_key="case-1",
                evidence_bundle=_bundle(),
                role_analyses={"bull": {"summary": "상승"}},
                store=store,
                code_commit="abc123",
            )

            self.assertIsNotNone(archived.manifest)
            self.assertEqual(set(archived.evidence_bundle), {"_artifact", "_digest"})
            self.assertNotIn("evidence", archived.evidence_bundle)
            self.assertIn("_artifact", archived.evidence_bundle)
            self.assertIn("_digest", archived.evidence_bundle)
            self.assertEqual(archived.role_analyses, [])
            self.assertEqual(archived.manifest.code_commit, "abc123")
            payload = store.read(archived.manifest)
            self.assertEqual(payload["evidence_bundle"]["ticker"], "AAPL")
            self.assertEqual(payload["role_analyses"]["bull"]["summary"], "상승")

    def test_artifact_failure_returns_only_digest_and_error_metadata(self) -> None:
        class BrokenStore:
            def write_case(self, **_kwargs):
                raise EvidenceArtifactError("disk unavailable")

        archived = archive_case_evidence(
            case_key="case-1",
            evidence_bundle=_bundle(),
            role_analyses=[],
            store=BrokenStore(),  # type: ignore[arg-type]
        )

        self.assertIsNone(archived.manifest)
        self.assertEqual(set(archived.evidence_bundle), {"_digest", "_artifact_error"})
        self.assertNotIn("ticker", archived.evidence_bundle)
        self.assertIn("disk unavailable", archived.evidence_bundle["_artifact_error"])
        self.assertEqual(archived.role_analyses, [])
        self.assertIsNotNone(archived.artifact_error)


class EvidenceEntryIntegrationTest(unittest.TestCase):
    def test_shadow_entries_archive_evidence_before_case_save(self) -> None:
        root = Path(__file__).resolve().parents[4]
        entry_paths = (
            root / "src/investment_agent/trading/decision/portfolio_shadow.py",
            root / "src/investment_agent/trading/decision/shadow_daily.py",
        )

        for path in entry_paths:
            with self.subTest(entry=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertIn("archive_case_evidence(", source)
                self.assertIn('"evidence_bundle": archived.evidence_bundle', source)
                self.assertIn('"role_analyses": archived.role_analyses', source)


if __name__ == "__main__":
    unittest.main()
