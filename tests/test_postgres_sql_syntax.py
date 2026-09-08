"""db/postgres/v1/*.sql이 pglast로 파싱 가능한지 오프라인으로 확인한다."""
from __future__ import annotations

import unittest

from scripts.verify_postgres_sql_syntax import check_all, sql_files


class PostgresSqlSyntaxTest(unittest.TestCase):
    def test_every_declared_file_parses(self) -> None:
        self.assertGreater(len(sql_files()), 0, "db/postgres/v1/*.sql이 비어 있다")
        self.assertEqual([], check_all())


if __name__ == "__main__":
    unittest.main()
