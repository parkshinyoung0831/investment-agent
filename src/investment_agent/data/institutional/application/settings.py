"""institutional 실행 설정."""
from __future__ import annotations

import os


def shadow_parser_enabled() -> bool:
    """edgartools shadow 대조를 켤지 여부(기본 off)."""
    return os.environ.get("GURUS_SHADOW_PARSER", "").strip().lower() in {
        "on", "1", "true", "yes",
    }


__all__ = ["shadow_parser_enabled"]
