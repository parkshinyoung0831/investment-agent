"""여러 LLM provider를 하루 요청 한도 안에서 종목 단위로 회전한다.

단일 모델(예: Gemini 무료 등급)의 분당 토큰·일일 요청 한도는 종목 하나(LLM 호출
10~15건)를 며칠에 걸쳐도 못 채울 만큼 작다. 여기서는 provider별 하루 요청 한도를
"종목당 예상 호출수"로 나눠 "그 모델로 오늘 몇 종목을 더 태울 수 있는가"로 바꾸고,
`external_usage.py`가 이미 쓰는 원자적 SQLite 예약을 그대로 재사용해 종목 시작
직전에 한 자리를 예약한다. 예약에 성공한 모델로 그 종목의 분석 전체(LLM 호출
10~15건)를 진행한다 — 실행 도중 모델을 바꾸는 것은 벤더 라이브러리(TradingAgents)
내부 그래프 구성을 건드려야 해서 하지 않는다. 그 모델이 중간에 실패하면 호출부가
다음 후보로 그 종목을 다시 시도한다.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

from investment_agent.platform.external_usage import ExternalUsageError, reserve_provider_call

# 실측: 한 종목이 researcher·시장/펀더멘털/거시 애널리스트·회의론자·PM에 더해
# bull/bear 토론·트레이더·리스크 토론까지 거치면 LLM 호출이 10건을 넘는다.
# 넉넉하게 잡아야 "예약은 됐는데 중간에 그 모델의 실제 한도가 먼저 바닥나는" 일이 줄어든다.
CALLS_PER_TICKER_ESTIMATE = 15

_ENV_KEYS = (
    "AI_INVESTOR_PROVIDER",
    "AI_INVESTOR_BASE_URL",
    "AI_INVESTOR_MODEL",
    "AI_INVESTOR_QUICK_MODEL",
    "AI_INVESTOR_DEEP_MODEL",
    "AI_INVESTOR_API_KEY",
    "AI_INVESTOR_TRADINGAGENTS_PROVIDER",
)


class ModelPoolError(RuntimeError):
    """풀 후보를 안전하게 적용할 수 없을 때 발생한다."""


@dataclass(frozen=True)
class ModelCandidate:
    """회전 풀의 항목 하나 — 어떤 provider의 어떤 모델을 어떤 키로 부르는가."""

    name: str
    base_url: str
    model: str
    provider: str
    tradingagents_provider: str
    api_key_env: str
    # provider가 실제로 광고하는 하루 HTTP 요청 한도. 종목 단위 한도가 아니다 —
    # select_model_for_ticker가 CALLS_PER_TICKER_ESTIMATE로 나눠 환산한다.
    daily_request_limit: int

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ValueError("model candidate name is required")
        if int(self.daily_request_limit) < 1:
            raise ValueError("daily_request_limit must be positive")

    @property
    def daily_ticker_budget(self) -> int:
        """이 모델로 오늘 새로 시작할 수 있는 종목 수. 0이면 하루 안에 하나도 못 태운다."""
        return max(0, int(self.daily_request_limit) // CALLS_PER_TICKER_ESTIMATE)


_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
_GEMINI_API_KEY_ENV = "AI_INVESTOR_GEMINI_API_KEY"


def gemini_candidate(model: str, *, daily_request_limit: int) -> ModelCandidate:
    return ModelCandidate(
        name=model,
        base_url=_GEMINI_BASE_URL,
        model=model,
        provider="openai_compatible",
        # google 네이티브 SDK 경로가 아니라 openai 호환 chat/completions로 부른다
        # Gemini의 OpenAI 호환 엔드포인트를 사용하면 provider adapter 계약을 공유할 수 있다.
        tradingagents_provider="openai",
        api_key_env=_GEMINI_API_KEY_ENV,
        daily_request_limit=daily_request_limit,
    )


def _azure(model: str, *, daily_request_limit: int) -> ModelCandidate:
    return ModelCandidate(
        name=f"azure-{model}",
        base_url=os.environ.get(
            "AZURE_AI_BASE_URL", "https://investment-agent-foundry.openai.azure.com/openai/v1"
        ),
        model=model,
        provider="openai_compatible",
        tradingagents_provider="openai",
        api_key_env="AI_INVESTOR_AZURE_API_KEY",
        daily_request_limit=daily_request_limit,
    )


GROQ_BASE_URL = "https://api.groq.com/openai/v1"
# 실측 2026-09-03: 무료(on_demand) 등급의 분당 토큰 한도. 종목 하나의 프롬프트가
# 이 한도의 몇 배라 free tier로는 한 호출도 통과하지 못한다(413).
GROQ_FREE_TIER_TPM = 8000


def groq_candidate(model: str, *, daily_request_limit: int) -> ModelCandidate:
    """Groq 후보를 만든다. 유료 등급으로 올린 뒤 DEFAULT_POOL에 넣으면 된다.

    도구 호출 자체는 `openai/gpt-oss-20b`·`-120b`·`qwen/qwen3.6-27b`에서 확인했다
    (`groq/compound*`는 tool calling 미지원). 막는 것은 모델이 아니라 등급의 TPM이다.
    """
    return ModelCandidate(
        name=f"groq-{model}",
        base_url=GROQ_BASE_URL,
        model=model,
        provider="openai_compatible",
        tradingagents_provider="openai",
        api_key_env="GROQ_API_KEY",
        daily_request_limit=daily_request_limit,
    )


def _azure_daily_requests() -> int:
    """Foundry는 pay-as-you-go라 provider가 거는 일일 요청 상한이 없다.

    그래서 이 값은 provider의 한도가 아니라 **우리가 거는 지출 가드**다. 크레딧을
    하루에 다 태우지 않도록 기본값을 두고, 환경변수로 올린다.
    """
    raw = os.environ.get("AI_INVESTOR_AZURE_DAILY_REQUESTS", "").strip()
    if not raw:
        return 300
    value = int(raw)
    if value < 1:
        raise ValueError("AI_INVESTOR_AZURE_DAILY_REQUESTS must be positive")
    return value


# 실측(2026-09-03)으로 세 provider를 모두 시험한 뒤 Azure 하나로 단일화했다.
# 판정 기준은 "도구 호출 2턴"과 "실제 evidence bundle 크기" 둘 다다.
#
# Azure  gpt-5-mini        : 둘 다 통과. 이 리소스에 배포된 유일한 모델이다.
#                            `/models`가 돌려주는 407개는 지역 카탈로그일 뿐이라
#                            gpt-4.1-nano·gpt-5-nano·DeepSeek-V4-Flash 등은 전부
#                            DeploymentNotFound(404)다.
# Gemini gemini-2.5-flash  : 도구 호출은 통과하나 무료 등급 하루 요청 한도가 작아
#                            종목 하나를 넘기지 못한다. `gemini_candidate()`로 남겨 둔다.
# Groq   openai/gpt-oss-*  : 도구 호출은 통과하지만 무료 TPM이 8,000이라 프롬프트
#                            자체가 413으로 거부된다. `groq_candidate()`로 남겨 둔다.
#
# 후보가 하나면 한 provider가 죽었을 때 그 종목은 실패한다 — 대신 "어느 키로 불렀는지"가
# 항상 분명해진다. 여러 후보를 섞던 동안 앞 후보의 키가 다음 후보로 새는 버그가 있었다.
DEFAULT_POOL: tuple[ModelCandidate, ...] = (
    _azure("gpt-5-mini", daily_request_limit=_azure_daily_requests()),
)


def select_model_for_ticker(
    pool: Sequence[ModelCandidate],
    *,
    ledger_path: Path | str,
    now: datetime | None = None,
    exclude: frozenset[str] = frozenset(),
) -> ModelCandidate | None:
    """오늘치 예산이 남아 있고 API 키가 설정된 첫 후보를 예약하고 돌려준다.

    예약은 원자적이라 같은 순간에 여러 프로세스가 불러도 한 자리씩만 나간다.
    `exclude`는 같은 종목에서 이미 실패해 다시 고르면 안 되는 이름이다 — 없으면
    예산이 남은 고장난 모델을 예산이 바닥날 때까지 계속 다시 고르게 된다.
    모든 후보가 소진·제외됐거나 키가 없으면 None — 호출부는 그 종목을 시도조차 하지 않는다.
    """
    point = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    for candidate in pool:
        if candidate.name in exclude:
            continue
        if not os.environ.get(candidate.api_key_env, "").strip():
            continue
        budget = candidate.daily_ticker_budget
        if budget < 1:
            continue
        reservation = reserve_provider_call(
            ledger_path, provider=_ledger_key(candidate.name), cap=budget, now=point,
        )
        if reservation.allowed:
            return candidate
    return None


def _ledger_key(name: str) -> str:
    """모델 id의 점(.)은 provider 이름 정규식이 허용하지 않아 하이픈으로 바꾼다."""
    return name.strip().lower().replace(".", "-")


@contextmanager
def apply_candidate(candidate: ModelCandidate) -> Iterator[None]:
    """이 블록 동안만 `AI_INVESTOR_*` 환경변수를 후보 설정으로 덮는다.

    `_config()`/`OpenAICompatibleClient.from_env()`가 매 호출마다 환경변수를 새로
    읽으므로, 이 블록 안에서 `engine.run(...)`을 부르면 그 종목 전체가 이 후보로 간다.
    """
    api_key = os.environ.get(candidate.api_key_env, "").strip()
    if not api_key:
        raise ModelPoolError(
            f"{candidate.api_key_env} is not set; refusing to send an unauthenticated request"
        )
    saved = {key: os.environ.get(key) for key in _ENV_KEYS}
    os.environ.update({
        "AI_INVESTOR_PROVIDER": candidate.provider,
        "AI_INVESTOR_BASE_URL": candidate.base_url,
        "AI_INVESTOR_MODEL": candidate.model,
        "AI_INVESTOR_QUICK_MODEL": candidate.model,
        "AI_INVESTOR_DEEP_MODEL": candidate.model,
        "AI_INVESTOR_API_KEY": api_key,
        "AI_INVESTOR_TRADINGAGENTS_PROVIDER": candidate.tradingagents_provider,
    })
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


__all__ = [
    "CALLS_PER_TICKER_ESTIMATE",
    "DEFAULT_POOL",
    "GROQ_BASE_URL",
    "GROQ_FREE_TIER_TPM",
    "gemini_candidate",
    "groq_candidate",
    "ExternalUsageError",
    "ModelCandidate",
    "ModelPoolError",
    "apply_candidate",
    "select_model_for_ticker",
]
