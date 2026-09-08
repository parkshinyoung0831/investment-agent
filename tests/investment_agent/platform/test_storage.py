"""근거는 내용 주소로 쌓이고, 바뀌면 읽을 때 걸린다."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from investment_agent.platform.artifacts import (
    ArtifactRef,
    LocalArtifactStore,
    StorageError,
)


class LocalArtifactStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.store = LocalArtifactStore(Path(self._dir.name))

    def test_roundtrip_returns_the_same_value(self) -> None:
        payload = {"ticker": "AAPL", "signals": [1, 2, 3]}
        ref = self.store.put_json("evidence", payload)
        self.assertEqual(payload, self.store.get_json(ref))

    def test_same_content_is_stored_once(self) -> None:
        first = self.store.put_json("evidence", {"a": 1})
        second = self.store.put_json("evidence", {"a": 1})
        self.assertEqual(first.uri, second.uri)
        files = list(Path(self._dir.name).rglob("*"))
        self.assertEqual(1, len([f for f in files if f.is_file()]))

    def test_key_order_does_not_change_the_address(self) -> None:
        """canonical JSON으로 저장하지 않으면 같은 근거가 두 지문을 갖는다."""
        self.assertEqual(
            self.store.put_json("evidence", {"a": 1, "b": 2}).sha256,
            self.store.put_json("evidence", {"b": 2, "a": 1}).sha256,
        )

    def test_row_shape_matches_what_the_db_stores(self) -> None:
        row = self.store.put_json("evidence", {"a": 1}).as_row()
        self.assertEqual({"artifact_uri", "sha256", "byte_size", "media_type"}, set(row))
        self.assertGreater(row["byte_size"], 0)
        # 내용 자체는 절대 행에 들어가지 않는다.
        self.assertNotIn("payload", row)

    def test_tampered_file_is_refused(self) -> None:
        """'그때 본 근거'가 조용히 바뀌면 판단 기록 전체가 거짓이 된다."""
        ref = self.store.put_json("evidence", {"a": 1})
        stored = next(p for p in Path(self._dir.name).rglob("*") if p.is_file())
        stored.write_bytes(b'{"a":2}')
        with self.assertRaises(StorageError):
            self.store.get_json(ref)

    def test_missing_file_is_a_clear_error(self) -> None:
        ref = ArtifactRef(uri="local://evidence/" + "0" * 64, sha256="0" * 64, byte_size=0)
        with self.assertRaises(StorageError):
            self.store.get_bytes(ref)

    def test_path_traversal_is_refused(self) -> None:
        for uri in ("local://../secrets/" + "a" * 64, "local://evidence/../../x", "s3://evidence/" + "a" * 64):
            with self.assertRaises(StorageError):
                self.store.get_bytes(ArtifactRef(uri=uri, sha256="a" * 64, byte_size=1))

    def test_no_temporary_file_is_left_behind(self) -> None:
        self.store.put_json("evidence", {"a": 1})
        leftovers = [p.name for p in Path(self._dir.name).rglob("*.tmp")]
        self.assertEqual([], leftovers)


if __name__ == "__main__":
    unittest.main()
