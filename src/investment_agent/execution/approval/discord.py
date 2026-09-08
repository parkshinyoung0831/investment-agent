"""투자 승인 카드 전용 Discord REST/Gateway 경계."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

import requests

from investment_agent.platform.logging import get_logger
from investment_agent.execution.contracts import ExecutionSafetyError

log = get_logger(__name__)

_API_BASE = "https://discord.com/api/v10"


@dataclass(frozen=True)
class DiscordMessageRef:
    guild_id: str
    channel_id: str
    message_id: str


class InteractionHandler(Protocol):
    def handle_interaction(self, payload: Mapping[str, Any]): ...


class DiscordApprovalClient:
    """승인 전용 bot token으로 카드만 발송·비활성화한다."""

    def __init__(
        self,
        *,
        bot_token: str,
        guild_id: str,
        timeout_sec: float = 15.0,
        session: Any = requests,
    ):
        token = bot_token.strip()
        if not token:
            raise ExecutionSafetyError("DISCORD_APPROVAL_BOT_TOKEN is empty")
        if not guild_id.strip():
            raise ExecutionSafetyError("DISCORD_GUILD_ID is empty")
        self._token = token
        self._guild_id = guild_id.strip()
        self._timeout_sec = timeout_sec
        self._session = session

    @property
    def guild_id(self) -> str:
        return self._guild_id

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bot {self._token}",
            "Content-Type": "application/json",
        }

    def post_card(self, *, channel_id: str, payload: Mapping[str, Any]) -> DiscordMessageRef:
        """timeout 때 중복 카드가 생기지 않도록 자동 재시도 없이 한 번만 보낸다."""
        if not payload.get("components"):
            raise ExecutionSafetyError("approval card has no signed buttons")
        url = f"{_API_BASE}/channels/{channel_id}/messages"
        response = self._session.post(
            url,
            headers=self._headers(),
            json=dict(payload),
            timeout=self._timeout_sec,
        )
        response.raise_for_status()
        data = response.json()
        message_id = str(data.get("id") or "")
        returned_channel = str(data.get("channel_id") or "")
        if not message_id or returned_channel != channel_id:
            raise ExecutionSafetyError("Discord returned an unexpected approval message")
        return DiscordMessageRef(
            guild_id=self._guild_id,
            channel_id=returned_channel,
            message_id=message_id,
        )

    def disable_buttons(
        self,
        *,
        channel_id: str,
        message_id: str,
        components: list[dict[str, Any]],
    ) -> None:
        """결정 뒤 버튼을 UI에서 잠근다. DB 원자성은 이 편집 성공 여부와 무관하다."""
        url = f"{_API_BASE}/channels/{channel_id}/messages/{message_id}"
        response = self._session.patch(
            url,
            headers=self._headers(),
            json={"components": components},
            timeout=self._timeout_sec,
        )
        response.raise_for_status()

    def set_status_text(
        self,
        *,
        channel_id: str,
        message_id: str,
        content: str,
    ) -> None:
        """원 승인 카드 한 장의 상태 문구만 멱등 PATCH한다."""
        text = content.strip()
        if not text or len(text) > 1_500:
            raise ExecutionSafetyError("Discord approval status text is invalid")
        url = f"{_API_BASE}/channels/{channel_id}/messages/{message_id}"
        response = self._session.patch(
            url,
            headers=self._headers(),
            json={"content": text, "allowed_mentions": {"parse": []}},
            timeout=self._timeout_sec,
        )
        response.raise_for_status()


def _interaction_payload(interaction: Any) -> dict[str, Any]:
    """discord.py 객체를 검증 가능한 원시 component payload로 축소한다."""
    user = getattr(interaction, "user", None)
    message = getattr(interaction, "message", None)
    return {
        "type": int(getattr(getattr(interaction, "type", None), "value", 0)),
        "data": dict(getattr(interaction, "data", None) or {}),
        "guild_id": str(getattr(interaction, "guild_id", "") or ""),
        "channel_id": str(getattr(interaction, "channel_id", "") or ""),
        "message": {"id": str(getattr(message, "id", "") or "")},
        "member": {"user": {"id": str(getattr(user, "id", "") or "")}},
    }


def run_gateway_listener(*, bot_token: str, handler: InteractionHandler) -> None:
    """Discord Gateway에서 button interaction만 받아 승인 상태를 기록한다.

    이 listener는 승인 결과를 주문 worker로 넘기지 않으며 broker API를 import하지 않는다.
    """
    try:
        import discord
    except ImportError as exc:  # pragma: no cover - 설치 경계
        raise RuntimeError("discord.py is required for the approval listener") from exc

    intents = discord.Intents.none()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        log.info("Discord approval listener ready bot_user_id=%s", client.user.id)

    @client.event
    async def on_interaction(interaction: Any) -> None:
        if int(getattr(getattr(interaction, "type", None), "value", 0)) != 3:
            return
        try:
            result = await asyncio.to_thread(
                handler.handle_interaction,
                _interaction_payload(interaction),
            )
            action_text = "승인" if result.status == "approved" else "거절"
            if result.status == "approved" and result.execution_mode == "live":
                message = (
                    "승인을 기록했습니다. 주문 worker가 계좌·시세·한도를 다시 검사한 뒤 "
                    "통과한 주문만 전송하며, 결과는 이 채널에 남습니다."
                )
            else:
                message = f"{action_text}을 기록했습니다. 주문은 전송되지 않습니다."
        except Exception as exc:  # Discord에는 내부 식별자·서명 오류 세부를 노출하지 않는다.
            log.warning("Discord approval interaction rejected: %s", exc)
            message = "이 요청은 처리할 수 없습니다. 만료·중복·권한·서명을 확인하세요."
        if not interaction.response.is_done():
            await interaction.response.send_message(message, ephemeral=True)

    client.run(bot_token.strip(), log_handler=None)
