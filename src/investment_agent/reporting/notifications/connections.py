"""Reporting·알림 read path 연결 조립."""
from __future__ import annotations

from typing import Any

from investment_agent.config import Config, load_config
from investment_agent.platform.db.postgres import Database


def configured_database(config: Config | None = None) -> Any:
    """operations 경계에서 설정된 v1 adapter를 만든다."""
    return Database.from_config(config or load_config())
