"""운영 CLI와 하네스가 공유하는 저장소·상태 파일 위치."""
from __future__ import annotations

from investment_agent.platform.storage_paths import repository_root

REPOSITORY_ROOT = repository_root()
HARNESS_STATE_DIR = REPOSITORY_ROOT / "artifacts" / "ops" / "investment_harness"
