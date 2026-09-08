"""서버 채널 구조의 단일 기준(SSOT).

여기가 서버의 '설계도'다. 채널을 바꾸고 싶으면 이 파일을 고치고 sync를 돌린다 —
Discord UI에서 직접 만들면 이 파일과 어긋나고, 어긋난 순간 어느 쪽이 맞는지 알 수 없다.

`env`가 있는 채널은 sync가 채널 ID를 `.env`의 그 변수에 써 넣는다. 실제
notification producer의 목적지는 이 값을 각 워크플로의 env(`DISCORD_CHANNEL_*`)와
`notifications/subscriptions.py`의 `KIND_ENV` 매핑으로 직접 읽어 결정한다.

**카테고리는 출처가 아니라 읽는 주기로 가른다.** 매일 보는 것(MARKET DESK), 분기에
몰리는 것(EARNINGS), 가끔 보는 것(STRATEGY / GURUS)을 한 칸에 두면 무엇을 매일 열어야 하는지가
안 보인다.

**실적은 포럼이다.** 관심종목 50개 × 분기 = 연 200건이 분기마다 2주에 몰린다. 한 건이
PNG 대시보드 + 세그먼트 카드라 일반 채널에서는 어제 본 것을 다시 찾지 못한다. 포럼은
종목 1개 = 스레드 1개에 공시를 누적하고 섹터 태그로 걸러 읽을 수 있다.

**운영 채널은 출처로 가른다.** Actions 실패·로컬 실패·발송 실패·일일 요약은
서로 다른 사람이 다른 방법으로 고친다. 한 채널에 섞으면 무엇을 지금 내가 할 수
있는지가 안 보인다.

**운영(prod)과 실험(lab)을 갈라 둔다.** 카드 디자인을 다듬을 때 운영 채널로 쏘면
진짜 카드와 테스트 카드가 섞여 처음 보는 사람은 구분하지 못한다.
"""
from __future__ import annotations

from typing import Any

from investment_agent.data.institutional.domain.managers import guru_tags

TEXT = 0
VOICE = 2
CATEGORY = 4
FORUM = 15

# 실적 포럼의 태그. `universe.entities.sic_division_name`이 그대로 업종이 되고,
# 마지막 하나만 보고 구간(연간 10-K)을 가른다. Discord 상한은 포럼당 20개다.
# SIC 분류라 자동으로 붙는다 — 관심종목이 바뀌어도 손으로 그룹을 넣지 않는다.
# 발송 코드가 쓰는 SIC division -> 태그 이름 대응은 src/investment_agent/notifications/channels/routing.py에 있고,
# 둘이 어긋나면 tests/discord_admin/test_sync_plan.py가 잡는다.
EARNINGS_TAGS: list[str] = [
    "제조", "금융·부동산", "서비스", "운송·유틸리티", "소매",
    "광업·에너지", "도매", "건설", "농림어업",
    "연간보고서",
    # 발표 예정 안내도 같은 종목 스레드에 쌓인다. 지나간 예정과 실제 결과를
    # 태그로 갈라 읽을 수 있어야 한다.
    "발표예정",
]

# 전략 포럼 태그. 6개 활성 전략의 ID 대응
STRATEGY_TAGS: list[str] = [
    "GEM", "ADM", "DMSR", "GTAA5", "HAA-균형", "HAA-단순",
]

