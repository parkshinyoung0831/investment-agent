"""institutional 7인 레이더의 코드 상수.

추적 대상 manager(cik/name/fund_name/is_active)의 런타임 SSOT는 이 모듈의
`MANAGER_CATALOG`다. Supabase `institutional.managers` 테이블은 없다 — SEC
사실(filings/positions)만 Supabase가 소유하고, "누구를 추적하는가"는 코드
설정이 소유한다.

역할(signal_role) 해석:
- copyable_core    : 포트폴리오를 보고 종목을 공부하기 좋은 핵심 대상
- market_signal    : 시장 주도주·매크로·정책 전환을 읽는 방향 레이더
- contrarian_value : 안전마진·현금·역발상으로 과열기에 휩쓸리지 않는 디프 밸류 기준점

blind_spots: 해당 운용사에서 13F가 특히 못 보는 자산. 알림 caveat 생성에 쓴다.

Off-13F Watchlist(13F 정기 추적 대상 아님, 참고용):
- Michael Burry / Scion Asset Management — 풋옵션·역발상 신호는 분기말 명목 기준이라
  13F 정기 추적보다 별도 관찰(Off-13F)이 더 적합.
"""
from __future__ import annotations

SIGNAL_ROLES = frozenset({"copyable_core", "market_signal", "contrarian_value"})

# 13F 정기 추적에서 제외하고 별도 관찰만 하는 후보(코드에서 수집하지 않음).
OFF_13F_WATCHLIST: tuple[str, ...] = ("Michael Burry / Scion Asset Management",)
# 화면 그룹 라벨(표시 순서 고정). signal_role → 한국어 그룹명. analysis.py도 이 값을 쓴다.
SIGNAL_GROUP_LABELS: tuple[tuple[str, str], ...] = (
    ("copyable_core", "따라 공부하기 좋은 핵심 포트폴리오"),
    ("market_signal", "시장 방향 레이더"),
    ("contrarian_value", "역발상 가치 레이더"),
)

# SEC fact가 아닌 화면·해석 설정. key는 stable manager CIK다.
MANAGER_PRESENTATION: dict[str, dict[str, object]] = {
    "0001067983": {"name_ko": "워런 버핏", "fund_name_ko": "버크셔 해서웨이", "strategy_group": "value", "signal_role": "copyable_core", "copyability": "high", "display_order": 1, "blind_spots": ["bond"]},
    "0001336528": {"name_ko": "빌 애크먼", "fund_name_ko": "퍼싱 스퀘어", "strategy_group": "concentrated_quality", "signal_role": "copyable_core", "copyability": "high", "display_order": 2, "blind_spots": ["short", "derivative"]},
    "0001647251": {"name_ko": "크리스 혼", "fund_name_ko": "TCI 펀드 매니지먼트", "strategy_group": "quality_growth", "signal_role": "copyable_core", "copyability": "medium", "display_order": 3, "blind_spots": ["foreign"]},
    "0001167483": {"name_ko": "체이스 콜먼", "fund_name_ko": "타이거 글로벌", "strategy_group": "innovation_growth", "signal_role": "copyable_core", "copyability": "medium", "display_order": 4, "blind_spots": ["private", "foreign"]},
    "0001536411": {"name_ko": "스탠리 드러켄밀러", "fund_name_ko": "듀케인 패밀리 오피스", "strategy_group": "macro_momentum", "signal_role": "market_signal", "copyability": "medium", "display_order": 5, "blind_spots": ["short", "bond", "foreign", "derivative"]},
    "0001656456": {"name_ko": "데이비드 테퍼", "fund_name_ko": "아팔루사", "strategy_group": "macro_policy", "signal_role": "market_signal", "copyability": "medium", "display_order": 6, "blind_spots": ["short", "bond", "derivative"]},
    "0001061768": {"name_ko": "세스 클라먼", "fund_name_ko": "바우포스트 그룹", "strategy_group": "contrarian_value", "signal_role": "contrarian_value", "copyability": "medium", "display_order": 7, "blind_spots": ["bond", "private", "foreign"]},
}


def presentation_for(manager_cik: str) -> dict[str, object]:
    """관리자 사실에 붙일 화면용 해석. 미등록 manager도 수집은 가능하다."""
    return dict(MANAGER_PRESENTATION.get(str(manager_cik).zfill(10), {}))


