from __future__ import annotations

import unittest

from investment_agent.operations.harness.reporting import HarnessReporter


class FakeLogger:
    def __init__(self):
        self.lines: list[str] = []

    def info(self, pattern, value):
        self.lines.append(pattern % value)

    def error(self, pattern, value):
        self.lines.append(pattern % value)


class FakeAlerts:
    def __init__(self):
        self.events: list[dict] = []

    def send(self, event):
        self.events.append(dict(event))
        return True


class HarnessReporterTest(unittest.TestCase):
    def test_structured_log_and_alert_redact_secret_key_values(self):
        logger = FakeLogger()
        alerts = FakeAlerts()
        reporter = HarnessReporter(logger=logger, alerts=alerts)
        reporter.error("adapter_failed", bot_token="secret-value", safe="ok")
        self.assertIn("harness_event=", logger.lines[0])
        self.assertNotIn("secret-value", logger.lines[0])
        self.assertEqual(alerts.events[0]["bot_token"], "[REDACTED]")


if __name__ == "__main__":
    unittest.main()
