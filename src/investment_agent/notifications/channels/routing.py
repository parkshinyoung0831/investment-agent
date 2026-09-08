"""관심종목을 실적 포럼의 어느 태그로 보낼지 정한다.

포럼 태그의 원본 선언은 `src/investment_agent/notifications/discord_admin/manifest.py`의 `EARNINGS_TAGS`이고,
여기는 **발송 시점에 쓰는 대응표**다. 둘을 한 파일로 합치지 않는 이유는
discord_admin이 로컬 전용 패키지라 CI 런타임에 끌고 들어오지 않기 위해서다.
어긋나면 `tests/discord_admin/test_sync_plan.py`가 잡는다.

분류 기준은 `universe.entities.sic_division_name`이다. **자동으로 붙는다** —
관심종목이 바뀌어도 사람이 그룹을 손으로 넣을 필요가 없다.

대가는 분포다. 추적 505종목 기준 Manufacturing이 202개(40%)로 몰리고, 관심종목
50개에서는 25개(50%)가 한 칸에 들어간다. SIC는 1937년의 규제 서류 분류라
비자·마스터카드가 Services, UNH가 Finance로 간다 — 투자 섹터와 다르다.
그래도 자동 분류를 택했다: 손으로 관리하는 group_name은 신규 편입 종목이
누락되면 태그 없이 나가고, 그 누락은 아무도 모르게 지나간다.
"""
from __future__ import annotations

from investment_agent.config import Config
from investment_agent.data.institutional.domain.managers import guru_tags
from investment_agent.notifications.channels.directory import guild_directory

# SIC 대분류 -> 태그 이름. 추적 유니버스에 실제로 나타나는 9종을 모두 덮는다.
# 빠진 분류가 있으면 그 종목은 태그 없이 나가므로, 새 분류가 보이면 여기에 더한다.
SIC_DIVISION_TAGS: dict[str, str] = {
    "Manufacturing": "제조",
    "Finance, Insurance & Real Estate": "금융·부동산",
    "Services": "서비스",
    "Transportation & Public Utilities": "운송·유틸리티",
    "Retail Trade": "소매",
    "Mining": "광업·에너지",
    "Wholesale Trade": "도매",
    "Construction": "건설",
    "Agriculture, Forestry & Fishing": "농림어업",
}

# 연간(10-K)은 분기와 읽는 깊이가 달라 섹터와 별도 축으로 건다.
ANNUAL_TAG = "연간보고서"


def tags_for(sic_division: str | None, fiscal_period: str | None) -> list[str]:
    """업종 태그 + (연간이면) 연간 태그. 모르는 분류는 태그 없이 보낸다."""
    tags = []
    division = SIC_DIVISION_TAGS.get(str(sic_division or "").strip())
    if division:
        tags.append(division)
    if str(fiscal_period or "").upper() == "FY":
        tags.append(ANNUAL_TAG)
    return tags


def thread_title(ctx: dict) -> str:
    """실적 카드 문맥에서 종목별 포럼 제목을 만든다."""
    return ticker_thread_title(str(ctx["ticker"]), str(ctx.get("title_main") or ctx["ticker"]))


def ticker_thread_title(ticker: str, name: str) -> str:
    """포럼 목록에서 한 줄로 읽히는 종목별 누적 스레드 제목.

    목록은 제목만 보이므로 **종목이 앞**에 와야 한다. 등급·구간은 각 메시지의
    카드에 담아 제목 정렬이 흔들리지 않게 한다.
    """
    return f"{ticker} · {name} · 실적 기록"


# 전략 ID -> 포럼 태그 이름
STRATEGY_TAGS_MAP: dict[str, str] = {
    "gem": "GEM",
    "adm": "ADM",
    "dmsr": "DMSR",
    "gtaa5": "GTAA5",
    "haa_bal": "HAA-균형",
    "haa_sim": "HAA-단순",
}

def strategy_thread_title(strategy_id: str) -> str:
    """전략 아카이브 포럼의 전략별 누적 스레드 제목.

    월간 배분이 전략마다 한 스레드에 쌓인다 — 매달 새 스레드를 만들면 6전략 × 12개월
    = 연 72개가 되어 "전략을 골라 이어 읽는다"는 포럼의 이유가 사라진다.
    """
    return f"{STRATEGY_TAGS_MAP.get(strategy_id, strategy_id)} · 월간 배분 기록"


def guru_names() -> dict[str, str]:
    """거장 CIK -> 표시 이름. 포럼 태그와 스레드 제목이 둘 다 이것에서 나온다.

    전에는 CIK -> 채널 이름이었고, 그 전에는 CIK -> 시크릿 이름이었다. 사람마다
    채널을 두면 13F 연 4건을 위해 채널·권한·감시 대상이 하나씩 늘고, 늘리는
    자리를 하나라도 빠뜨리면 그 사람의 카드가 조용히 갈 곳을 잃는다.

    지금은 포럼 하나에 사람마다 스레드 하나다. 원본은 거장 카탈로그 하나뿐이다.
    """
    return {str(row["cik"]): str(row["name"]) for row in guru_tags()}


def guru_thread_title(name: str) -> str:
    """거장 포럼의 스레드 제목 — 사람 1명 = 스레드 1개.

    분기마다 새 스레드를 만들면 7명 × 4분기 = 연 28개가 되어 "한 사람의 흐름"이
    끊긴다. 실적 포럼이 종목별로 누적하는 것과 같은 이유다. 어느 분기인지는 각
    카드가 말한다.
    """
    return f"{name} · 13F 기록"


def guru_tag_ids(manager_cik: str, target: str, *, config: Config) -> tuple[str, ...]:
    """그 거장의 포럼 태그 ID. 없으면 빈 튜플 — 태그 없이 보낸다."""
    name = guru_names().get(str(manager_cik).zfill(10))
    if not name:
        return ()
    return tuple(guild_directory(config).tag_ids_by_channel_id(target, (name,)))
