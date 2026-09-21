"""보안 사전점검의 두 공허한 통과를 막는다.

- `.gitignore` 점검이 부분 문자열이라 `!.env.example` 한 줄만 있어도 PASS였다(감사 OP2-13).
- 봇 토큰 분리 점검이 일반 토큰이 없으면 항목을 **하나도 내지 않아**, 읽는 사람이
  "분리를 통과했다"와 "확인하지 않았다"를 구별할 수 없었다(감사 OP2-14).
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from investment_agent.operations.harness.contracts import HarnessMode
from investment_agent.operations.harness.security_audit import (
    CheckStatus,
    _check_discord_security,
    _check_secrets_exposure,
)


def _codes(results) -> dict[str, CheckStatus]:
    return {result.code: result.status for result in results}


class GitignoreCheckTest(unittest.TestCase):
    def _run(self, gitignore: str) -> dict[str, CheckStatus]:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".gitignore").write_text(gitignore, encoding="utf-8")
            return _codes(_check_secrets_exposure(root))

    def test_the_real_repository_gitignore_passes(self):
        codes = self._run(".env\n.env.*\n!.env.example\nartifacts/\n")
        self.assertEqual(codes.get("GITIGNORE_SECRETS_PROTECTED"), CheckStatus.PASS)

    def test_a_negation_line_alone_does_not_count_as_protection(self):
        codes = self._run("!.env.example\nartifacts/\n")
        self.assertEqual(codes.get("GITIGNORE_SECRETS_MISSING"), CheckStatus.FAIL)

    def test_a_comment_mentioning_env_does_not_count(self):
        codes = self._run("# .env 는 커밋하지 마세요\nartifacts/\n")
        self.assertEqual(codes.get("GITIGNORE_SECRETS_MISSING"), CheckStatus.FAIL)

    def test_a_different_path_containing_artifacts_does_not_count(self):
        codes = self._run(".env\ndata/local/artifacts/cache\n")
        self.assertEqual(codes.get("GITIGNORE_SECRETS_MISSING"), CheckStatus.FAIL)


class BotTokenSeparationCheckTest(unittest.TestCase):
    def _run(self, environ: dict[str, str]) -> dict[str, CheckStatus]:
        return _codes(_check_discord_security(environ, HarnessMode.ANALYSIS_ONLY))

    def test_separated_tokens_pass(self):
        codes = self._run({"DISCORD_BOT_TOKEN": "a", "DISCORD_APPROVAL_BOT_TOKEN": "b"})
        self.assertEqual(codes.get("DISCORD_BOT_TOKENS_SEPARATED"), CheckStatus.PASS)

    def test_identical_tokens_fail(self):
        codes = self._run({"DISCORD_BOT_TOKEN": "a", "DISCORD_APPROVAL_BOT_TOKEN": "a"})
        self.assertEqual(codes.get("DISCORD_BOT_TOKENS_IDENTICAL"), CheckStatus.FAIL)

    def test_an_unverifiable_configuration_says_so_instead_of_vanishing(self):
        codes = self._run({"DISCORD_APPROVAL_BOT_TOKEN": "b"})
        self.assertEqual(codes.get("DISCORD_BOT_TOKENS_UNVERIFIED"), CheckStatus.WARN)


if __name__ == "__main__":
    unittest.main()