# (key, 카테고리 이름, [채널...]) — 순서가 서버 표시 순서다.
# 카테고리: private=True면 @everyone에게서 '채널 보기'를 막는다. 그 순간 카드 봇도 함께
#           막히므로 봇 오버라이트를 사람이 아니라 roles.py가 자동으로 붙인다.
# 채널: key / name / topic / env(채널 ID를 써 넣을 .env 변수, 없으면 None) / kind(기본 TEXT)
#       tags(포럼 전용) / role(Community 필수 채널 표시: "rules" | "updates")
LAYOUT: list[dict[str, Any]] = [
    {
        "key": "start",
        "name": "✦ START HERE",
        "channels": [
            {"key": "welcome", "name": "시작하기", "env": None,
             "topic": "ATLAS를 가장 빠르게 시작하는 곳 · 어떤 채널을 언제 열면 되는지 안내합니다"},
            {"key": "rules", "name": "서버-규칙", "env": None, "role": "rules",
             "topic": "참여 규칙과 면책 고지 · ATLAS는 투자 자문이 아니라 공개 데이터 정리 도구입니다"},
            {"key": "notice", "name": "업데이트-노트", "env": None,
             "topic": "카드·파이프라인 변경과 점검 공지"},
        ],
    },
    {
        "key": "market",
        "name": "📊 MARKET DESK",
        "channels": [
            {"key": "macro_daily", "name": "오늘의-시장",
             "env": "DISCORD_CHANNEL_MACRO_DAILY",
             "topic": "매일 한 장 · 주식·금리·환율·원자재와 레짐 게이지"},
            {"key": "econ_calendar_release", "name": "지표-발표",
             "env": "DISCORD_CHANNEL_ECON_CALENDAR_RELEASE",
             "topic": "CPI·고용·GDP 같은 신규 발표 지표만 · 발표가 없는 날은 조용합니다"},
            {"key": "macro_alert", "name": "시장-경보",
             "env": "DISCORD_CHANNEL_MACRO_ALERT",
             "topic": "장중 임계 돌파 감시 · 평일 매시간 확인합니다"},
        ],
    },
    {
        "key": "earnings",
        "name": "💰 EARNINGS",
        "channels": [
            {"key": "earnings_calendar", "name": "실적-캘린더",
             "env": "DISCORD_CHANNEL_EARNINGS_CALENDAR",
             "topic": "이번 주 관심종목 발표 예정 · 월요일 아침 한 장 (예정일은 확정이 아닙니다)"},
            {"key": "earnings", "name": "실적-리포트", "kind": FORUM,
             "env": "DISCORD_CHANNEL_EARNINGS", "tags": EARNINGS_TAGS,
             "topic": "관심종목 종목 1개 = 스레드 1개 · 공시를 누적해 보고, 스레드 안에 메모를 남기세요"},
        ],
    },
    {
        "key": "strategy",
        "name": "📐 STRATEGY",
        "channels": [
            {"key": "strategy", "name": "월간-전략-요약",
             "env": "DISCORD_CHANNEL_STRATEGY_MONTHLY",
             "topic": "팩터와 추세 기반 전략의 월간 자산배분 신호를 정리합니다 (6전략 한 장 비교)"},
            {"key": "strategy_forum", "name": "전략-아카이브", "kind": FORUM,
             "env": "DISCORD_CHANNEL_STRATEGY_FORUM", "tags": STRATEGY_TAGS,
             "topic": "전략별 월간 배분 기록 아카이브 · 태그로 전략을 선택해 조회하세요"},
        ],
    },
    {
        "key": "gurus",
        "name": "🏛 GURUS",
        "channels": [
            {"key": "gurus", "name": "13f-요약",
             "env": "DISCORD_CHANNEL_GURUS",
             "topic": "분기마다 거장 전체를 한 장으로 비교합니다 · 13F는 실시간 거래 정보가 아닙니다"},
            # 사람마다 채널을 두지 않는다. 13F는 분기 공시라 한 사람이 연 4건인데,
            # 그 4건을 위해 채널·권한·감시 대상이 하나씩 늘었다. 실적과 같은 모양으로
            # **포럼 하나에 사람마다 스레드 하나**를 둔다 — 태그는 카탈로그에서 나오므로
            # 거장을 늘려도 여기를 고칠 일이 없다.
            {"key": "guru_forum", "name": "거장-13f", "kind": FORUM,
             "env": "DISCORD_CHANNEL_GURU_FORUM",
             "tags": [str(row["name"]) for row in guru_tags()],
             "topic": "거장 1명 = 스레드 1개 · 분기 공시를 누적해 한 사람의 흐름으로 읽습니다"},
        ],
    },
    {
        "key": "community",
        "name": "◆ COMMUNITY",
        "channels": [
            {"key": "lounge", "name": "라운지", "env": None,
             "topic": "투자·시장·ATLAS에 대해 자유롭게 이야기하는 공간"},
            {"key": "lounge_voice", "name": "라운지-보이스", "env": None,
             "kind": VOICE, "topic": None},
        ],
    },
    {
        "key": "lab",
        "name": "🧪 LAB",
        "private": True,
        "channels": [
            {"key": "lab_cards", "name": "랩-카드",
             "env": "DISCORD_CHANNEL_LAB_CARDS",
             "topic": "카드 디자인·형식 실험용 · 운영 발송이 아니며 발송 기록을 남기지 않습니다"},
            {"key": "lab_ops", "name": "랩-시스템로그",
             "env": "DISCORD_CHANNEL_LAB_OPS",
             "topic": "운영 알림·하트비트 형식 실험용"},
            {"key": "lab_forum", "name": "랩-포럼", "kind": FORUM,
             "env": "DISCORD_CHANNEL_LAB_FORUM", "tags": EARNINGS_TAGS,
             "topic": "실적 포럼과 같은 태그를 가진 실험용 포럼 · 스레드 형식을 여기서 먼저 확인합니다"},
        ],
    },
    {
        # 판단 → 승인 → 체결이 위에서 아래로 읽히도록 한 카테고리에 모은다.
        # 보유종목·비중·체결가가 다 드러나므로 공개하지 않는다.
        "key": "ai_investor",
        "name": "🤖 AI INVESTOR",
        "private": True,
        "channels": [
            {"key": "ai_reports", "name": "투자-리포트",
             "env": "DISCORD_CHANNEL_AI_REPORTS",
             "topic": "자동매매의 종합 판단과 상위 후보 심층 리포트 · 확보하지 못한 근거도 함께 적습니다"},
            {"key": "ai_approvals", "name": "투자-승인",
             "env": "DISCORD_CHANNEL_AI_APPROVALS",
             "topic": "AI 주문안 승인·거절 전용 · 서명 버튼만 유효하며 승인 뒤에도 계좌·시세·한도를 재검증합니다"},
            {"key": "ai_trades", "name": "매매-기록",
             "env": "DISCORD_CHANNEL_AI_TRADES",
             "topic": "실제로 나간 주문과 체결 기록 · 승인 ID로 판단까지 되짚을 수 있습니다"},
        ],
    },
    {
        # 운영 채널은 **어디서 났는가**로 가른다. 전에는 넷이 한 채널로 들어와서
        # "무엇을 내가 고칠 수 있는가"가 안 보였다 — Actions 실패는 재실행이나
        # 워크플로 수정, 로컬 실패는 내 노트북, 발송 실패는 Discord 권한·형식,
        # 요약은 아무것도 안 해도 되는 정상 기록이다.
        "key": "operations",
        "name": "⚙ OPERATIONS",
        "private": True,
        "channels": [
            {"key": "ops_digest", "name": "운영-요약",
             "env": "DISCORD_CHANNEL_OPS_DIGEST",
             "topic": "매일 한 장 · 예정된 것이 실제로 돌았는지 · 조용하면 정상입니다"},
            {"key": "ops_actions", "name": "액션-실패",
             "env": "DISCORD_CHANNEL_OPS_ACTIONS",
             "webhook": "DISCORD_WEBHOOK_OPS_ACTIONS",
             "topic": "GitHub Actions 워크플로 실패 · 원문 로그는 Actions 실행 페이지에 있습니다"},
            {"key": "ops_local", "name": "로컬-실패",
             "env": "DISCORD_CHANNEL_OPS_LOCAL",
             "webhook": "DISCORD_WEBHOOK_OPS_LOCAL",
             "topic": "로컬 하네스·실주문 경계에서 난 오류 · 이 컴퓨터가 켜져 있을 때만 옵니다"},
            {"key": "ops_delivery", "name": "발송-실패",
             "env": "DISCORD_CHANNEL_OPS_DELIVERY",
             "topic": "outbox가 끝내 못 보낸 알림 · ETL은 성공했는데 카드만 안 나간 경우입니다"},
            {"key": "mod_updates", "name": "모더레이터-알림", "env": None, "role": "updates",
             "topic": "Discord가 서버 관리자에게 보내는 시스템 공지 (Community 필수 채널)"},
        ],
    },
]


