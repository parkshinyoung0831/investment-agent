from __future__ import annotations

import unittest

from postgrest.exceptions import APIError

from investment_agent.platform.retry import _is_retryable


class CommonRetryTests(unittest.TestCase):
    def test_transient_postgres_errors_are_retryable(self) -> None:
        for code in ("57014", "40001", "40P01", "PGRST003"):
            error = APIError({"message": "transient", "code": code})
            self.assertTrue(_is_retryable(error), code)

    def test_constraint_and_auth_errors_are_not_retryable(self) -> None:
        for code in ("23505", "23514", "42501", "PGRST301"):
            error = APIError({"message": "permanent", "code": code})
            self.assertFalse(_is_retryable(error), code)


if __name__ == "__main__":
    unittest.main()
