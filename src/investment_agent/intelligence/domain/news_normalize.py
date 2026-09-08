"""provider 응답을 저장 레코드로 바꾸고 중복 제거 키를 만든다.

## 왜 URL을 정규화하는가

같은 기사에 추적 파라미터만 다른 링크가 붙어 오면, 정규화 없이는 같은 기사가
여러 행이 된다. 중복 제거의 키는 사람이 보는 URL이 아니라 정규화된 URL이다.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from investment_agent.intelligence.domain.models import NewsArticleRecord
from investment_agent.platform.clock import ensure_aware
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

# 내용이 아니라 유입 경로를 나타내는 파라미터. 남겨두면 같은 기사가 여러 행이 된다.
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = frozenset({"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ncid"})


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_url(raw: object) -> str:
    """중복 제거에 쓸 URL 형태로 맞춘다."""
    text = str(raw or "").strip()
    if not text:
        return ""
    parts = urlsplit(text)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_KEYS
        and not key.lower().startswith(_TRACKING_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), "")
    )


def content_fingerprint(title: object, summary: object) -> str:
    """제목·요약으로 만드는 내용 지문.

    다른 provider가 같은 기사를 다른 URL로 줄 때 이 지문이 중복을 잡는다.
    """
    normalized = " ".join(f"{title or ''} {summary or ''}".split()).lower()
    return _sha(normalized)


def _published_at(payload: Mapping[str, Any]) -> datetime | None:
    """provider가 주는 발행 시각. 읽을 수 없으면 비운다 — 추측하지 않는다."""
    epoch = payload.get("providerPublishTime")
    if isinstance(epoch, (int, float)) and epoch > 0:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc)
    text = str(payload.get("published_at") or "").strip()
    if not text:
        return None
    try:
        return ensure_aware(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def to_record(
    payload: Mapping[str, Any],
    *,
    provider: str,
    now: datetime,
) -> NewsArticleRecord | None:
    """응답 한 건을 저장 레코드로 바꾼다. 식별할 수 없으면 `None`."""
    moment = ensure_aware(now)
    url = canonical_url(payload.get("link") or payload.get("url"))
    title = " ".join(str(payload.get("title") or "").split())
    if not url or not title:
        return None
    summary = " ".join(str(payload.get("summary") or "").split()) or None
    return NewsArticleRecord(
        article_id=_sha(f"{provider}|{url}"),
        provider=provider,
        source_name=str(payload.get("publisher") or "").strip() or None,
        canonical_url=url,
        url_hash=_sha(url),
        title=title,
        summary=summary,
        content_hash=content_fingerprint(title, summary),
        published_at=_published_at(payload),
        # provider가 명시적으로 주지 않으면 비운다. 수집 시각으로 채우면
        # coalesce(available_at, first_seen_at) 계약이 거짓이 된다.
        available_at=None,
        first_seen_at=moment,
        collected_at=moment,
    )


__all__ = ["canonical_url", "content_fingerprint", "to_record"]
