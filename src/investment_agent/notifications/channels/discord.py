"""Discord 메시지 전송 어댑터. HTTP는 이 파일에만 있고 설정·전송 함수를 주입한다.

한 번의 호출은 한 번의 HTTP 시도다. 429 재시도는 outbox가 예약하며 타임아웃/5xx는
전달 여부 불명으로 남긴다. 응답 없는 POST를 여기서 반복하지 않는다.
"""
from __future__ import annotations

from copy import deepcopy
import math
from collections.abc import Sequence
from typing import Any, Callable

from investment_agent.config import Config
from investment_agent.platform.serialization import canonical_json

from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

_API_BASE = "https://discord.com/api/v10"


class DeliveryRejected(RuntimeError):
    """전송되지 않았음이 명확한 응답. 재시도 가능한 거절만 다시 예약한다."""

    def __init__(self, reason: str, *, is_retryable: bool = False, retry_after: float = 60) -> None:
        super().__init__(reason)
        self.is_retryable = is_retryable
        self.retry_after = retry_after


class DeliveryUnknown(RuntimeError):
    """전달 여부 불명. 자동 재전송하면 같은 알림이 두 번 나갈 수 있다."""


def validate_message(message: dict[str, Any]) -> dict[str, Any]:
    """이 어댑터의 text/embed 계약과 Discord 길이 한도를 전송 전에 검사한다."""
    if not isinstance(message, dict) or set(message) - {"content", "embeds", "allowed_mentions"}:
        raise ValueError("unsupported discord message fields")
    content = message.get("content", "")
    embeds = message.get("embeds", [])
    if not isinstance(content, str) or len(content) > 2000:
        raise ValueError("discord content exceeds its limit")
    if not isinstance(embeds, list) or len(embeds) > 10 or (not content.strip() and not embeds):
        raise ValueError("discord message must have content or up to 10 embeds")
    total = 0
    for embed in embeds:
        if not isinstance(embed, dict) or set(embed) - {
            "title", "description", "fields", "footer", "color", "image", "url",
            "thumbnail",
        }:
            raise ValueError("unsupported discord embed fields")
        if "color" in embed and (
            isinstance(embed["color"], bool)
            or not isinstance(embed["color"], int)
            or not 0 <= embed["color"] <= 0xFFFFFF
        ):
            raise ValueError("invalid discord embed color")
        # 제목을 원문으로 잇는 링크. 거장 카드가 SEC 공시로 걸어 두는 자리다.
        # 스킴을 여기서 좁히지 않으면 producer가 넣은 문자열이 그대로 링크가 된다.
        url = embed.get("url")
        if url is not None and (
            not isinstance(url, str)
            or not url.startswith(("https://", "http://"))
            or len(url) > 2048
        ):
            raise ValueError("invalid discord embed url")
        # image는 카드 아래 큰 그림, thumbnail은 오른쪽 위 작은 그림이다. 모양이
        # 같으므로 같은 규칙으로 본다 — 전략 카드가 thumbnail로 QuickChart를 건다.
        for key in ("image", "thumbnail"):
            media = embed.get(key)
            if media is not None and (
                not isinstance(media, dict)
                or set(media) - {"url"}
                or not isinstance(media.get("url"), str)
                or not media["url"]
                or len(media["url"]) > 2048
            ):
                raise ValueError(f"invalid discord embed {key}")
        for key, limit in (("title", 256), ("description", 4096)):
            value = embed.get(key, "")
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError("discord embed text exceeds its limit")
            total += len(value)
        fields = embed.get("fields", [])
        if not isinstance(fields, list) or len(fields) > 25:
            raise ValueError("discord embed supports up to 25 fields")
        for field in fields:
            if not isinstance(field, dict) or set(field) - {"name", "value", "inline"}:
                raise ValueError("invalid discord embed field")
            for key, limit in (("name", 256), ("value", 1024)):
                value = field.get(key)
                if not isinstance(value, str) or not value or len(value) > limit:
                    raise ValueError("discord field text exceeds its limit")
                total += len(value)
            if "inline" in field and not isinstance(field["inline"], bool):
                raise ValueError("discord inline must be boolean")
        footer = embed.get("footer", {})
        if not isinstance(footer, dict) or set(footer) - {"text"}:
            raise ValueError("invalid discord footer")
        text = footer.get("text", "")
        if not isinstance(text, str) or len(text) > 2048:
            raise ValueError("discord footer exceeds its limit")
        total += len(text)
    if total > 6000:
        raise ValueError("discord embed text exceeds 6000 characters")
    result = deepcopy(message)
    # 데이터에 @everyone/role mention이 있어도 알림 대상을 넓히지 않는다.
    result["allowed_mentions"] = {"parse": []}
    return result


