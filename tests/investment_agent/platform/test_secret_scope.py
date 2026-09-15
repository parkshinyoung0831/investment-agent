"""판단 범위 프로세스는 `.env`를 다시 읽어도 broker·승인 비밀을 갖지 못한다."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from investment_agent.config import load_config
from investment_agent.platform.secret_scope import (
    EXECUTION_SECRET_NAMES,
    SCOPE_ENV,
    SecretScopeError,
    environ_for_scope,
    strip_out_of_scope_secrets,
)

SECRETS = {name: "value" for name in EXECUTION_SECRET_NAMES}


class SecretScopeTest(unittest.TestCase):
    def test_unknown_scope_is_treated_as_analysis(self):
        child = environ_for_scope({**SECRETS, "SUPABASE_URL": "u"}, "anything")
        self.assertEqual(child, {"SUPABASE_URL": "u", SCOPE_ENV: "analysis"})

    def test_execution_scope_keeps_every_secret(self):
        child = environ_for_scope(SECRETS, "execution")
        self.assertTrue(EXECUTION_SECRET_NAMES <= set(child))

    def test_manual_process_without_scope_keeps_its_environment(self):
        environ = dict(SECRETS)
        self.assertEqual(strip_out_of_scope_secrets(environ), ())
        self.assertEqual(environ, SECRETS)

    def test_dotenv_reload_in_analysis_scope_does_not_bring_secrets_back(self):
        with tempfile.TemporaryDirectory() as directory:
            dotenv = Path(directory) / ".env"
            dotenv.write_text("TOSS_CLIENT_SECRET=from-dotenv\nAI_INVESTOR_MODEL=m\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {SCOPE_ENV: "analysis"}, clear=True):
                config = load_config(dotenv_path=dotenv)
                self.assertNotIn("TOSS_CLIENT_SECRET", os.environ)
                self.assertIsNone(config.get("TOSS_CLIENT_SECRET"))
                self.assertEqual(config.get("AI_INVESTOR_MODEL"), "m")

    def test_bootstrap_strips_secrets_loaded_from_dotenv(self):
        from investment_agent import bootstrap

        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".env").write_text("DISCORD_APPROVAL_BOT_TOKEN=t\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {SCOPE_ENV: "analysis"}, clear=True), \
                    mock.patch.object(bootstrap, "repository_root", return_value=Path(directory)), \
                    mock.patch("investment_agent.platform.logging.configure_logging"):
                bootstrap.start_cli()
                self.assertNotIn("DISCORD_APPROVAL_BOT_TOKEN", os.environ)

    def test_broker_authentication_refuses_the_analysis_scope(self):
        from investment_agent.execution.brokers.toss import auth

        with mock.patch.dict(os.environ, {SCOPE_ENV: "analysis", "TOSS_CLIENT_ID": "i",
                                          "TOSS_CLIENT_SECRET": "s"}, clear=True):
            with self.assertRaises(SecretScopeError):
                auth.get_token_manager()

    def test_approval_signing_secret_refuses_the_analysis_scope(self):
        from investment_agent.execution.approval.secret import load_or_create_approval_secret

        with mock.patch.dict(os.environ, {SCOPE_ENV: "analysis"}, clear=True):
            with self.assertRaises(SecretScopeError):
                load_or_create_approval_secret()


if __name__ == "__main__":
    unittest.main()
