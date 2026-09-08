"""Reddit 새 글 스트림 어댑터.

자격증명이 없으면 별도 스위치 없이 건너뛴다 — 자격증명 유무가 곧 스위치다.
스위치를 따로 두면 어긋날 수 있는 두 번째 진실이 생긴다.
"""
from __future__ import annotations

import os
from typing import Any

from investment_agent.intelligence.domain.contracts import (
    SocialCredentialsMissing,
    SocialQuotaExhausted,
)
from investment_agent.platform.external_usage import (
    default_ledger_path,
    provider_daily_cap,
    reserve_provider_call,
)
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

PROVIDER = "reddit"
CLIENT_ID_ENV = "REDDIT_CLIENT_ID"
CLIENT_SECRET_ENV = "REDDIT_CLIENT_SECRET"
USER_AGENT_ENV = "REDDIT_USER_AGENT"


def credentials_available() -> bool:
    """세 값이 모두 있어야 켜진 것으로 본다."""
    return all(
        os.environ.get(name, "").strip()
        for name in (CLIENT_ID_ENV, CLIENT_SECRET_ENV, USER_AGENT_ENV)
    )


def fetch_new_posts(channel: str, *, limit: int = 100) -> list[dict[str, Any]]:
    """서브레딧 하나의 새 글을 가져온다. 한 번 호출로 여러 종목이 함께 들어온다."""
    if not credentials_available():
        raise SocialCredentialsMissing(
            f"set {CLIENT_ID_ENV}, {CLIENT_SECRET_ENV} and {USER_AGENT_ENV}"
        )
    reservation = reserve_provider_call(
        default_ledger_path(),
        provider=PROVIDER,
        cap=provider_daily_cap(PROVIDER),
    )
    if not reservation.allowed:
        raise SocialQuotaExhausted(f"{PROVIDER} daily cap reached ({reservation.cap})")

    import praw

    client = praw.Reddit(
        client_id=os.environ[CLIENT_ID_ENV],
        client_secret=os.environ[CLIENT_SECRET_ENV],
        user_agent=os.environ[USER_AGENT_ENV],
    )
    return [
        {
            "id": post.id,
            "author": str(post.author) if post.author else "",
            "title": post.title,
            "selftext": post.selftext,
            "permalink": post.permalink,
            "score": post.score,
            "num_comments": post.num_comments,
            "link_flair_text": post.link_flair_text,
            "created_utc": post.created_utc,
        }
        for post in client.subreddit(str(channel)).new(limit=int(limit))
    ]


__all__ = [
    "CLIENT_ID_ENV",
    "CLIENT_SECRET_ENV",
    "PROVIDER",
    "SocialQuotaExhausted",
    "USER_AGENT_ENV",
    "credentials_available",
    "fetch_new_posts",
]
