"""8-K 실적 속보의 가이던스 문장을 상태 태그로 접는 순수 변환.

Discord 속보 embed와 Dashboard 실적 화면이 같은 문장을 주장해야 하므로 알림 패키지가
아니라 Reporting 계약이 소유한다. 원문은 8-K 보도자료 파싱 결과(`guidance_summary`)이고,
여기서는 DB나 외부 호출 없이 문자열만 다룬다.

## 방향 배지를 언제 달 것인가

원문은 `extract_guidance_text()`가 고른 **보도자료 문단 최대 3개**를 ` | `로 이은 것이다
(문단마다 25~500자). 즉 한 문단 안에 실적 서술과 전망이 같이 들어 있고, 여기서 상향/하향을
읽어내야 한다.

그래서 동사만 보고 판정하지 않는다 — "revenue increased 12%"는 실적 서술이지 전망 상향이
아니다. 방향 동사가 **전망을 가리키는 명사**(guidance/outlook/forecast/expectations/targets)를
실제로 목적어로 잡을 때만 배지를 단다. 능동("raised its full-year guidance")과
수동("guidance was lowered") 둘 다 보되, 수동은 조동사를 요구한다 — 그것이 없으면
"guidance reflects cost cut initiatives" 같은 명사구까지 하향으로 읽힌다. 문단 경계(`|`)도
넘지 않는다. 다른 문단의 동사가 이 문단의 전망을 수식할 수는 없다.

확신이 없으면 배지를 달지 않고 원문 첫 조각을 그대로 보여준다. 잘못된 방향을 단언하는 것이
아무 말도 안 하는 것보다 나쁘다.
"""
from __future__ import annotations

import re

# 전망을 가리키는 명사. 이것이 목적어일 때만 방향 동사를 전망 변경으로 읽는다.
_OUTLOOK = r"(?:guidance|outlook|forecasts?|expectations?|projections?|targets?)"

# 능동형은 동사와 명사 사이에 수식어("its full-year 2026 revenue")를 40자까지 허용한다.
_ACTIVE_GAP = 40
# 수동형은 명사가 먼저 오므로 창을 좁게 잡고, 조동사를 반드시 요구한다.
_PASSIVE_GAP = 25
_AUXILIARY = r"(?:was|were|is|are|has|have|had|been|being|remains?)\s+(?:been\s+)?"

_RAISE_BADGE = "🟢 연간 실적 전망 상향 (Raises Outlook)"
_LOWER_BADGE = "🔴 연간 실적 전망 하향 (Lowers Outlook)"
_MAINTAIN_BADGE = "🔵 연간 실적 전망 유지 (Maintains Outlook)"

# (배지, 능동형 동사, 수동형 분사)
_DIRECTIONS: tuple[tuple[str, str, str], ...] = (
    (
        _RAISE_BADGE,
        r"(?:rais(?:e[sd]?|ing)|increas(?:e[sd]?|ing)|boost(?:s|ed|ing)?|lift(?:s|ed|ing)?|upgrad(?:e[sd]?|ing))",
        r"(?:raised|increased|boosted|lifted|upgraded)",
    ),
    (
        _LOWER_BADGE,
        r"(?:lower(?:s|ed|ing)?|reduc(?:e[sd]?|ing)|cut(?:s|ting)?|trim(?:s|med|ming)?|downgrad(?:e[sd]?|ing))",
        r"(?:lowered|reduced|cut|trimmed|downgraded)",
    ),
    (
        _MAINTAIN_BADGE,
        r"(?:reaffirm(?:s|ed|ing)?|reiterat(?:e[sd]?|ing)|maintain(?:s|ed|ing)?|confirm(?:s|ed|ing)?)",
        r"(?:reaffirmed|reiterated|maintained|confirmed)",
    ),
)


def _direction_pattern(active: str, passive: str) -> re.Pattern[str]:
    """동사가 전망 명사를 잡는 자리만 고른다. `|`는 문단 경계라 넘지 않는다."""
    return re.compile(
        rf"\b{active}\b[^|]{{0,{_ACTIVE_GAP}}}?\b{_OUTLOOK}\b"
        rf"|\b{_OUTLOOK}\b[^|]{{0,{_PASSIVE_GAP}}}?\b{_AUXILIARY}{passive}\b",
        re.IGNORECASE,
    )


_DIRECTION_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (badge, _direction_pattern(active, passive)) for badge, active, passive in _DIRECTIONS
)

# 조동사 없이도 유지로 읽는 유일한 형태. 동사가 아니라 상태를 말하는 말이라 오탐이 없다.
_UNCHANGED_RE = re.compile(
    rf"\b{_OUTLOOK}\b[^|]{{0,{_PASSIVE_GAP}}}?\bunchanged\b", re.IGNORECASE
)

# 다음 분기 가이던스를 따로 제시했는지. 연간 전망 방향과 함께 나올 수 있어 배타적이지 않다.
_NEXT_QUARTER_RE = re.compile(
    r"\bissues?\s+guidance\b"
    r"|\bguidance\s+for\s+(?:the\s+)?(?:q[1-4]|first|second|third|fourth)\b"
    r"|\b(?:q[1-4]|first|second|third|fourth)[- ]quarter\s+guidance\b",
    re.IGNORECASE,
)

# 배지가 없을 때 원문 첫 조각을 그대로 보여줄 최대 길이.
_FALLBACK_MAX_CHARS = 60


def format_guidance_headline(guidance_raw: str | None) -> str | None:
    """원문 영어 문장에서 지저분한 세부내역을 걷어내고 직관적인 한글 상태 태그로 정제한다."""
    if not guidance_raw:
        return None

    badges: list[str] = []
    for badge, pattern in _DIRECTION_RULES:
        if pattern.search(guidance_raw):
            badges.append(badge)
            break  # 방향은 하나만 — 상향/하향/유지가 동시에 참일 수는 없다.
    else:
        if _UNCHANGED_RE.search(guidance_raw):
            badges.append(_MAINTAIN_BADGE)

    if _NEXT_QUARTER_RE.search(guidance_raw):
        badges.append("📌 다음 분기 가이던스 제시")

    if badges:
        return " · ".join(badges)

    first_part = guidance_raw.split("|")[0].strip().lstrip("-").strip()
    if len(first_part) <= _FALLBACK_MAX_CHARS:
        return first_part
    return None


__all__ = ["format_guidance_headline"]
