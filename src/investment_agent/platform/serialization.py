"""JSON 직렬화·해싱·URL 정규화.

## 왜 표준 json으로 부족한가

`json.dumps`는 `Decimal`과 `date`를 못 찍는다. 부르는 쪽마다 `default=str`을 다르게
붙이면 같은 값이 자리에 따라 다른 문자열이 되고, 그 문자열로 해시를 만들면 **같은
내용이 다른 지문**을 갖는다. 재현성이 필요한 자리(판단 근거 digest, 중복 판정)에서
그것은 조용한 오류다.

`Decimal`을 float으로 바꾸지 않고 문자열로 두는 것도 같은 이유다 — 돈과 비율을
float으로 왕복시키면 마지막 자리가 달라진다.

## 이 파일에 없는 것

ticker 정규화, SEC accession 형식, 재무 단위 규칙은 여기 없다. 그것은 도메인
지식이고, platform에 두면 도메인을 고칠 때 무관한 모듈이 함께 흔들린다.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class ContractError(ValueError):
    """값이 계약을 어겼다. 부르는 쪽이 고쳐야 하는 오류다."""


def parse_datetime(value: str | datetime) -> datetime:
    """ISO 문자열을 UTC datetime으로. tz가 없으면 **거부한다**."""
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )
    if parsed.tzinfo is None:
        raise ContractError("datetime must include a timezone")
    return parsed.astimezone(timezone.utc)


def json_value(value: Any) -> Any:
    """JSON에 실을 수 있는 모양으로 바꾼다. 손실이 생기는 변환은 하지 않는다."""
    if isinstance(value, Decimal):
        # float으로 바꾸면 마지막 자리가 흔들린다. 문자열이 정확하다.
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [json_value(item) for item in value]
        # 집합에는 순서가 없다. 정렬하지 않으면 같은 내용이 매번 다른 지문을 갖는다.
        return sorted(items, key=repr) if isinstance(value, (set, frozenset)) else items
    if isinstance(value, float) and not math.isfinite(value):
        # NaN/Infinity는 표준 JSON이 아니다. 받는 쪽 파서가 조용히 다르게 읽는다.
        return None
    return value


def canonical_json(value: Any) -> str:
    """같은 내용이면 항상 같은 문자열. 해시와 중복 판정의 기준이다."""
    return json.dumps(json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_id(prefix: str, value: Mapping[str, Any]) -> str:
    """내용 기반의 결정론적 식별자를 만든다."""
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def content_hash(value: Any) -> str:
    """내용 지문(sha256 hex). 근거 번들이 바뀌었는지 판정하는 유일한 기준."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


_TRACKING_KEYS = frozenset({"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "source"})


def canonicalize_url(value: str | None) -> str | None:
    """같은 문서를 가리키는 URL을 한 모양으로. 읽을 수 없으면 `None`.

    같은 기사에 tracking 파라미터만 달라진 URL이 붙어 오는데, 그대로 두면 중복
    판정이 전부 빗나가 같은 뉴스를 여러 번 근거로 센다.
    """
    raw = str(value or "").strip().rstrip(".,;")
    if not raw:
        return None
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        return None
    netloc = parsed.hostname.lower()
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{netloc}:{port}"
    query = urlencode(sorted(
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_KEYS
    ))
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, query, ""))


def finite_float(value: Any, default: float | None = None) -> float | None:
    """유한한 float만. NaN·Infinity·bool·읽을 수 없는 값은 `default`.

    bool을 막는 이유: 파이썬에서 `float(True)`는 1.0이라, 플래그 컬럼이 지표 값으로
    조용히 섞여 들어간다.
    """
    if isinstance(value, bool) or value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def normalize_ticker(value: object) -> str:
    """종목 심볼을 대문자 및 표준 dash 형태로 정규화한다."""
    return str(value or "").strip().upper().replace(".", "-")


__all__ = [
    "ContractError",
    "canonical_json",
    "canonicalize_url",
    "content_hash",
    "finite_float",
    "json_value",
    "normalize_ticker",
    "parse_datetime",
    "stable_id",
]