def fetch_guild_channels(config: Config, *, get: Callable[..., Any] | None = None) -> list[dict[str, Any]]:
    """길드의 채널 목록. 채널 ID를 사람이 옮겨 적지 않으려면 이 한 번이 필요하다.

    포럼 채널이면 `available_tags`도 같이 온다 — 태그도 이름이 아니라 snowflake로
    지정해야 해서, 이름→ID가 필요한 두 곳이 이 응답 하나로 해결된다.
    """
    token, = config.require("DISCORD_BOT_TOKEN")
    guild_id, = config.require("DISCORD_GUILD_ID")
    if get is None:
        import requests

        get = requests.get
    response = get(
        f"{_API_BASE}/guilds/{guild_id}/channels",
        headers={"Authorization": f"Bot {token}"},
        timeout=30,
        allow_redirects=False,
    )
    if not 200 <= response.status_code < 300:
        raise RuntimeError(f"discord_guild_channels_http_{response.status_code}")
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("discord_guild_channels_unexpected_payload")
    return payload


def _thread_match_key(thread_name: str) -> str:
    """스레드를 다시 찾을 때 쓰는 안정된 키.

    제목 전체를 키로 쓰면 표시명이 바뀌는 순간 같은 대상의 이력이 조용히 갈라진다.
    실제로 한글명을 채우자 `AAPL · Apple Inc. · 실적 기록` 옆에
    `AAPL · 애플 · 실적 기록`이 새로 생겨 종목마다 스레드가 둘이 됐다.

    제목의 첫 마디는 그 스레드가 무엇에 대한 것인지다(실적은 ticker, 거장은 사람
    이름). 표시명은 뒤에 오고 바뀔 수 있으므로 키에서 뺀다.
    """
    head = str(thread_name).strip().split("·", 1)[0]
    return head.strip().lower()[:100]


def fetch_forum_threads(
    config: Config, channel_id: str, *, get: Callable[..., Any] | None = None,
) -> dict[str, str]:
    """포럼 채널의 스레드 매칭 키(`_thread_match_key`) -> 스레드 ID (활성 + 공개 보관).

    포럼은 "종목 1개 = 스레드 1개에 공시를 누적"이 설계다. 그런데 `/threads`는
    부를 때마다 **새 스레드를 만든다** — 그대로 두면 같은 종목의 분기 공시가
    제목만 같은 별개 스레드로 흩어지고, 누적해 읽는다는 성질이 사라진다.
    """
    token, = config.require("DISCORD_BOT_TOKEN")
    guild_id, = config.require("DISCORD_GUILD_ID")
    if get is None:
        import requests

        get = requests.get
    headers = {"Authorization": f"Bot {token}"}
    found: dict[str, str] = {}
    sources = (
        (f"{_API_BASE}/guilds/{guild_id}/threads/active", True),
        (f"{_API_BASE}/channels/{channel_id}/threads/archived/public?limit=100", False),
    )
    for url, filter_parent in sources:
        response = get(url, headers=headers, timeout=30, allow_redirects=False)
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"discord_forum_threads_http_{response.status_code}")
        payload = response.json()
        threads = payload.get("threads") if isinstance(payload, dict) else None
        for thread in threads or []:
            if filter_parent and str(thread.get("parent_id") or "") != str(channel_id):
                continue
            name = _thread_match_key(thread.get("name") or "")
            thread_id = str(thread.get("id") or "")
            # 먼저 본 것을 남긴다 — 활성 스레드가 보관된 동명보다 우선이다.
            if name and thread_id.isdigit():
                found.setdefault(name, thread_id)
    return found


