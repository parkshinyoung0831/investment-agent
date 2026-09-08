from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

from investment_agent.platform.storage_paths import (
    intelligence_database_path,
    intelligence_parquet_root,
    legacy_candidates,
    local_artifact_root,
    local_data_root,
    market_change_manifest_path,
    research_root,
    runtime_database_path,
)


PATH_ENVIRON = {
    "AI_INVESTOR_LOCAL_DATA_ROOT": "",
    "AI_INVESTOR_LOCAL_ARTIFACT_ROOT": "",
    "AI_INVESTOR_INTELLIGENCE_DB_PATH": "",
    "AI_INVESTOR_INTELLIGENCE_PARQUET_ROOT": "",
    "INVESTMENT_AGENT_RESEARCH_ROOT": "",
    "AI_INVESTOR_RUNTIME_DB_PATH": "",
    "AI_INVESTOR_MARKET_CHANGE_MANIFEST_PATH": "",
}


class StoragePathsTest(unittest.TestCase):
    def test_default_paths_are_grouped_by_store(self) -> None:
        with patch.dict(os.environ, PATH_ENVIRON):
            self.assertEqual(Path("data/local"), local_data_root())
            self.assertEqual(
                Path("data/local/intelligence/intelligence.duckdb"),
                intelligence_database_path(),
            )
            self.assertEqual(
                Path("data/local/intelligence/parquet"),
                intelligence_parquet_root(),
            )
            self.assertEqual(Path("data/local/research"), research_root())
            self.assertEqual(
                Path("data/local/runtime/runtime.sqlite3"),
                runtime_database_path(),
            )
            self.assertEqual(Path("data/local/artifacts"), local_artifact_root())
            self.assertEqual(
                Path("data/local/artifacts/market_change_manifest.json"),
                market_change_manifest_path(),
            )

    def test_store_specific_path_wins_over_local_root(self) -> None:
        configured = {
            **PATH_ENVIRON,
            "AI_INVESTOR_LOCAL_DATA_ROOT": "D:/investment-data",
            "AI_INVESTOR_RUNTIME_DB_PATH": "D:/ledger/runtime.sqlite3",
        }
        with patch.dict(os.environ, configured):
            self.assertEqual(Path("D:/ledger/runtime.sqlite3"), runtime_database_path())
            self.assertEqual(
                Path("D:/investment-data/intelligence/intelligence.duckdb"),
                intelligence_database_path(),
            )

    def test_explicit_parquet_root_wins_for_an_isolated_database(self) -> None:
        configured = {
            **PATH_ENVIRON,
            "AI_INVESTOR_INTELLIGENCE_PARQUET_ROOT": "D:/archives/intelligence",
        }
        with patch.dict(os.environ, configured):
            self.assertEqual(
                Path("D:/archives/intelligence"),
                intelligence_parquet_root(Path("D:/tests/intelligence.duckdb")),
            )

    def test_legacy_candidates_preserve_previous_defaults(self) -> None:
        self.assertEqual(
            (Path("data/local/intelligence.duckdb"),),
            legacy_candidates("intelligence"),
        )
        self.assertEqual(
            (Path("artifacts/research/research.duckdb"),),
            legacy_candidates("research"),
        )
        self.assertEqual(
            (Path("data/local/runtime.sqlite3"),),
            legacy_candidates("runtime"),
        )
        with self.assertRaisesRegex(ValueError, "unknown local store"):
            legacy_candidates("missing")



class EveryLocalStoreFollowsTheDataRootTest(unittest.TestCase):
    """`AI_INVESTOR_LOCAL_DATA_ROOT`를 옮기면 로컬 저장소가 전부 따라와야 한다.

    뉴스·소셜 lazy cache만 모듈 상수로 경로가 박혀 있어서, 로컬 데이터를 옮겨도
    그 파일 하나만 옛 자리에 남았다. "옮겼는데 하나가 안 따라온다"는 에러 없이
    조용하다 — 옛 자리의 캐시를 계속 읽고 쓴다.
    """

    def test_relocating_the_data_root_moves_every_store(self) -> None:
        from investment_agent.platform import storage_paths

        movers = (
            storage_paths.intelligence_database_path,
            storage_paths.research_database_path,
            storage_paths.runtime_database_path,
            storage_paths.evidence_cache_path,
            storage_paths.local_artifact_root,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "elsewhere"
            with mock.patch.dict(
                os.environ,
                {storage_paths.LOCAL_DATA_ROOT_ENV: str(root)},
                clear=False,
            ):
                for resolve in movers:
                    with self.subTest(store=resolve.__name__):
                        self.assertTrue(
                            root in resolve().parents,
                            f"{resolve.__name__}() -> {resolve()}",
                        )

if __name__ == "__main__":
    unittest.main()
