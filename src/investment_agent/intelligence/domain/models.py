"""Intelligence 저장 레코드.

수집 도메인(news·social)이 아니라 저장 경계가 이 모델을 소유한다. 저장 형태를
쓰는 쪽마다 따로 정의하면 컬럼 하나를 늘릴 때 두 곳을 고쳐야 하고, 한쪽만 고친
결과는 삽입 시점이 아니라 조회 시점에 드러난다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from investment_agent.platform.clock import ensure_aware


@dataclass
class NewsArticleRecord:
    """기사 한 건. `url_hash`와 `content_hash`가 중복 제거의 키다."""

    article_id: str
    provider: str
    source_name: str | None
    canonical_url: str
    url_hash: str
    title: str
    summary: str | None
    content_hash: str
    published_at: datetime | None
    available_at: datetime | None
    first_seen_at: datetime
    collected_at: datetime

    def __post_init__(self) -> None:
        self.first_seen_at = ensure_aware(self.first_seen_at)
        self.collected_at = ensure_aware(self.collected_at)
        if self.published_at is not None:
            self.published_at = ensure_aware(self.published_at)
        if self.available_at is not None:
            self.available_at = ensure_aware(self.available_at)


@dataclass
class SocialPostRecord:
    """게시물 한 건. 작성자는 해시로만 남긴다."""

    post_id: str
    platform: str
    channel: str
    native_id: str
    author_hash: str | None
    title: str | None
    body: str | None
    permalink: str | None
    score: int | None
    num_comments: int | None
    flair: str | None
    posted_at: datetime | None
    available_at: datetime | None
    first_seen_at: datetime
    collected_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        self.first_seen_at = ensure_aware(self.first_seen_at)
        self.collected_at = ensure_aware(self.collected_at)
        if self.posted_at is not None:
            self.posted_at = ensure_aware(self.posted_at)
        if self.available_at is not None:
            self.available_at = ensure_aware(self.available_at)


@dataclass
class EntityMention:
    """어떤 글이 어떤 종목을 언급했다는 사실.

    `match_kind`는 그 사실을 어떻게 알았는지를 남긴다 — 조회해서 받은 것과
    본문에서 찾아낸 것을 섞으면 언급량이 거짓이 된다.
    """

    mention_id: str
    source_kind: str
    source_id: str
    ticker: str
    match_kind: str
    confidence: float
    observed_at: datetime
    first_seen_at: datetime

    def __post_init__(self) -> None:
        self.observed_at = ensure_aware(self.observed_at)
        self.first_seen_at = ensure_aware(self.first_seen_at)


@dataclass
class CollectionRun:
    """수집·정리 실행 한 번."""

    run_id: str
    kind: str
    domain: str
    provider: str | None
    started_at: datetime
    finished_at: datetime | None = None
    status: str = "ok"
    stored_count: int = 0
    duplicate_count: int = 0
    unparsed_count: int = 0
    deleted_count: int = 0
    error_kind: str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        self.started_at = ensure_aware(self.started_at)
        if self.finished_at is not None:
            self.finished_at = ensure_aware(self.finished_at)


@dataclass
class StoreResult:
    """저장 시도의 결과. 중복은 실패가 아니라 정상이다."""

    stored: int = 0
    duplicates: int = 0


@dataclass
class PruneResult:
    """보존 정리로 지운 행 수."""

    news: int = 0
    social: int = 0
    mentions: int = 0

    @property
    def total(self) -> int:
        return self.news + self.social + self.mentions


__all__ = [
    "CollectionRun",
    "EntityMention",
    "NewsArticleRecord",
    "PruneResult",
    "SocialPostRecord",
    "StoreResult",
]
