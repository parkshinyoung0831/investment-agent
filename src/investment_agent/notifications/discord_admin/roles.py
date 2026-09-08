"""역할과 권한의 단일 기준(SSOT).

**이 설계의 핵심은 한 줄이다: @everyone에게서 '메시지 보내기'를 길드 레벨에서 뺀다.**

채널마다 deny를 다는 방식과 결과는 비슷해 보이지만 실패 방향이 정반대다. 채널 deny 방식은
나중에 채널을 하나 추가했을 때 아무도 손대지 않은 그 채널이 '누구나 쓸 수 있는' 상태로
열리고, 그 사실은 누가 쓰기 전까지 아무에게도 보이지 않는다. 길드 레벨에서 끄면 새 채널은
자동으로 읽기 전용이고, 열고 싶으면 여기에 한 줄을 적어야 한다.

**그리고 이쪽이 봇을 살린다.** 길드 레벨 deny는 채널 오버라이트가 아니라서 역할의 길드
권한으로 그냥 덮인다 — 카드 봇에 길드 권한 한 벌만 주면 모든 채널에서 그대로 동작한다.
`onboarding.py`가 경고한 함정(채널마다 봇 allow를 달다가 하나를 빠뜨려 카드가 조용히
안 나가는 것)은, 채널 오버라이트를 '예외'로만 쓰기 때문에 생기지 않는다.

예외는 셋뿐이다.

1. 라운지 — 온보딩에서 참여를 고른 사람(member)에게만 대화를 연다.
2. 실적-리포트 — 새 글은 봇만(종목 1개 = 스레드 1개), 스레드 안 댓글은 member에게 연다.
3. private 카테고리(LAB·OPERATIONS) — @everyone에게서 채널 보기를 막는다. 여기서만
   봇 오버라이트가 필요한데, 사람이 적는 게 아니라 매니페스트의 private 표시에서
   자동으로 나온다(`overwrites()`). 빠뜨림은 tests/discord_admin/test_roles.py가 잡는다.

카드 채널에는 **@everyone 채널 deny를 절대 달지 않는다.** 다는 순간 그 채널에서 봇의 길드
권한이 무력화되고, 위의 함정이 그대로 돌아온다.
"""
from __future__ import annotations

from typing import Any

from investment_agent.notifications.discord_admin import manifest

# --- Discord 권한 비트 (쓰는 것만) ---
CREATE_INSTANT_INVITE = 1 << 0
KICK_MEMBERS = 1 << 1
BAN_MEMBERS = 1 << 2
ADMINISTRATOR = 1 << 3
MANAGE_CHANNELS = 1 << 4
MANAGE_GUILD = 1 << 5
ADD_REACTIONS = 1 << 6
VIEW_AUDIT_LOG = 1 << 7
STREAM = 1 << 9
VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
MANAGE_MESSAGES = 1 << 13
EMBED_LINKS = 1 << 14
ATTACH_FILES = 1 << 15
READ_MESSAGE_HISTORY = 1 << 16
MENTION_EVERYONE = 1 << 17
USE_EXTERNAL_EMOJIS = 1 << 18
CONNECT = 1 << 20
SPEAK = 1 << 21
USE_VAD = 1 << 25
CHANGE_NICKNAME = 1 << 26
MANAGE_NICKNAMES = 1 << 27
MANAGE_ROLES = 1 << 28
MANAGE_WEBHOOKS = 1 << 29
USE_APPLICATION_COMMANDS = 1 << 31
MANAGE_THREADS = 1 << 34
CREATE_PUBLIC_THREADS = 1 << 35
USE_EXTERNAL_STICKERS = 1 << 37
SEND_MESSAGES_IN_THREADS = 1 << 38
MODERATE_MEMBERS = 1 << 40
CREATE_POLLS = 1 << 49

# 어떤 멤버 역할에도 들어가면 안 되는 것. 하나라도 새면 서버 구조를 코드로 지키는 의미가 없다.
FORBIDDEN = (ADMINISTRATOR | MANAGE_GUILD | MANAGE_ROLES | MANAGE_CHANNELS
             | MANAGE_WEBHOOKS | BAN_MEMBERS | MENTION_EVERYONE)