class DiscordChannel:
    """목적지 ID와 고정 API 경로만 사용한다. webhook URL을 받거나 기록하지 않는다."""

    def __init__(self, config: Config, *, post: Callable[..., Any] | None = None,
                 get: Callable[..., Any] | None = None) -> None:
        self._config = config
        self._post = post
        self._get = get
        #: 채널 ID -> {스레드 제목(소문자): 스레드 ID}. 프로세스 안에서만 산다.
        self._threads: dict[str, dict[str, str]] = {}

    def _forum_destination(
        self, target: str, thread_name: str,
    ) -> tuple[str, bool]:
        """(POST 대상 채널 ID, 새 스레드를 만들어야 하는가).

        같은 스레드가 이미 있으면 그 안에 이어 붙인다. 없을 때만 만든다 —
        `/threads`를 매번 부르면 같은 종목의 공시가 제목만 같은 별개 스레드로
        흩어져 "누적해 읽는다"는 포럼의 이유가 사라진다.

        조회에 실패하면 새로 만드는 쪽으로 둔다. 스레드가 하나 늘어나는 것이
        카드가 아예 안 나가는 것보다 낫다.
        """
        key = str(target)
        cached = self._threads.get(key)
        if cached is None:
            try:
                cached = fetch_forum_threads(self._config, key, get=self._get)
            except Exception:  # noqa: BLE001 - 조회 실패로 발송을 막지 않는다
                log.warning("discord forum thread lookup failed", extra={"channel": key})
                cached = {}
            self._threads[key] = cached
        existing = cached.get(_thread_match_key(thread_name))
        return (existing, False) if existing else (key, True)

    def _remember_thread(self, target: str, thread_name: str, thread_id: str) -> None:
        """같은 실행 안에서 두 번째 카드가 방금 만든 스레드를 다시 찾게 한다."""
        self._threads.setdefault(str(target), {})[_thread_match_key(thread_name)] = str(thread_id)


    def send(
        self, *, target: str, message: dict[str, Any],
        thread_name: str | None = None, thread_tags: Sequence[str] = (),
    ) -> str:
        """`thread_name`이 있으면 포럼 스레드로, 없으면 일반 메시지로 보낸다.

        포럼 채널은 `/channels/{id}/messages`를 400으로 거절한다 — 첫 글이 곧
        스레드라 `/threads`로 만들어야 한다. 목적지가 포럼인지는 부르는 쪽이
        안다(선언이 그렇게 되어 있다). 여기서 채널 종류를 다시 물으면 카드 한 장마다
        왕복이 하나 더 붙는다.
        """
        try:
            payload = validate_message(message)
            if not isinstance(target, str) or not target.isascii() or not target.isdigit():
                raise ValueError("invalid discord channel id")
            if thread_name is not None and not str(thread_name).strip():
                raise ValueError("empty forum thread name")
            token, = self._config.require("DISCORD_BOT_TOKEN")
        except (ValueError, RuntimeError) as exc:
            raise DeliveryRejected(type(exc).__name__) from None
        post = self._post
        if post is None:
            import requests
            post = requests.post
        destination, is_new_thread = (target, False)
        if thread_name is not None:
            destination, is_new_thread = self._forum_destination(target, thread_name)
        if thread_name is None or not is_new_thread:
            # 이미 있는 스레드는 일반 채널처럼 메시지를 이어 붙인다.
            url = f"{_API_BASE}/channels/{destination}/messages"
            body: dict[str, Any] = payload
        else:
            url = f"{_API_BASE}/channels/{destination}/threads"
            # Discord 스레드 제목 상한은 100자다. 넘기면 400으로 거절당한다.
            body = {"name": str(thread_name)[:100], "message": payload}
            if thread_tags:
                body["applied_tags"] = list(thread_tags)
        try:
            response = post(
                url,
                headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
                json=body, timeout=30, allow_redirects=False,
            )
        except Exception:
            raise DeliveryUnknown("discord_transport_outcome_unknown") from None
        status = response.status_code
        if status == 429:
            retry_after = response.headers.get("Retry-After", 60)
            try:
                retry_after = float(response.json().get("retry_after", retry_after))
                if not math.isfinite(retry_after) or retry_after < 0:
                    raise ValueError("invalid retry interval")
            except (ValueError, TypeError, AttributeError):
                # 대기 시간을 읽지 못하면 짧은 재시도 간격을 추측하지 않는다.
                raise DeliveryUnknown("discord_rate_limit_interval_unknown") from None
            raise DeliveryRejected("discord_rate_limited", is_retryable=True, retry_after=retry_after)
        if 400 <= status < 500:
            raise DeliveryRejected(f"discord_http_{status}")
        if not 200 <= status < 300:
            raise DeliveryUnknown(f"discord_http_{status}_outcome_unknown")
        try:
            message_id = str(response.json()["id"])
            if not message_id.isascii() or not message_id.isdigit():
                raise ValueError("invalid message id")
            if is_new_thread and thread_name is not None:
                # 새 스레드의 응답 id가 곧 스레드 id다.
                self._remember_thread(target, thread_name, message_id)
            return message_id
        except (ValueError, TypeError, KeyError):
            raise DeliveryUnknown("discord_response_outcome_unknown") from None

    def send_file(
        self, *, target: str, path: str, content: str = "",
        embeds: list[dict[str, Any]] | None = None,
        thread_name: str | None = None, thread_tags: Sequence[str] = (),
    ) -> str:
        """한 개의 카드 파일을 보낸다. 파일 업로드는 이 채널 경계에서만 수행한다."""
        try:
            token, = self._config.require("DISCORD_BOT_TOKEN")
            if not isinstance(target, str) or not target.isascii() or not target.isdigit():
                raise ValueError("invalid discord channel id")
            if not isinstance(path, str) or not path:
                raise ValueError("invalid file path")
            file_name = path.replace("\\", "/").split("/")[-1]
            if not file_name:
                raise ValueError("invalid file name")
            if thread_name is not None and not str(thread_name).strip():
                raise ValueError("empty forum thread name")
        except (ValueError, RuntimeError) as exc:
            raise DeliveryRejected(type(exc).__name__) from None
        if self._post is not None:
            raise DeliveryRejected("file_sender_does_not_support_injected_post")
        import requests
        try:
            with open(path, "rb") as stream:
                starter = {
                    "content": content,
                    "embeds": embeds or [],
                    "allowed_mentions": {"parse": []},
                }
                destination, is_new_thread = (target, False)
                if thread_name is not None:
                    destination, is_new_thread = self._forum_destination(target, thread_name)
                if thread_name is None or not is_new_thread:
                    url = f"{_API_BASE}/channels/{destination}/messages"
                    form: dict[str, Any] = starter
                else:
                    url = f"{_API_BASE}/channels/{destination}/threads"
                    form = {"name": str(thread_name)[:100], "message": starter}
                    if thread_tags:
                        form["applied_tags"] = list(thread_tags)
                response = requests.post(
                    url,
                    headers={"Authorization": f"Bot {token}"},
                    data={"payload_json": canonical_json(form)},
                    files={"file": (file_name, stream, "image/png")},
                    timeout=30,
                    allow_redirects=False,
                )
        except (FileNotFoundError, OSError):
            raise DeliveryRejected("discord_attachment_does_not_exist") from None
        except Exception:
            raise DeliveryUnknown("discord_transport_outcome_unknown") from None
        if response.status_code == 429:
            raise DeliveryRejected("discord_rate_limited", is_retryable=True)
        if 400 <= response.status_code < 500:
            raise DeliveryRejected(f"discord_http_{response.status_code}")
        if not 200 <= response.status_code < 300:
            raise DeliveryUnknown(f"discord_http_{response.status_code}_outcome_unknown")
        try:
            message_id = str(response.json()["id"])
            if not message_id.isascii() or not message_id.isdigit():
                raise ValueError("invalid message id")
            if is_new_thread and thread_name is not None:
                self._remember_thread(target, thread_name, message_id)
            return message_id
        except (ValueError, TypeError, KeyError):
            raise DeliveryUnknown("discord_response_outcome_unknown") from None
