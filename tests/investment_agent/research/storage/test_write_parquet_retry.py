"""`_write_parquet`이 Windows의 일시적 파일 잠금을 재시도로 넘기는지 검증한다.

실제로 겪은 오류: 방금 만든 임시 파일을 백신 실시간 검사가 짧게 잠가 DuckDB의 내부
rename이 "액세스가 거부되었습니다"로 실패했다. 디스크 내용 문제가 아니라 타이밍
문제라 몇 번 안에 저절로 풀린다.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import duckdb

from investment_agent.research.storage.repository import ResearchStore


class _FlakyConnection:
    """앞 N번은 IOException을 던지고 그 뒤엔 진짜 연결에 위임한다."""

    def __init__(self, real, *, fail_times: int):
        self._real = real
        self._fail_times = fail_times
        self.attempts = 0

    def execute(self, sql, *args, **kwargs):
        if sql.strip().upper().startswith("COPY"):
            self.attempts += 1
            if self.attempts <= self._fail_times:
                raise duckdb.IOException("IO Error: Could not move file: 액세스가 거부되었습니다.")
        return self._real.execute(sql, *args, **kwargs)


class WriteParquetRetryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.connection = duckdb.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.execute("CREATE TABLE t AS SELECT 1 AS x")

    def test_a_transient_failure_is_retried_and_succeeds(self) -> None:
        target = Path(self.temp.name) / "out.parquet"
        flaky = _FlakyConnection(self.connection, fail_times=2)
        ResearchStore._write_parquet(flaky, "t", target)
        self.assertTrue(target.is_file())
        self.assertEqual(flaky.attempts, 3)

    def test_it_gives_up_and_raises_after_repeated_failures(self) -> None:
        target = Path(self.temp.name) / "out.parquet"
        flaky = _FlakyConnection(self.connection, fail_times=99)
        with self.assertRaises(duckdb.IOException):
            ResearchStore._write_parquet(flaky, "t", target)
        self.assertFalse(target.exists())



class InterruptedWriteLeftoverTest(unittest.TestCase):
    def test_a_leftover_temporary_file_is_not_read_as_a_second_copy(self) -> None:
        """중단된 COPY가 남긴 `tmp_data.*.parquet`를 읽으면 같은 표본이 두 벌이 돼 학습 export가 멈춘다."""
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.duckdb")
            store.upsert_records("probe_rows", [{"record_key": "a", "ticker": "AAA",
                                                  "as_of_at": "2022-01-07T23:30:00+00:00"}], key="record_key")
            partition = next(store._dataset_root("probe_rows").glob("year=*"))
            (partition / "tmp_data.leftover.parquet").write_bytes((partition / "data.parquet").read_bytes())
            reader = ResearchStore(Path(directory) / "research.duckdb", read_only=True)
            self.assertEqual(1, len(reader.records("probe_rows")))

    def test_a_reader_holding_the_file_delays_the_swap_instead_of_failing_it(self) -> None:
        """Windows에서 하네스가 파일을 읽는 동안 교체가 거부된다. 짧은 잠금은 기다려서 넘긴다."""
        from unittest import mock

        from investment_agent.research.storage import repository

        real_replace = repository.os.replace
        calls = {"n": 0}

        def locked_twice(source, target):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise PermissionError(5, "액세스가 거부되었습니다")
            return real_replace(source, target)

        with tempfile.TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection,                 mock.patch.object(repository.os, "replace", side_effect=locked_twice),                 mock.patch.object(repository.time, "sleep"):
            connection.execute("CREATE TABLE t AS SELECT 1 AS x")
            target = Path(directory) / "out.parquet"
            ResearchStore._write_parquet(connection, "t", target)
            self.assertTrue(target.is_file())
        self.assertEqual(3, calls["n"])


if __name__ == "__main__":
    unittest.main()
