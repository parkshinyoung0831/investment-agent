"""파괴적 DB 도구는 대상을 확인할 수 없으면 연결하기 전에 거절하고, 검증 도구는 읽기만 한다(SC-03·SC-05)."""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load(name: str):
    """스크립트를 불러온다. import가 .env를 프로세스 환경에 올리므로 끝나면 되돌린다."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ):
        spec.loader.exec_module(module)
    return module


POOLER = "postgresql://postgres.abcdefghijklmnopqrst:pw@aws-0-x.pooler.supabase.com:6543/postgres"
DIRECT = "postgresql://postgres:pw@db.abcdefghijklmnopqrst.supabase.co:5432/postgres"
LOCAL = "postgresql://postgres:pw@127.0.0.1:5432/postgres"
# 비밀번호가 소문자 20자이면 예전 정규식은 그것을 project ref로 읽었다.
LOOKALIKE = "postgresql://postgres:abcdefghijklmnopqrst@10.0.0.5:5432/postgres"

project_ref = _load("project_ref")


class ProjectRefTest(unittest.TestCase):
    def test_reads_ref_from_pooler_and_direct_urls(self) -> None:
        self.assertEqual(project_ref.project_ref_from_db_url(POOLER), "abcdefghijklmnopqrst")
        self.assertEqual(project_ref.project_ref_from_db_url(DIRECT), "abcdefghijklmnopqrst")

    def test_an_unreadable_ref_is_refused_not_skipped(self) -> None:
        for url in (LOCAL, LOOKALIKE, ""):
            for confirm in ("anything", "", None):  # 빈 --confirm이 빈 ref와 "같아" 통과하면 안 된다
                with self.subTest(url=url, confirm=confirm):
                    with self.assertRaises(SystemExit):
                        project_ref.require_confirmation(url, confirm)

    def test_a_wrong_confirmation_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            project_ref.require_confirmation(POOLER, "another")
        with self.assertRaises(SystemExit):
            project_ref.require_confirmation(POOLER, None)
        self.assertEqual(project_ref.require_confirmation(POOLER, "abcdefghijklmnopqrst"), "abcdefghijklmnopqrst")


class NoConnectionBeforeConfirmationTest(unittest.TestCase):
    """확인이 실패하면 DB에 연결조차 하지 않는다."""

    def _assert_refused_without_connecting(self, module, call) -> None:
        with mock.patch.dict(os.environ, {"SUPABASE_DB_URL": LOCAL}), \
             mock.patch.object(module.psycopg2, "connect", side_effect=AssertionError("연결하면 안 된다")):
            with self.assertRaises(SystemExit):
                call()

    def test_db_bootstrap_apply(self) -> None:
        module = _load("db_bootstrap")
        self._assert_refused_without_connecting(
            module, lambda: module.cmd_apply(Namespace(confirm="anything", drop_first=True)),
        )

    def test_db_capacity_reclaim(self) -> None:
        module = _load("db_capacity")
        self._assert_refused_without_connecting(
            module, lambda: module.cmd_reclaim(Namespace(confirm="anything", tables=None)),
        )

    def test_v1_reset(self) -> None:
        module = _load("v1_reset")
        self._assert_refused_without_connecting(
            module, lambda: module.main(["--confirm-reset", "--confirm", "anything"]),
        )

    def test_v1_reset_requires_the_ref_argument(self) -> None:
        module = _load("v1_reset")
        with self.assertRaises(SystemExit):
            module.main(["--confirm-reset"])


class VerifyDataIsReadOnlyTest(unittest.TestCase):
    def test_session_is_read_only(self) -> None:
        module = _load("verify_data")
        conn = mock.MagicMock()
        with mock.patch.dict(os.environ, {"SUPABASE_DB_URL": LOCAL}), \
             mock.patch.object(module.psycopg2, "connect", return_value=conn), \
             mock.patch.object(module, "CHECKS", ()):
            module.main([])
        conn.set_session.assert_called_once_with(readonly=True, autocommit=True)


if __name__ == "__main__":
    unittest.main()
