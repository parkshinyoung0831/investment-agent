"""Server Guide(온보딩)의 단일 기준(SSOT).

처음 들어온 사람이 보는 화면이다. 채널 16개를 한꺼번에 보여 주면 어디부터 열어야 할지
모르므로, **무엇을 보러 왔는지**를 먼저 묻고 그 묶음을 가리킨다.

채널 key로 선언하고 적용 시점에 ID로 바꾼다 — 채널을 다시 만들어도 여기는 안 고친다.

**카드 채널의 가시성은 건드리지 않는다.** 온보딩 옵션으로 카드 채널을 '해금'하려면 그
채널을 @everyone에게서 숨겨야 하고, 그러면 카드 봇에도 채널마다 allow 오버라이트를 따로
달아야 한다. 하나 빠뜨리면 카드가 조용히 안 나가고 CI는 초록이다 — 이 저장소가 가장
싫어하는 실패 모양이라 택하지 않았다. 카드 채널 프롬프트는 길잡이 역할만 한다.

**대신 역할은 여기서 준다.** 서버의 기본값은 읽기 전용이고(roles.py), 라운지에서
말하려면 `◆ 라운지` 역할이 있어야 한다. 그 역할을 여기서 스스로 고르게 하는 이유는
문턱 자체가 필터이기 때문이다 — 스팸 봇은 보통 온보딩을 통과하지 않는다. 사람에게는
클릭 한 번이고, 그 한 번이 '읽으러 온 사람'과 '말하러 온 사람'을 가른다.
"""
from __future__ import annotations

from typing import Any

# Server Guide를 켤지. **지금은 끈다.**
#
# Discord는 온보딩을 켜 두려면 "@everyone이 **글을 쓸 수 있는** 채널 5개"를 요구한다
# (기본 채널 7개 중 5개). 우리 서버는 카드 채널이 전부 읽기 전용이라 그 수를 채우려면
# 채팅 채널을 넷 더 만들어 @everyone에게 열어야 하고, 그러면 '기본은 읽기 전용'이라는
# 전제가 사라진다. 요건을 못 맞춘 채로 갱신을 시도하면 350001로 막힌다.
#
# 그래서 처음 온 사람 안내는 #시작하기 안내문(guide.py)이 맡는다. 아래 프롬프트 선언은
# 지우지 않고 둔다 — 커뮤니티 채널이 다섯을 넘는 날 이 한 줄만 True로 바꾸면 된다.
ENABLED = False

# 처음 화면에 기본으로 펼쳐 둘 채널(key). 나머지는 프롬프트가 안내한다.
DEFAULT_CHANNELS = [
    "welcome", "rules", "notice",
    "macro_daily", "econ_calendar_release", "macro_alert",
    "earnings", "earnings_calendar", "lounge",
]

# type 0 = MULTIPLE_CHOICE
PROMPTS: list[dict[str, Any]] = [
    {
        "title": "무엇을 보러 오셨나요?",
        "type": 0,
        "single_select": False,
        "required": False,
        "in_onboarding": True,
        "options": [
            {
                "title": "매일 시장 흐름",
                "description": "금리·물가·환율·원자재를 매일 한 장으로",
                "emoji_name": "📊",
                "channels": ["macro_daily", "econ_calendar_release", "macro_alert"],
            },
            {
                "title": "관심종목 실적",
                "description": "종목 1개 스레드에 공시를 누적 · 섹터 태그로 걸러 봅니다",
                "emoji_name": "💰",
                "channels": ["earnings", "earnings_calendar"],
            },
            {
                "title": "거장 13F와 전략",
                "description": "분기 보유 공시 비교와 월간 자산배분",
                "emoji_name": "🔭",
                "channels": ["gurus", "strategy"],
            },
        ],
    },
    {
        "title": "이야기도 나누실 건가요?",
        "type": 0,
        "single_select": True,
        "required": False,
        "in_onboarding": True,
        "options": [
            {
                "title": "네, 라운지에서 이야기할래요",
                "description": "라운지 채팅·음성과 실적 스레드 댓글이 열립니다",
                # 카테고리 이름에 쓰는 ◆ 같은 기하 기호는 Discord가 이모지로 받지 않는다(50035).
                "emoji_name": "💬",
                "channels": ["lounge", "lounge_voice"],
                "roles": ["member"],
            },
            {
                "title": "읽기만 할게요",
                "description": "카드만 보고 갑니다 · 나중에 언제든 바꿀 수 있습니다",
                "emoji_name": "👀",
                "channels": ["welcome"],
                "roles": [],
            },
        ],
    },
]


def build(channel_ids: dict[str, str],
          role_ids: dict[str, str] | None = None) -> dict[str, Any]:
    """채널·역할 key -> ID 표를 받아 Discord가 받는 온보딩 payload를 만든다.

    서버에 없는 key는 조용히 빠진다 — 매니페스트에서 채널을 지웠을 때 온보딩 적용이
    통째로 실패하는 것보다, 그 항목만 빠지는 편이 낫다. 다만 역할이 빠지면 그 옵션은
    '아무 일도 하지 않는 버튼'이 되므로, 역할을 선언한 옵션은 역할이 없으면 통째로 뺀다.
    """
    role_ids = role_ids or {}
    prompts = []
    # Discord는 새로 만드는 프롬프트·옵션에도 id를 요구하고(50035), 저장할 때 진짜
    # 스노플레이크로 갈아 끼운다. 선언 순서에서 만든 자리표를 넘긴다.
    counter = 0
    for index, prompt in enumerate(PROMPTS):
        options = []
        for option in prompt["options"]:
            ids = [channel_ids[key] for key in option["channels"] if key in channel_ids]
            wanted_roles = option.get("roles") or []
            granted = [role_ids[key] for key in wanted_roles if key in role_ids]
            if len(granted) != len(wanted_roles):
                continue
            if not ids and not granted:
                continue
            counter += 1
            options.append({
                "id": str(counter),
                "title": option["title"],
                "description": option["description"],
                "emoji_name": option["emoji_name"],
                "channel_ids": ids,
                "role_ids": granted,
            })
        if not options:
            continue
        prompts.append({
            "id": str(index),
            "title": prompt["title"],
            "type": prompt["type"],
            "single_select": prompt["single_select"],
            "required": prompt["required"],
            "in_onboarding": prompt["in_onboarding"],
            "options": options,
        })
    return {
        "prompts": prompts,
        "default_channel_ids": [channel_ids[key] for key in DEFAULT_CHANNELS
                                if key in channel_ids],
        "enabled": ENABLED,
        # 1 = ADVANCED — 기본 채널만이 아니라 프롬프트가 가리키는 채널도 요건 계산에 넣는다.
        "mode": 1,
    }
