"""설정은 명시적으로 읽고, 안전 플래그는 fail-closed다."""
from __future__ import annotations

import unittest
from pathlib import Path

from investment_agent.config import Config, ConfigError, load_config


class LoadConfigTest(unittest.TestCase):
    def test_explicit_environ_ignores_local_dotenv(self) -> None:
        """테스트가 개발자 기계의 .env에 물들지 않아야 한다."""
        config = load_config(environ={"SUPABASE_URL": "https://example.test"})
        self.assertEqual("https://example.test", config.get("SUPABASE_URL"))
        self.assertIsNone(config.get("SUPABASE_SERVICE_KEY"))
        self.assertFalse(config.dotenv_loaded)

    def test_require_names_what_is_missing_without_values(self) -> None:
        config = load_config(environ={"SUPABASE_URL": "https://example.test"})
        with self.assertRaises(ConfigError) as ctx:
            config.require("SUPABASE_URL", "SUPABASE_SERVICE_KEY")
        message = str(ctx.exception)
        self.assertIn("SUPABASE_SERVICE_KEY", message)
        # 값은 절대 메시지에 넣지 않는다.
        self.assertNotIn("https://example.test", message)

    def test_require_returns_values_when_present(self) -> None:
        config = load_config(environ={"A": "1", "B": "2"})
        self.assertEqual(("1", "2"), config.require("A", "B"))

    def test_blank_is_treated_as_missing(self) -> None:
        config = load_config(environ={"A": "   "})
        self.assertIsNone(config.get("A"))
        with self.assertRaises(ConfigError):
            config.require("A")

    def test_flag_is_fail_closed(self) -> None:
        """안전 플래그가 오타 하나로 켜지면 안 된다."""
        config = load_config(environ={
            "ON": "true", "ON2": "1", "ON3": "YES", "ON4": " On ",
            "OFF": "ture", "OFF2": "0", "OFF3": "", "OFF4": "enabled",
        })
        for name in ("ON", "ON2", "ON3", "ON4"):
            self.assertTrue(config.flag(name), name)
        for name in ("OFF", "OFF2", "OFF3", "OFF4"):
            self.assertFalse(config.flag(name), name)
        self.assertFalse(config.flag("MISSING"))
        self.assertTrue(config.flag("MISSING", default=True))


class PackageImportTest(unittest.TestCase):
    def test_package_import_has_no_side_effect(self) -> None:
        """패키지를 import하는 것만으로 환경이 바뀌면 안 된다."""
        source = Path("src/investment_agent/__init__.py").read_text(encoding="utf-8")
        for forbidden in ("load_dotenv", "os.environ[", "getenv"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
