"""Reddit 응답을 저장 레코드로 바꾼다.

## 작성자는 해시로만 남긴다

필요한 것은 "같은 사람이 반복 게시하나"뿐이고 그것은 해시로 된다. 공개 계정명이라도
90일 들고 있으면 얻는 것 없이 개인정보 보관 책임만 생긴다.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Mapping

from investment_agent.intelligence.domain.models import SocialPostRecord
from investment_agent.platform.clock import ensure_aware
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

PLATFORM = "reddit"

# 삭제·비공개 작성자. 해시를 만들면 이 값들이 한 사람인 것처럼 묶인다.
_ABSENT_AUTHORS = frozenset({"", "[deleted]", "[removed]", "automoderator"})


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def author_hash(raw: object) -> str | None:
    """작성자 식별용 해시. 지워진 계정은 비운다."""
    name = str(raw or "").strip()
    if name.lower() in _ABSENT_AUTHORS:
        return None
    return _sha(f"{PLATFORM}|{name.lower()}")


def _posted_at(payload: Mapping[str, Any]) -> datetime | None:
    created = payload.get("created_utc")
    if isinstance(created, (int, float)) and created > 0:
        return datetime.fromtimestamp(float(created), tz=timezone.utc)
    return None


def to_record(
    payload: Mapping[str, Any],
    *,
    channel: str,
    now: datetime,
) -> SocialPostRecord | None:
    """게시물 한 건을 저장 레코드로 바꾼다. 식별할 수 없으면 `None`."""
    moment = ensure_aware(now)
    native_id = str(payload.get("id") or "").strip()
    if not native_id:
        return None
    title = " ".join(str(payload.get("title") or "").split()) or None
    body = str(payload.get("selftext") or "").strip() or None
    permalink = str(payload.get("permalink") or "").strip() or None
    return SocialPostRecord(
        post_id=_sha(f"{PLATFORM}|{native_id}"),
        platform=PLATFORM,
        channel=str(channel),
        native_id=native_id,
        author_hash=author_hash(payload.get("author")),
        title=title,
        body=body,
        permalink=f"https://www.reddit.com{permalink}" if permalink else None,
        score=int(payload["score"]) if isinstance(payload.get("score"), (int, float)) else None,
        num_comments=(
            int(payload["num_comments"])
            if isinstance(payload.get("num_comments"), (int, float))
            else None
        ),
        flair=str(payload.get("link_flair_text") or "").strip() or None,
        posted_at=_posted_at(payload),
        available_at=None,
        first_seen_at=moment,
        collected_at=moment,
        content_hash=_sha(" ".join(f"{title or ''} {body or ''}".split()).lower()),
    )


__all__ = ["PLATFORM", "author_hash", "to_record"]