# @everyone: 보고, 읽고, 반응만. 여기에 SEND_MESSAGES가 없는 것이 설계의 전부다.
EVERYONE_PERMISSIONS = VIEW_CHANNEL | READ_MESSAGE_HISTORY | ADD_REACTIONS | CHANGE_NICKNAME

# 채널 오버라이트로 얹는 묶음.
CHAT = (SEND_MESSAGES | SEND_MESSAGES_IN_THREADS | CREATE_PUBLIC_THREADS
        | EMBED_LINKS | ATTACH_FILES | ADD_REACTIONS | READ_MESSAGE_HISTORY
        | CREATE_POLLS)   # 투표는 라운지에서만 — 카드 채널에 끼면 목록이 흐려진다
THREAD_REPLY = SEND_MESSAGES_IN_THREADS | EMBED_LINKS | ATTACH_FILES | ADD_REACTIONS
VOICE_CHAT = CONNECT | SPEAK | STREAM | USE_VAD

# 카드 봇이 실제로 하는 일: 카드 올리기(첨부·embed), 포럼에 스레드 만들기, 스레드에 이어
# 붙이기, 그리고 **도착 확인을 위해 읽기**(src/investment_agent/operations/discord.py가 /messages를 센다).
BOT_PERMISSIONS = (VIEW_CHANNEL | READ_MESSAGE_HISTORY | SEND_MESSAGES
                   | SEND_MESSAGES_IN_THREADS | CREATE_PUBLIC_THREADS
                   | EMBED_LINKS | ATTACH_FILES | USE_EXTERNAL_EMOJIS)

# 슬래시 명령은 말할 수 있는 채널에서만 의미가 있으니 길드 레벨로 준다 — 나중에 도우미 봇을
# 붙였을 때 "명령이 안 보인다"로 헤매는 것을 미리 막는다.
_MEMBER = (CREATE_INSTANT_INVITE | USE_EXTERNAL_EMOJIS | USE_EXTERNAL_STICKERS
           | USE_APPLICATION_COMMANDS)
_MOD = (_MEMBER | KICK_MEMBERS | MODERATE_MEMBERS | MANAGE_MESSAGES | MANAGE_THREADS
        | MANAGE_NICKNAMES | VIEW_AUDIT_LOG | SEND_MESSAGES | SEND_MESSAGES_IN_THREADS
        | CREATE_PUBLIC_THREADS | EMBED_LINKS | ATTACH_FILES | CONNECT | SPEAK)

# 만들 역할. bot_env가 있으면 그 토큰의 봇에게 역할을 붙인다 — 봇 사용자 ID는 토큰으로 묻는다.
ROLES: list[dict[str, Any]] = [
    {
        "key": "member",
        "name": "◆ 라운지",
        "permissions": _MEMBER,
        "color": 0x3182F6,   # DESIGN-system.md · colors.primary
        "hoist": False,
        "mentionable": False,
        "note": "온보딩에서 대화 참여를 고르면 붙는다. 스팸 봇은 보통 온보딩을 통과하지 "
                "않아, 이 한 칸이 그대로 1차 필터가 된다.",
    },
    {
        "key": "mod",
        "name": "🛡 모더레이터",
        "permissions": _MOD,
        "color": 0x3182F6,
        "hoist": True,       # 누구에게 말해야 하는지 멤버 목록에서 보여야 한다
        "mentionable": True,
        "note": "메시지·스레드 정리와 타임아웃·추방까지. 차단(ban)과 서버 구조 변경은 "
                "주지 않는다 — 되돌릴 수 없는 것은 사람 한 명에게만 남긴다.",
    },
    {
        "key": "cardbot",
        "name": "🤖 ATLAS 카드봇",
        "permissions": BOT_PERMISSIONS,
        "color": 0x3182F6,
        "hoist": False,
        "mentionable": False,
        "bot_env": "DISCORD_BOT_TOKEN",
        "note": "카드 봇에게 주는 길드 권한 한 벌. Discord가 만든 관리형(managed) 역할은 "
                "건드리지 않는다 — 우리 역할을 따로 만들어 붙인다.",
    },
    {
        "key": "approvalbot",
        "name": "🔐 ATLAS 승인봇",
        "permissions": VIEW_CHANNEL | READ_MESSAGE_HISTORY | SEND_MESSAGES | EMBED_LINKS,
        "color": 0x3182F6,
        "hoist": False,
        "mentionable": False,
        "bot_env": "DISCORD_APPROVAL_BOT_TOKEN",
        "note": "투자-승인 카드와 버튼 interaction만 처리한다. 첨부·스레드·서버 관리 권한은 없다.",
    },
]

