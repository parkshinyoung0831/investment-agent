"""종목을 가리키는 이름들의 규칙.

## 왜 platform이 아니라 여기인가

ticker 정규화와 CUSIP 검증은 "투자 데이터"를 알아야만 쓸 수 있는 규칙이다.
따라서 universe가 이 규칙의 주인이다.

## ticker는 identity가 아니다

회사는 이름을 바꾸고(FB→META), 거래소를 옮기고, 듀얼클래스로 갈린다. 더 나쁜 것은
**버려진 ticker가 재사용된다**는 점이다. 그래서 저장소의 identity는 `security_id`이고
ticker는 현재 표기일 뿐이다. 이 파일의 함수들은 "밖에서 온 이름을 우리 표기로
맞추는" 일만 한다 — 그것이 어느 종목인지 정하는 것은 저장소의 몫이다.
"""
from __future__ import annotations

import re

# 저장소가 강제하는 모양(db/postgres/v1/10_universe.sql의 CHECK와 같아야 한다).
TICKER_RE = re.compile(r"^[A-Z0-9-]{1,12}$")
CIK_RE = re.compile(r"^[0-9]{10}$")
CUSIP_RE = re.compile(r"^[A-Z0-9]{9}$")
FIGI_RE = re.compile(r"^[A-Z0-9]{12}$")

IDENTIFIER_TYPES = ("CUSIP", "CINS", "FIGI", "TICKER")


def normalize_ticker(value: object) -> str | None:
    """밖에서 온 종목 표기를 우리 표기로. 읽을 수 없으면 `None`.

    점을 하이픈으로 바꾸는 이유: 같은 종목을 SEC은 `BRK.B`, yfinance는 `BRK-B`로
    준다. 한쪽으로 모으지 않으면 같은 회사가 두 종목이 된다. 하이픈을 고른 것은
    저장소가 그 모양을 강제하기 때문이다.
    """
    text = str(value or "").strip().upper().replace(".", "-")
    return text if TICKER_RE.match(text) else None


def normalize_cik(value: object) -> str | None:
    """CIK를 10자리 0채움 문자열로. 읽을 수 없으면 `None`.

    SEC은 같은 회사를 `320193`, `0000320193`, `CIK0000320193`으로 준다. 숫자로
    저장하면 앞의 0이 사라져 다른 소스와 조인이 어긋나므로 문자열로 다룬다.
    """
    text = str(value or "").strip().upper()
    if text.startswith("CIK"):
        text = text[3:]
    text = text.lstrip("-")
    if not text.isdigit() or len(text) > 10:
        return None
    return text.zfill(10)


def _cusip_char_value(char: str) -> int:
    if char.isdigit():
        return int(char)
    if char.isalpha():
        return ord(char) - ord("A") + 10
    # CUSIP은 *, @, #도 쓴다(각각 36, 37, 38).
    return {"*": 36, "@": 37, "#": 38}[char]


def cusip_check_digit(body: str) -> str | None:
    """앞 8자리로 검사숫자를 계산한다. 계산할 수 없으면 `None`.

    13F 원문에는 자리가 밀리거나 문자가 빠진 CUSIP이 실제로 섞여 온다. 그것을 그대로
    매핑하면 아무 종목에도 안 붙는데, **에러는 나지 않아서** 그 보유 종목이 조용히
    사라진다. 검사숫자는 그 사고를 넣는 자리에서 잡는다.
    """
    if len(body) != 8:
        return None
    total = 0
    for index, char in enumerate(body):
        try:
            value = _cusip_char_value(char)
        except KeyError:
            return None
        if index % 2:  # 두 번째 자리부터 한 칸 걸러 2배
            value *= 2
        total += value // 10 + value % 10
    return str((10 - (total % 10)) % 10)


def normalize_cusip(value: object) -> str | None:
    """CUSIP을 9자리 표기로. 모양이나 검사숫자가 틀리면 `None`."""
    text = str(value or "").strip().upper()
    if not CUSIP_RE.match(text):
        return None
    expected = cusip_check_digit(text[:8])
    return text if expected is not None and text[8] == expected else None


def is_valid_identifier(identifier: str, identifier_type: str) -> bool:
    """저장소가 받아들일 모양인가. 넣기 전에 여기서 거른다."""
    if identifier_type in {"CUSIP", "CINS"}:
        return bool(CUSIP_RE.match(identifier))
    if identifier_type == "FIGI":
        return bool(FIGI_RE.match(identifier))
    if identifier_type == "TICKER":
        return bool(TICKER_RE.match(identifier))
    return False


__all__ = [
    "CIK_RE",
    "CUSIP_RE",
    "FIGI_RE",
    "IDENTIFIER_TYPES",
    "TICKER_RE",
    "cusip_check_digit",
    "is_valid_identifier",
    "normalize_cik",
    "normalize_cusip",
    "normalize_ticker",
]
