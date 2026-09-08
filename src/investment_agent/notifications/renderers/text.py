"""알림 embed 본문에 쓰는 모노스페이스 표기 헬퍼.

Discord embed에는 표도 색도 없다. 남는 표현 수단이 코드블록 안의 정렬 하나뿐이라
알림 패키지 셋이 같은 폭 계산을 쓴다 — 한글·전각은 두 칸을 차지하므로 글자 수가
아니라 표시 폭으로 재야 열이 맞는다.

막대는 색을 못 쓰는 자리에서 크기·비중을 모양으로 말한다(DESIGN-system.md의
'시맨틱 색은 텍스트 전용' 규칙 때문에 채움 막대에는 어차피 색을 못 준다).
"""
from __future__ import annotations

FILLED, EMPTY = "█", "░"

# 유니코드 MINUS SIGN(−, U+2212)은 코드포인트만 보면 전각 범위에 걸리지만
# 실제 모노스페이스 렌더링에서는 한 칸이다 — 이걸 두 칸으로 세면 그 기호가
# 낀 열만 구분자 스페이스가 하나 모자라 표가 어긋난다.
_NARROW_EXCEPTIONS = {"−"}


def _char_width(ch: str) -> int:
    if ch in _NARROW_EXCEPTIONS:
        return 1
    return 2 if ord(ch) > 0x1100 else 1


def width(text: str) -> int:
    """모노스페이스 표시 폭. 한글·전각은 두 칸."""
    return sum(_char_width(ch) for ch in text)


def clip(text: str, limit: int) -> str:
    """표시 폭 기준으로 자른다. 글자 수로 자르면 한글이 두 칸이라 넘친다."""
    out, used = [], 0
    for ch in text:
        step = _char_width(ch)
        if used + step > limit:
            break
        out.append(ch)
        used += step
    return "".join(out)


def tail(text: str, limit: int) -> str:
    """표시 폭 기준으로 뒤에서부터 남긴다."""
    out, used = [], 0
    for ch in reversed(text):
        step = _char_width(ch)
        if used + step > limit:
            break
        out.append(ch)
        used += step
    return "".join(reversed(out))


def shorten(text: str, limit: int) -> str:
    """가운데를 줄여 앞뒤를 남긴다.

    앞에서만 자르면 'Energy Generation And Storage Sales'와 '…Storage Leasing'이 똑같이
    'Energy Generatio'가 된다 — 세그먼트 이름은 뒤쪽이 서로를 구분한다.
    말줄임표(…)는 폰트에 따라 한 칸이 되기도 두 칸이 되기도 해서 열이 어긋난다. 점 두 개로 둔다.
    """
    if width(text) <= limit:
        return text
    keep = max(3, limit // 3)
    return clip(text, limit - keep - 2) + ".." + tail(text, keep)


def pad(text: str, limit: int, *, right: bool = False) -> str:
    fill = " " * max(0, limit - width(text))
    return fill + text if right else text + fill


def table(rows: list[tuple[str, ...]], *, right: tuple[int, ...] = ()) -> str:
    """열 폭을 표시 폭 기준으로 맞춘 모노스페이스 표(코드블록)."""
    if not rows:
        return ""
    columns = len(rows[0])
    widths = [max(width(row[i]) for row in rows) for i in range(columns)]
    lines = [
        "  ".join(
            pad(cell, widths[i], right=i in right) for i, cell in enumerate(row)
        ).rstrip()
        for row in rows
    ]
    return "```\n" + "\n".join(lines) + "\n```"


def bar(ratio: float | None, *, cells: int = 6) -> str:
    """0~1 비율을 채움 막대로.

    값이 있는데 0칸이 되면 '없음'과 구분되지 않으므로 양수는 최소 한 칸을 채운다.
    """
    if ratio is None:
        return EMPTY * cells
    clamped = max(0.0, min(1.0, ratio))
    filled = max(1, round(clamped * cells)) if clamped > 0 else 0
    return FILLED * filled + EMPTY * (cells - filled)
