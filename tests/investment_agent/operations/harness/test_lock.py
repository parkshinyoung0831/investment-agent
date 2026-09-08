from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from investment_agent.operations.harness.lock import DuplicateProcessError, ProcessFileLock


class ProcessFileLockTest(unittest.TestCase):
    def test_second_process_lock_is_rejected_and_release_allows_reacquire(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "harness.lock"
            first = ProcessFileLock(path)
            second = ProcessFileLock(path)
            first.acquire()
            try:
                with self.assertRaises(DuplicateProcessError):
                    second.acquire()
            finally:
                first.release()
            second.acquire()
            second.release()


if __name__ == "__main__":
    unittest.main()
