"""설정을 명시적으로 읽는 자리.

실제 환경변수가 `.env`보다 우선하고, 필수 값은 호출 시점에 검증하며, 비밀값은 로그에
기록하지 않는다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping
from investment_agent.platform.storage_paths import repository_root

# 저장소 루트. 이 파일이 src/investment_agent/config.py이므로 두 단계 위다.
ROOT = repository_root()

# 모든 잡이 필요로 하는 값. 이것이 없으면 아무것도 할 수 없다.
REQUIRED_ALWAYS = ("SUPABASE_URL", "SUPABASE_SERVICE_KEY")


class ConfigError(RuntimeError):
    """설정이 없거나 모양이 틀렸다. 값 자체는 담지 않는다."""


@dataclass(frozen=True)
class Config:
    """이 실행이 쓰는 설정. 값은 프로세스 환경에서 온다."""

    env: Mapping[str, str]
    dotenv_path: Path | None
    dotenv_loaded: bool

    def get(self, name: str, default: str | None = None) -> str | None:
        value = self.env.get(name, default)
        return value if value is None else str(value).strip() or None

    def require(self, *names: str) -> tuple[str, ...]:
        """필요한 값을 지금 확인한다. 없으면 **이름만** 말하고 멈춘다."""
        missing = [name for name in names if not self.get(name)]
        if missing:
            raise ConfigError(f"required settings are missing: {', '.join(sorted(missing))}")
        return tuple(str(self.get(name)) for name in names)

    def flag(self, name: str, *, default: bool = False) -> bool:
        """켜짐/꺼짐 값. 모르는 값은 **꺼진 것으로 읽는다**(fail-closed).

        안전 플래그가 오타 하나로 켜지면 안 된다. 그래서 참으로 읽는 값만 열거한다.
        """
        raw = self.get(name)
        if raw is None:
            return default
        return raw.lower() in {"1", "true", "yes", "on"}


def load_config(
    *,
    dotenv_path: Path | None = None,
    use_dotenv: bool = True,
    environ: Mapping[str, str] | None = None,
) -> Config:
    """설정을 한 번 읽는다. **진입점에서만** 부른다.

    `use_dotenv=False`는 테스트용이다 — 로컬 `.env`가 테스트 결과를 바꾸지 못하게 한다.
    """
    source = os.environ if environ is None else environ
    path = dotenv_path or (ROOT / ".env")
    loaded = False
    if use_dotenv and environ is None and path.exists():
        from dotenv import load_dotenv

        # override=False: 실제 환경변수가 이긴다. CI에서 secrets가 .env에 지지 않도록.
        loaded = load_dotenv(path, override=False)
    return Config(env=dict(source), dotenv_path=path if path.exists() else None, dotenv_loaded=loaded)


@lru_cache(maxsize=1)
def default_config() -> Config:
    """진입점이 매번 넘기기 번거로운 자리를 위한 캐시.

    라이브러리 코드에서는 쓰지 않는다 — 쓰면 그 함수는 프로세스 환경에 묶여 테스트에서
    격리할 수 없게 된다. 인자로 받아라.
    """
    return load_config()


__all__ = ["Config", "ConfigError", "REQUIRED_ALWAYS", "ROOT", "default_config", "load_config"]
