"""OpenAI 호환 로컬·원격 LLM 호출 어댑터."""
from __future__ import annotations

import json
import os
import re
from typing import Any, Mapping, Protocol

import httpx


class LLMClient(Protocol):
    provider: str
    model: str

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        output_schema: Mapping[str, Any],
        task_name: str,
    ) -> dict[str, Any]: ...


# gpt-5 계열과 o-시리즈는 temperature를 기본값(1)에서 바꾸지 못한다. 보내면 400이다
# (실측 2026-09-03, Azure gpt-5-mini: "Only the default (1) value is supported").
_FIXED_TEMPERATURE_MODEL = re.compile(r"^(gpt-5|o[1-9])")
DEFAULT_TEMPERATURE = 0.1


def supports_custom_temperature(model: str) -> bool:
    """이 모델에 temperature를 실어 보내도 되는가."""
    return _FIXED_TEMPERATURE_MODEL.match(str(model).strip().lower()) is None


def _response_detail(response: Any) -> str:
    """provider가 돌려준 거절 사유를 짧게 뽑는다. 본문이 없으면 그렇다고 적는다."""
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - 본문이 JSON이 아닐 수 있다
        text = str(getattr(response, "text", "") or "").strip()
        return text[:300] or "<no response body>"
    if isinstance(body, Mapping):
        error = body.get("error")
        if isinstance(error, Mapping) and error.get("message"):
            return str(error["message"])[:300]
    return json.dumps(body, ensure_ascii=False)[:300]


def _parse_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM returned invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("LLM output must be a JSON object")
    return value


class OpenAICompatibleClient:
    """Ollama·LM Studio·OpenAI 호환 chat/completions 클라이언트."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        provider: str = "openai_compatible",
        timeout_sec: float = 180.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.provider = provider
        self.api_key = api_key
        self.timeout_sec = timeout_sec

    @classmethod
    def from_env(cls) -> "OpenAICompatibleClient":
        base_url = os.environ.get("AI_INVESTOR_BASE_URL", "").strip()
        model = os.environ.get("AI_INVESTOR_MODEL", "").strip()
        if not base_url or not model:
            raise RuntimeError("AI_INVESTOR_BASE_URL and AI_INVESTOR_MODEL are required")
        return cls(
            base_url=base_url,
            model=model,
            api_key=os.environ.get("AI_INVESTOR_API_KEY", ""),
            provider=os.environ.get("AI_INVESTOR_PROVIDER", "openai_compatible"),
            timeout_sec=float(os.environ.get("AI_INVESTOR_TIMEOUT_SEC", "180")),
        )

    @property
    def endpoint(self) -> str:
        if self.base_url.endswith("/v1"):
            return self.base_url + "/chat/completions"
        return self.base_url + "/v1/chat/completions"

    def build_payload(self, *, system: str, user: str, schema_text: str) -> dict[str, Any]:
        """모델이 실제로 받는 모양으로 요청 본문을 만든다."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"{user}\n\n반환 JSON 모양:\n{schema_text}"},
            ],
            "response_format": {"type": "json_object"},
        }
        if supports_custom_temperature(self.model):
            payload["temperature"] = DEFAULT_TEMPERATURE
        return payload

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        output_schema: Mapping[str, Any],
        task_name: str,
    ) -> dict[str, Any]:
        import time
        schema_text = json.dumps(output_schema, ensure_ascii=False, separators=(",", ":"))
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = self.build_payload(system=system, user=user, schema_text=schema_text)

        max_attempts = 3
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                with httpx.Client(timeout=self.timeout_sec) as client:
                    response = client.post(self.endpoint, headers=headers, json=payload)
                    response.raise_for_status()
                    body = response.json()
                try:
                    content = body["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as exc:
                    raise RuntimeError(f"unexpected LLM response for {task_name}") from exc
                return _parse_json_object(str(content))
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_exc = exc
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                # 4xx 중 429(Rate Limit)가 아닌 일반 클라이언트 오류는 재시도하지 않고 즉시 발생
                if isinstance(exc, httpx.HTTPStatusError) and status_code and 400 <= status_code < 500 and status_code != 429:
                    # 거절 이유는 provider 응답 본문에만 있다. 그걸 버리면 상태 코드만
                    # 남아 무엇이 잘못됐는지 알 수 없다(실측: temperature 400을 찾는 데
                    # 실행 한 번을 더 썼다).
                    raise RuntimeError(
                        f"LLM rejected the {task_name} request "
                        f"({status_code}): {_response_detail(exc.response)}"
                    ) from exc
                if attempt < max_attempts:
                    sleep_sec = 2.0 ** (attempt - 1)
                    time.sleep(sleep_sec)
                else:
                    break

        raise RuntimeError(f"LLM request failed for {task_name} after {max_attempts} attempts: {last_exc}") from last_exc