EVERYONE_KEY = "everyone"

# 예외 1·2 — 채널 key -> {역할 key: 허용 비트}. 여기 없는 채널은 전부 읽기 전용이다.
GRANTS: dict[str, dict[str, int]] = {
    "lounge": {"member": CHAT},
    "lounge_voice": {"member": VOICE_CHAT},
    # 포럼에서 SEND_MESSAGES는 '새 글 쓰기'다. 주지 않으므로 스레드는 봇만 연다.
    "earnings": {"member": THREAD_REPLY},
    "ai_approvals": {
        "approvalbot": VIEW_CHANNEL | READ_MESSAGE_HISTORY | SEND_MESSAGES | EMBED_LINKS,
    },
}

# 예외 3 — private 카테고리에서 누가 무엇을 갖는가.
PRIVATE_DENY = VIEW_CHANNEL
PRIVATE_ALLOW = {
    "cardbot": BOT_PERMISSIONS,
    "mod": VIEW_CHANNEL | READ_MESSAGE_HISTORY | SEND_MESSAGES | SEND_MESSAGES_IN_THREADS,
}

# 승인 채널은 일반 카드 봇도 보지 못한다. 같은 private 카테고리의 상위 allow를
# channel-level deny로 덮고, 승인 전용 봇만 GRANTS에서 다시 연다.
PRIVATE_CHANNEL_DENY = {
    "ai_approvals": {"cardbot": VIEW_CHANNEL},
}

# Community 전환 때 LOW(1)로 켜 둔 것을 MEDIUM으로 올린다 — 가입 5분이 안 된 계정은
# 말할 수 없다. 사람을 모으는 서버에서 스팸 봇을 가장 싸게 거르는 지점이다.
VERIFICATION_LEVEL = 2


def role(key: str) -> dict[str, Any]:
    for item in ROLES:
        if item["key"] == key:
            return item
    raise KeyError(key)


def overwrites() -> list[dict[str, Any]]:
    """적용할 채널 오버라이트 선언 — (대상 이름, 역할 key, allow, deny).

    private 카테고리는 카테고리와 그 안의 채널에 **둘 다** 적는다. Discord는 이미 있던
    채널을 카테고리에 맞춰 자동으로 동기화해 주지 않아서, 카테고리에만 적으면 나중에
    합류한 채널이 조용히 공개로 남는다.
    """
    out: list[dict[str, Any]] = []
    for category in manifest.private_categories():
        targets = [(category["name"], "category", None)]
        targets += [(c["name"], "channel", c["key"]) for c in category["channels"]]
        for name, kind, channel_key in targets:
            out.append({"target": name, "kind": kind, "role": EVERYONE_KEY,
                        "allow": 0, "deny": PRIVATE_DENY})
            for role_key, allow in PRIVATE_ALLOW.items():
                denied = PRIVATE_CHANNEL_DENY.get(channel_key or "", {}).get(role_key, 0)
                if denied:
                    out.append({"target": name, "kind": kind, "role": role_key,
                                "allow": 0, "deny": denied})
                    continue
                out.append({"target": name, "kind": kind, "role": role_key,
                            "allow": allow, "deny": 0})

    by_key = {c["key"]: c for c in manifest.channels()}
    for channel_key, grants in GRANTS.items():
        channel = by_key[channel_key]
        for role_key, allow in grants.items():
            out.append({"target": channel["name"], "kind": "channel",
                        "role": role_key, "allow": allow, "deny": 0})
    return out


def plan_everyone(existing: list[dict[str, Any]], guild_id: str) -> dict[str, Any] | None:
    """@everyone의 길드 권한이 선언과 다르면 그 차이. 같으면 None."""
    for item in existing:
        if str(item.get("id")) == str(guild_id):
            current = int(item.get("permissions") or 0)
            if current == EVERYONE_PERMISSIONS:
                return None
            return {"current": current, "wanted": EVERYONE_PERMISSIONS,
                    "removing": current & ~EVERYONE_PERMISSIONS,
                    "adding": EVERYONE_PERMISSIONS & ~current}
    return {"current": 0, "wanted": EVERYONE_PERMISSIONS,
            "removing": 0, "adding": EVERYONE_PERMISSIONS}


