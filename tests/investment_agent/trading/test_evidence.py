"""근거는 DB 밖에 있고, 조용히 바뀌면 읽을 때 걸려야 한다."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from investment_agent.platform.artifacts import LocalArtifactStore, StorageError
from investment_agent.trading.evidence.bundle import (
    SCHEMA_VERSION,
    EvidenceError,
    load,
    store,
)

CASE = "1:2026-09-05:h20:abc123"
PAYLOAD = {"price": 100.0, "signals": {"rsi": 55.0}, "news": ["a", "b"]}


class StoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.backend = LocalArtifactStore(Path(self._dir.name))

    def test_the_row_carries_an_address_not_the_payload(self) -> None:
        row = store(self.backend, case_key=CASE, evidence_kind="bundle", payload=PAYLOAD).as_row()
        self.assertEqual(
            {"case_key", "evidence_kind", "schema_version",
             "artifact_uri", "sha256", "byte_size", "media_type"},
            set(row),
        )
        self.assertNotIn("price", str(row))

    def test_a_roundtrip_returns_the_same_payload(self) -> None:
        row = store(self.backend, case_key=CASE, evidence_kind="bundle", payload=PAYLOAD).as_row()
        self.assertEqual(PAYLOAD, load(self.backend, row))

    def test_an_empty_payload_is_refused(self) -> None:
        """빈 근거를 저장하면 '근거가 있다'고 기록되면서 실제로는 없다."""
        with self.assertRaises(EvidenceError):
            store(self.backend, case_key=CASE, evidence_kind="bundle", payload={})

    def test_an_unknown_kind_is_refused(self) -> None:
        with self.assertRaises(EvidenceError):
            store(self.backend, case_key=CASE, evidence_kind="notes", payload=PAYLOAD)

    def test_the_two_kinds_are_stored_separately(self) -> None:
        """한 파일로 합치면 목록 화면이 역할 의견까지 통째로 받는다."""
        bundle = store(self.backend, case_key=CASE, evidence_kind="bundle", payload=PAYLOAD)
        roles = store(self.backend, case_key=CASE, evidence_kind="role_analyses",
                      payload={"bull": "buy", "bear": "sell"})
        self.assertNotEqual(bundle.ref.uri, roles.ref.uri)


class IntegrityTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.backend = LocalArtifactStore(Path(self._dir.name))
        self.row = store(
            self.backend, case_key=CASE, evidence_kind="bundle", payload=PAYLOAD
        ).as_row()

    def test_a_tampered_file_is_refused(self) -> None:
        """'그때 본 근거'가 조용히 바뀌면 판단 기록 전체가 거짓이 된다."""
        stored = next(p for p in Path(self._dir.name).rglob("*") if p.is_file())
        stored.write_bytes(b'{"price": 1.0}')
        with self.assertRaises(StorageError):
            load(self.backend, self.row)

    def test_a_missing_file_is_a_clear_error(self) -> None:
        for path in Path(self._dir.name).rglob("*"):
            if path.is_file():
                path.unlink()
        with self.assertRaises(StorageError):
            load(self.backend, self.row)

    def test_an_older_schema_generation_is_refused(self) -> None:
        """세대가 다른 근거를 지금 규칙으로 읽으면 필드가 조용히 비거나 뜻이 달라진다."""
        with self.assertRaises(EvidenceError):
            load(self.backend, {**self.row, "schema_version": "0"})

    def test_the_current_generation_reads_fine(self) -> None:
        self.assertEqual(SCHEMA_VERSION, self.row["schema_version"])
        self.assertEqual(PAYLOAD, load(self.backend, self.row))


if __name__ == "__main__":
    unittest.main()
