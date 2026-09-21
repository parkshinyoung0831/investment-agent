"""Discord 메시지 전송 어댑터. HTTP는 이 파일에만 있고 설정·전송 함수를 주입한다.

한 번의 호출은 한 번의 HTTP 시도다. 429 재시도는 원장이 예약하며 타임아웃/5xx는
전달 여부 불명으로 남긴다. 응답 없는 POST를 여기서 반복하지 않는다 — 다만 `deliver`에
nonce를 주면 Discord가 몇 분 안의 같은 nonce를 새 메시지로 만들지 않으므로, 호출자가
그 창 안에서 한 번 더 시도할 수 있다.
"""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Callable
from urllib.parse import quote

from investment_agent.config import Config
from investment_agent.notifications.channels.contracts import (
    NONCE_MAX_LENGTH, Delivery, DeliveryRejected, DeliveryUnknown, ForumThread,
)
from investment_agent.platform.serialization import canonical_json

from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

_API_BASE = "https://discord.com/api/v10"
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
    # (url, 부모 포럼으로 거를지, 페이지를 이어 받을지). 보관 스레드는 한 번에 100개까지라 종목 수가 그보다
    # 많으면 오래된 종목의 스레드를 못 찾고 같은 종목의 스레드를 새로 만들게 된다.
    sources = (
        (f"{_API_BASE}/guilds/{guild_id}/threads/active", True, False),
        (f"{_API_BASE}/channels/{channel_id}/threads/archived/public?limit=100", False, True),
    )
    for url, filter_parent, paginate in sources:
        newest: dict[str, tuple[str, str]] = {}
        page_url = url
        for _ in range(_MAX_ARCHIVED_PAGES if paginate else 1):
            response = get(page_url, headers=headers, timeout=30, allow_redirects=False)
            if not 200 <= response.status_code < 300:
                raise RuntimeError(f"discord_forum_threads_http_{response.status_code}")
            payload = response.json()
            threads = payload.get("threads") if isinstance(payload, dict) else None
            for thread in threads or []:
                if filter_parent and str(thread.get("parent_id") or "") != str(channel_id):
                    continue
                name = _thread_match_key(thread.get("name") or "")
                thread_id = str(thread.get("id") or "")
                if not name or not thread_id.isdigit():
                    continue
                # 같은 키에 스레드가 둘 이상이면 **가장 최근에 만들어진 것**을 쓴다.
                # 표시명이 바뀌어 스레드가 갈라진 적이 있는데, 그때 어느 쪽에 쌓일지가
                # Discord 응답 순서에 달려 있었다 — 실행마다 목적지가 달라진다.
                # 최신 스레드에 최신 카드가 있으므로 그쪽으로 모은다.
                created = str(
                    (thread.get("thread_metadata") or {}).get("create_timestamp") or ""
                ) or _snowflake_order(thread_id)
                previous = newest.get(name)
                if previous is None or created > previous[0]:
                    newest[name] = (created, thread_id)
            cursor = _next_archive_cursor(payload, threads) if paginate else None
            if cursor is None:
                break
            page_url = f"{url}&before={quote(cursor, safe='')}"
        # 활성 스레드가 보관된 동명보다 우선이다 — 보관된 곳에는 글을 못 붙인다.
        for name, (_created, thread_id) in newest.items():
            found.setdefault(name, thread_id)
    return found


# 보관 스레드 페이지 상한(100개 × 이 값). 관심종목이 수십 개라 이 안에서 끝나야 하고, 응답이 끝나지 않는
# 이상 상황에서 요청이 끝없이 이어지지 않게 하는 안전장치다.
_MAX_ARCHIVED_PAGES = 10


def _next_archive_cursor(payload: Any, threads: Any) -> str | None:
    """다음 페이지를 받을 `before` 값(마지막 스레드의 보관 시각). 더 없으면 None."""
    if not isinstance(payload, dict) or not payload.get("has_more") or not threads:
        return None
    cursor = str(((threads[-1] or {}).get("thread_metadata") or {}).get("archive_timestamp") or "")
    return cursor or None


def _snowflake_order(thread_id: str) -> str:
    """생성 시각이 없을 때 쓰는 순서. snowflake는 시간순으로 커진다."""
    return thread_id.zfill(24)


def _file_name(path: str) -> str:
    name = str(path).replace("\\", "/").split("/")[-1]
    if not name:
        raise DeliveryRejected("ValueError")
    return name


