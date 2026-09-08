"""표시용 텍스트 정규화.

`reasons.py`·`formatting.py`는 Discord 관례(이모지·마크다운 강조)로 문장을 만든다.
그 장식이 카드에서는 노이즈이고(국기 이모지는 렌더 폰트에 없어 "us" 같은 글자로 깨진다),
embed에서도 강조가 겹치면 위계가 사라진다. 표시 직전에 여기서 걷어낸다.
"""
from __future__ import annotations

import re

# 이모지·기호 픽토그램. 디자인 기준은 "아이콘은 기하학적·최소".
_PICTOGRAPH = re.compile(
    "[\U0001F1E6-\U0001F1FF"   # 국기(regional indicator)
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F900-\U0001FAFF"
    "☀-➿"
    "️⃣]+"
)
# Discord 마크다운 강조. 카드(PNG)에서는 문법이 그대로 보인다.
_EMPHASIS = re.compile(r"(?<!\w)[_*]{1,2}(.+?)[_*]{1,2}(?!\w)")


def plain(text: str) -> str:
    """이모지와 마크다운 강조를 걷어낸 표시용 문장."""
    text = _PICTOGRAPH.sub("", text)
    text = _EMPHASIS.sub(r"\1", text)
    # 장식을 걷어내며 생긴 이중 공백과 줄 앞뒤 공백 정리.
    lines = [re.sub(r"[ \t]{2,}", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
