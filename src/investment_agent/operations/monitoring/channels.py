"""운영 채널의 기대 주기 선언 — '조용한 게 정상인가'를 판정하는 기준.

**워크플로가 초록인데 카드가 없을 수 있다.** 실행 상태만으로는 Discord 전달 상태를
확인할 수 없으므로, 채널 활동도 함께 점검해 그 간극을 메운다.

`quiet_hours`가 판정의 전부다.
- 숫자면 그 시간을 넘겨 조용할 때 경고한다. 주기가 정해진 채널만 이 값을 갖는다.
- None이면 **침묵을 문제로 보지 않는다**. 발표·임계 돌파·공시처럼 사건이 있어야
  우는 채널은 조용한 게 정상이고, 그걸 경고로 칠하면 매일 거짓 경보가 뜬다.

항목은 `env`(채널 ID를 담은 환경변수) 또는 `name`(길드에서 이름으로 찾는다) 중
하나를 갖는다. 후자는 채널이 늘어날 수 있는 곳에 쓴다 — 거장처럼.

`DISCORD_CHANNEL_*`는 Discord 관리자 동기화와 운영 manifest의 선언이다. 실제 알림
producer의 목적지는 `notifications.subscriptions`에서 읽어야 하므로, 이 목록은 채널
구조와 환경변수 이름을 검증하는 용도로만 유지한다. 이름은
`src/investment_agent/notifications/discord_admin/manifest.py`가 SSOT이고,
어긋나면 tests/ops/test_channels.py가 잡는다.
"""
from __future__ import annotations

from typing import Any


_DAY = 24

# forum=True면 창 내 건수를 셀 수 없다(포럼의 글은 메시지가 아니라 스레드다).
# 마지막 활동 시각은 last_message_id로 읽히므로 생존 판정은 그대로 된다.
WATCHED: list[dict[str, Any]] = [
    {
        "env": "DISCORD_CHANNEL_MACRO_DAILY", "label": "오늘의-시장",
        "cadence": "월~토 12:20", "quiet_hours": 52,
        # 토요일 발송 뒤 월요일까지 48시간이 빈다. 여유 4시간을 더해 일요일에 울지 않게.
    },
    {
        "env": "DISCORD_CHANNEL_ECON_CALENDAR_RELEASE", "label": "지표-발표",
        "cadence": "발표 있을 때만", "quiet_hours": None,
    },
    {
        "env": "DISCORD_CHANNEL_MACRO_ALERT", "label": "시장-경보",
        "cadence": "임계 돌파 시", "quiet_hours": None,
    },
    {
        "env": "DISCORD_CHANNEL_EARNINGS_CALENDAR", "label": "실적-캘린더",
        "cadence": "월요일 08:10", "quiet_hours": 10 * _DAY,
        # 주 1회지만 그 주에 발표 예정이 없으면 아예 안 나간다. 2주 반이 비면 그때 묻는다.
    },
    {
        "env": "DISCORD_CHANNEL_EARNINGS", "label": "실적-리포트", "forum": True,
        "cadence": "공시가 나올 때", "quiet_hours": None,
    },
    {
        "env": "DISCORD_CHANNEL_GURUS", "label": "13f-요약",
        "cadence": "분기 제출 때", "quiet_hours": None,
    },
    # 거장은 포럼 하나에 사람마다 스레드 하나다. 사람 수만큼 감시 대상이 늘지 않는다.
    {
        "env": "DISCORD_CHANNEL_GURU_FORUM", "label": "거장-13f", "forum": True,
        "cadence": "분기 제출 때", "quiet_hours": None,
    },
    {
        "env": "DISCORD_CHANNEL_STRATEGY_MONTHLY", "label": "월간-전략-요약",
        "cadence": "매월 말", "quiet_hours": 40 * _DAY,
    },
    {
        "env": "DISCORD_CHANNEL_STRATEGY_FORUM", "label": "전략-아카이브", "forum": True,
        "cadence": "매월 말", "quiet_hours": 40 * _DAY,
    },
    {
        "env": "DISCORD_CHANNEL_AI_REPORTS", "label": "투자-리포트",
        # 하네스가 켜져 있는 날에만 판단이 나온다. 노트북을 며칠 꺼 둘 수 있으므로
        # 하루가 아니라 사흘을 기준으로 잡는다.
        "cadence": "판단이 나온 날", "quiet_hours": 3 * _DAY,
    },
    {
        "env": "DISCORD_CHANNEL_AI_TRADES", "label": "매매-기록",
        # 매매가 없는 날이 정상이다. 조용하다고 고장은 아니므로 묻지 않는다.
        "cadence": "실제 체결이 있을 때", "quiet_hours": None,
    },
    {
        "env": "DISCORD_CHANNEL_AI_APPROVALS", "label": "투자-승인",
        "cadence": "승인할 주문안이 있을 때", "quiet_hours": None,
    },
    {
        "env": "DISCORD_CHANNEL_OPS_DIGEST", "label": "운영-요약",
        "cadence": "매일 15:40", "quiet_hours": 30,
        # 일일 점검 카드가 이 채널에 도착하는지 직접 확인한다. 스케줄 지연과
        # Discord API 반영 시간을 감안해 24시간보다 여유를 둔다.
    },
    # 실패 채널은 조용한 것이 정상이다. 침묵을 경고로 칠하면 매일 거짓 경보가 뜨고,
    # 그러면 진짜 실패가 왔을 때 아무도 보지 않는다.
    {
        "env": "DISCORD_CHANNEL_OPS_ACTIONS", "label": "액션-실패",
        "cadence": "워크플로가 실패할 때", "quiet_hours": None,
    },
    {
        "env": "DISCORD_CHANNEL_OPS_LOCAL", "label": "로컬-실패",
        "cadence": "로컬 하네스가 실패할 때", "quiet_hours": None,
    },
    {
        "env": "DISCORD_CHANNEL_OPS_DELIVERY", "label": "발송-실패",
        "cadence": "outbox가 끝내 못 보낼 때", "quiet_hours": None,
    },
]