class DiscordChannel:
    """목적지 ID와 고정 API 경로만 사용한다. webhook URL을 받거나 기록하지 않는다."""

    def __init__(self, config: Config, *, post: Callable[..., Any] | None = None,
                 get: Callable[..., Any] | None = None,
                 patch: Callable[..., Any] | None = None) -> None:
        self._config = config
        self._post = post
        self._get = get
        self._patch = patch
        #: 채널 ID -> {스레드 제목(소문자): 스레드 ID}. 프로세스 안에서만 산다.
        self._threads: dict[str, dict[str, str]] = {}

    # ── 원장 기반 전송 ─────────────────────────────────────────────────────
    def deliver(
        self, *, target: str, message: dict[str, Any], attachment_path: str | None = None,
        thread: ForumThread | None = None, known_thread_id: str | None = None,
        nonce: str | None = None,
    ) -> Delivery:
        """새 메시지를 보낸다. 포럼이면 스레드에 이어 붙이거나 스레드를 새로 만든다.

        `known_thread_id`는 원장이 기억하는 스레드다. 그것이 없으면(원장 도입 전에 만든
        스레드) Discord 목록에서 제목 첫 마디로 한 번 찾는다. 기억하던 스레드가 지워졌으면
        새 스레드를 만들고, 호출자는 돌려받은 thread_id로 원장을 고친다.
        """
        payload = self._checked(target=target, message=message)
        if thread is not None and not str(thread.name).strip():
            raise DeliveryRejected("ValueError")
        if thread is None:
            response = self._send_message(target, payload, attachment_path, nonce)
            return Delivery(target, self._message_id(response))
        destination = known_thread_id
        if destination is None:
            found, is_new = self._forum_destination(target, thread.name)
            destination = None if is_new else found
        if destination is not None:
            try:
                response = self._send_message(destination, payload, attachment_path, nonce)
                return Delivery(destination, self._message_id(response), destination)
            except DeliveryRejected as exc:
                # 지워진 스레드. 같은 대상의 기록이 끊기지 않게 새 스레드를 연다.
                if str(exc) != "discord_http_404" or known_thread_id is None:
                    raise
                log.warning("discord thread vanished; opening a new one", extra={"channel": target})
        body: dict[str, Any] = {"name": str(thread.name)[:100], "message": payload}
        if thread.tags:
            body["applied_tags"] = list(thread.tags)
        response = self._request("post", f"{_API_BASE}/channels/{target}/threads", body, attachment_path)
        thread_id = self._message_id(response)
        self._remember_thread(target, thread.name, thread_id)
        # 포럼의 첫 글은 스레드와 같은 id를 갖는다.
        return Delivery(thread_id, thread_id, thread_id)

    def edit(
        self, *, location_id: str, message_id: str, message: dict[str, Any],
        attachment_path: str | None = None,
    ) -> Delivery:
        """이미 보낸 메시지의 내용을 바꾼다. 첨부가 있으면 옛 첨부를 새 것으로 갈아 끼운다."""
        payload = self._checked(target=location_id, message=message)
        if not isinstance(message_id, str) or not message_id.isascii() or not message_id.isdigit():
            raise DeliveryRejected("ValueError")
        if attachment_path is not None:
            payload["attachments"] = [{"id": 0, "filename": _file_name(attachment_path)}]
        response = self._request(
            "patch", f"{_API_BASE}/channels/{location_id}/messages/{message_id}", payload, attachment_path,
        )
        self._message_id(response)
        return Delivery(location_id, message_id)

    def _checked(self, *, target: str, message: dict[str, Any]) -> dict[str, Any]:
        try:
            payload = validate_message(message)
            if not isinstance(target, str) or not target.isascii() or not target.isdigit():
                raise ValueError("invalid discord channel id")
            self._config.require("DISCORD_BOT_TOKEN")
        except (ValueError, RuntimeError) as exc:
            raise DeliveryRejected(type(exc).__name__) from None
        return payload

    def _send_message(self, channel_id: str, payload: dict[str, Any], attachment_path: str | None,
                      nonce: str | None) -> Any:
        body = dict(payload)
        if nonce is not None:
            if not nonce or len(nonce) > NONCE_MAX_LENGTH:
                raise DeliveryRejected("invalid_nonce")
            body["nonce"], body["enforce_nonce"] = nonce, True
        return self._request("post", f"{_API_BASE}/channels/{channel_id}/messages", body, attachment_path)

    def _request(self, method: str, url: str, body: dict[str, Any], attachment_path: str | None) -> Any:
        token, = self._config.require("DISCORD_BOT_TOKEN")
        sender = self._post if method == "post" else self._patch
        if sender is None:
            import requests

            sender = requests.post if method == "post" else requests.patch
        headers = {"Authorization": f"Bot {token}"}
        try:
            if attachment_path is None:
                return self._checked_status(sender(
                    url, headers={**headers, "Content-Type": "application/json"},
                    json=body, timeout=30, allow_redirects=False,
                ))
            name = _file_name(attachment_path)
            with open(attachment_path, "rb") as stream:
                response = sender(
                    url, headers=headers, data={"payload_json": canonical_json(body)},
                    files={"files[0]": (name, stream, "image/png")}, timeout=30, allow_redirects=False,
                )
        except (FileNotFoundError, IsADirectoryError):
            raise DeliveryRejected("discord_attachment_does_not_exist") from None
        except (DeliveryRejected, DeliveryUnknown):
            raise
        except Exception:
            raise DeliveryUnknown("discord_transport_outcome_unknown") from None
        return self._checked_status(response)

    @staticmethod
    def _checked_status(response: Any) -> Any:
        status = response.status_code
        if status == 429:
            try:
                retry_after = float(response.json().get("retry_after", response.headers.get("Retry-After", 60)))
                if not math.isfinite(retry_after) or retry_after < 0:
                    raise ValueError("invalid retry interval")
            except (ValueError, TypeError, AttributeError):
                raise DeliveryUnknown("discord_rate_limit_interval_unknown") from None
            raise DeliveryRejected("discord_rate_limited", is_retryable=True, retry_after=retry_after)
        if 400 <= status < 500:
            raise DeliveryRejected(f"discord_http_{status}")
        if not 200 <= status < 300:
            raise DeliveryUnknown(f"discord_http_{status}_outcome_unknown")
        return response

    @staticmethod
    def _message_id(response: Any) -> str:
        try:
            message_id = str(response.json()["id"])
            if not message_id.isascii() or not message_id.isdigit():
                raise ValueError("invalid message id")
            return message_id
        except (ValueError, TypeError, KeyError):
            raise DeliveryUnknown("discord_response_outcome_unknown") from None

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


__all__ = [
    "DiscordChannel", "fetch_forum_threads", "fetch_guild_channels", "validate_message",
]