def channels() -> list[dict[str, Any]]:
    """(카테고리 key 포함) 평탄화된 채널 목록."""
    out = []
    for category in LAYOUT:
        for order, channel in enumerate(category["channels"]):
            # 재생성할 때 선언 순서를 그대로 서버 표시 순서로 쓴다 — 안 주면 새 채널이
            # 전부 카테고리 맨 아래로 붙어 배치가 무너진다.
            out.append({"kind": TEXT, **channel, "category": category["name"],
                        "category_key": category["key"], "position": order,
                        "private": bool(category.get("private"))})
    return out


def private_categories() -> list[dict[str, Any]]:
    """@everyone에게서 숨길 카테고리. 권한 계산(roles.py)이 여기를 읽는다."""
    return [c for c in LAYOUT if c.get("private")]


def webhook_bindings() -> dict[str, str]:
    """채널 key -> webhook URL을 써 넣을 .env 변수 이름.

    운영 알림은 봇 토큰이 아니라 webhook으로 나간다 — GitHub Actions에 봇 토큰을
    주지 않기 위해서다. 그래서 채널 ID와 별개로 URL이 필요하다.
    """
    return {c["key"]: c["webhook"] for c in channels() if c.get("webhook")}


def needs_community() -> bool:
    """포럼을 선언했으면 길드가 Community여야 한다 — 아니면 생성이 403으로 막힌다."""
    return any(c["kind"] == FORUM for c in channels())


def role_channel(role: str) -> dict[str, Any] | None:
    """Community 활성화에 필요한 규칙/모더레이터 채널 선언을 찾는다."""
    for channel in channels():
        if channel.get("role") == role:
            return channel
    return None
