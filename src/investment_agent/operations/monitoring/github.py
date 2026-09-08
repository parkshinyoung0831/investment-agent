"""GitHub Actions step output helper. 로컬 실행에서는 조용히 no-op."""
from __future__ import annotations

import os
from pathlib import Path


def write_changed_output(changed: bool) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT", "").strip()
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write(f"changed={'true' if changed else 'false'}\n")