def plan_roles(existing: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """선언한 역할을 이름으로 대조한다 — 없으면 만들고, 권한이 다르면 고친다.

    이름으로 찾는 이유는 채널과 같다: ID를 코드에 박으면 서버를 다시 세울 때마다 코드를
    고쳐야 한다. 삭제는 하지 않는다.
    """
    by_name = {str(r.get("name")): r for r in existing}
    create, update, ok = [], [], []
    for declared in ROLES:
        found = by_name.get(declared["name"])
        if found is None:
            create.append(declared)
            continue
        entry = {**declared, "id": str(found["id"]),
                 "permissions_current": int(found.get("permissions") or 0)}
        (ok if entry["permissions_current"] == declared["permissions"] else update).append(entry)
    return {"create": create, "update": update, "ok": ok}


def plan_overwrites(channels: list[dict[str, Any]],
                    role_ids: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    """선언한 오버라이트 중 실제로 써야 하는 것.

    선언한 값이 그대로 최종 상태다(PUT). 사람이 Discord UI에서 같은 역할에 비트를 더해
    뒀다면 이 적용이 되돌린다 — 그래야 코드를 읽고 서버 상태를 알 수 있다.
    """
    by_name = {str(c.get("name")): c for c in channels}
    apply_, ok, missing = [], [], []
    for item in overwrites():
        channel = by_name.get(item["target"])
        role_id = role_ids.get(item["role"])
        if channel is None or not role_id:
            missing.append({**item, "why": "채널 없음" if channel is None else "역할 없음"})
            continue
        current = next((o for o in (channel.get("permission_overwrites") or [])
                        if str(o.get("id")) == str(role_id)), None)
        entry = {**item, "channel_id": str(channel["id"]), "role_id": str(role_id)}
        if (current and int(current.get("allow") or 0) == item["allow"]
                and int(current.get("deny") or 0) == item["deny"]):
            ok.append(entry)
        else:
            apply_.append(entry)
    return {"apply": apply_, "ok": ok, "missing": missing}


_NAMES = [
    (ADMINISTRATOR, "관리자"), (MANAGE_GUILD, "서버 관리"), (MANAGE_ROLES, "역할 관리"),
    (MANAGE_CHANNELS, "채널 관리"), (MANAGE_WEBHOOKS, "웹훅 관리"),
    (BAN_MEMBERS, "차단"), (KICK_MEMBERS, "추방"), (MODERATE_MEMBERS, "타임아웃"),
    (MANAGE_MESSAGES, "메시지 관리"), (MANAGE_THREADS, "스레드 관리"),
    (MANAGE_NICKNAMES, "별명 관리"), (VIEW_AUDIT_LOG, "감사 로그"),
    (MENTION_EVERYONE, "everyone 멘션"), (VIEW_CHANNEL, "채널 보기"),
    (READ_MESSAGE_HISTORY, "기록 읽기"), (SEND_MESSAGES, "메시지 보내기"),
    (SEND_MESSAGES_IN_THREADS, "스레드에 쓰기"), (CREATE_PUBLIC_THREADS, "스레드 만들기"),
    (EMBED_LINKS, "링크 미리보기"), (ATTACH_FILES, "파일 첨부"), (ADD_REACTIONS, "반응 추가"),
    (USE_EXTERNAL_EMOJIS, "외부 이모지"), (USE_EXTERNAL_STICKERS, "외부 스티커"),
    (USE_APPLICATION_COMMANDS, "슬래시 명령"), (CREATE_POLLS, "투표 만들기"),
    (CREATE_INSTANT_INVITE, "초대 만들기"), (CHANGE_NICKNAME, "별명 변경"),
    (CONNECT, "음성 참여"), (SPEAK, "말하기"), (STREAM, "화면 공유"), (USE_VAD, "음성 감지"),
]


def describe(bits: int) -> str:
    """권한 비트를 사람이 읽는 이름으로. dry-run 출력이 숫자면 아무도 검토하지 못한다."""
    if not bits:
        return "없음"
    known = [name for bit, name in _NAMES if bits & bit]
    rest = bits & ~sum(bit for bit, _ in _NAMES)
    if rest:
        known.append(f"기타(0x{rest:x})")
    return " · ".join(known)