# 추적 대상 manager의 SEC 사실. key는 10자리 manager CIK.
MANAGER_CATALOG: dict[str, dict[str, object]] = {
    "0001067983": {"name": "Warren Buffett", "fund_name": "Berkshire Hathaway", "is_active": True},
    "0001336528": {"name": "Bill Ackman", "fund_name": "Pershing Square", "is_active": True},
    "0001647251": {"name": "Chris Hohn", "fund_name": "TCI Fund Management", "is_active": True},
    "0001167483": {"name": "Chase Coleman", "fund_name": "Tiger Global", "is_active": True},
    "0001536411": {"name": "Stanley Druckenmiller", "fund_name": "Duquesne Family Office", "is_active": True},
    "0001656456": {"name": "David Tepper", "fund_name": "Appaloosa", "is_active": True},
    "0001061768": {"name": "Seth Klarman", "fund_name": "Baupost Group", "is_active": True},
}


def guru_display_name(manager_cik: str) -> str | None:
    """이 거장의 표시 이름. 포럼 태그와 스레드 제목이 여기서 나온다.

    전에는 사람마다 포럼 **채널**을 하나씩 뒀다. 13F는 분기 공시라 한 사람이 연
    4건인데, 그 4건을 위해 채널·권한·감시 대상이 하나씩 늘었다. 실적이 이미
    "포럼 1개 + 대상별 스레드"인데 거장만 달랐다.

    지금은 포럼 하나에 사람마다 스레드 하나다. 늘리는 자리는 여전히
    `MANAGER_PRESENTATION` 한 줄이고, 채널을 만들 필요가 없어졌다.
    """
    name = MANAGER_PRESENTATION.get(str(manager_cik).zfill(10), {}).get("name_ko")
    return name if isinstance(name, str) and name.strip() else None


def guru_thread_topic(manager_cik: str) -> str | None:
    """스레드 첫 줄에 붙는 설명. 선언과 발송이 같은 문장을 쓰게 한다."""
    cik = str(manager_cik).zfill(10)
    presentation = MANAGER_PRESENTATION.get(cik, {})
    name, fund = presentation.get("name_ko"), presentation.get("fund_name_ko")
    if not isinstance(name, str) or not isinstance(fund, str):
        return None
    return f"{name} ({fund}) 13F 분기 보유 공시 기록"


def guru_tags() -> tuple[dict[str, object], ...]:
    """거장별 포럼 태그 선언. 화면 표시 순서(display_order)를 그대로 따른다.

    이 튜플이 곧 "거장을 한 명 추가한다"의 전부다 — `MANAGER_PRESENTATION`에
    한 줄을 넣으면 포럼 태그도, 스레드 제목도, 발송 대상도 여기서 함께 나온다.

    Discord 포럼 태그는 상한이 20개다. 그 위로 늘리려면 그때 축을 다시 잡는다.
    """
    rows = []
    for cik, presentation in MANAGER_PRESENTATION.items():
        name = guru_display_name(cik)
        topic = guru_thread_topic(cik)
        if not name or not topic:
            continue
        rows.append({
            "cik": cik,
            "name": name,
            "topic": topic,
            "display_order": int(presentation.get("display_order") or 0),
        })
    return tuple(sorted(rows, key=lambda row: (row["display_order"], row["cik"])))


def all_managers(catalog: dict[str, dict[str, object]] | None = None) -> list[dict[str, object]]:
    """활성 여부와 무관한 전체 manager 사실 + 화면 해석. cik 오름차순."""
    source = MANAGER_CATALOG if catalog is None else catalog
    return [
        {"manager_cik": cik, **row, **presentation_for(cik)}
        for cik in sorted(source)
        for row in (source[cik],)
    ]


def active_managers(catalog: dict[str, dict[str, object]] | None = None) -> list[dict[str, object]]:
    """추적 중인 manager 사실 + 화면 해석. display_order로 정렬한다."""
    rows = [row for row in all_managers(catalog) if row.get("is_active")]
    return sorted(rows, key=lambda row: int(row.get("display_order", 9999)))

# 13F 사각지대 코드 → 한국어 라벨. 13F가 구조적으로 못 보는 자산군이다.
BLIND_SPOT_LABELS: dict[str, str] = {
    "short": "숏 포지션",
    "derivative": "장외파생·스왑",
    "foreign": "해외 상장주",
    "bond": "채권·현금",
    "private": "비상장·프리IPO",
}


def blind_spot_caveat(codes) -> str:
    """blind_spots 코드 목록을 운용사별 한국어 caveat 한 줄로 만든다."""
    labels = [BLIND_SPOT_LABELS[c] for c in (codes or []) if c in BLIND_SPOT_LABELS]
    if not labels:
        return ""
    return "⚠️ 13F 사각지대: " + "·".join(labels) + "는 이 포트폴리오에 보이지 않습니다."
