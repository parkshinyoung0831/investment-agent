"""뉴스·소셜 원문을 사건과 작은 feature로 압축하는 순수 모듈."""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping, Sequence

from investment_agent.platform.serialization import canonical_json, canonicalize_url, parse_datetime
from investment_agent.trading.decision.contracts import Event, EventFeatureSnapshot

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{2,}")
_POSITIVE_WORDS = frozenset({
    "beat", "beats", "growth", "strong", "raised", "upgrade", "approved", "record",
    "profit", "contract", "launch", "buyback", "bullish", "surge", "positive",
})
_NEGATIVE_WORDS = frozenset({
    "miss", "misses", "decline", "weak", "cut", "downgrade", "lawsuit", "recall",
    "loss", "dilution", "offering", "bearish", "plunge", "negative", "warning",
})
_EVENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("earnings", ("earnings", "quarter", "eps", "revenue")),
    ("guidance", ("guidance", "outlook", "forecast")),
    ("regulation", ("regulator", "regulation", "sec", "ftc", "approval")),
    ("litigation", ("lawsuit", "litigation", "court", "settlement")),
    ("management", ("ceo", "cfo", "resigns", "appointed", "management")),
    ("insider_buy", ("insider bought", "insider buy", "director purchase")),
    ("insider_sell", ("insider sold", "insider sell", "director sale")),
    ("beneficial_ownership", ("13d", "13g", "beneficial ownership")),
    ("activist_entry", ("activist", "stake", "campaign")),
    ("dilution", ("dilution", "convertible", "shares issued")),
    ("offering", ("offering", "secondary shares", "capital raise")),
    ("contract", ("contract", "agreement", "partnership", "order")),
    ("product", ("product", "launch", "release", "chip", "drug")),
    ("analyst_revision", ("analyst", "price target", "estimate revision", "rating")),
)


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8", errors="replace")).hexdigest()


def _clean_text(value: Any) -> str:
    text = "".join(char for char in str(value or "") if char in "\n\t" or ord(char) >= 32)
    return " ".join(text.split()).strip()


def _tokens(value: str) -> set[str]:
    return set(_TOKEN_RE.findall(value.lower()))


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _simple_sentiment(text: str) -> float:
    tokens = _tokens(text)
    positive = len(tokens & _POSITIVE_WORDS)
    negative = len(tokens & _NEGATIVE_WORDS)
    total = positive + negative
    if total == 0:
        return 0.0
    return max(-1.0, min(1.0, (positive - negative) / total))


@dataclass(frozen=True)
class RawContent:
    """provider adapter가 넘기는 원문 최소 입력이다."""

    provider: str
    content_type: str
    ticker: str | None
    fetched_at: str
    content: str
    published_at: str | None = None
    url: str | None = None
    title: str | None = None
    author: str | None = None
    source: str | None = None
    sentiment: float | None = None
    item_id: str | None = None


@dataclass(frozen=True)
class NormalizedContent:
    """URL·본문·시각을 표준화한 원문 reference다."""

    item_id: str
    provider: str
    content_type: str
    ticker: str | None
    published_at: str
    fetched_at: str
    canonical_url: str | None
    content_hash: str
    title: str
    content: str
    author: str | None = None
    source: str | None = None
    sentiment: float = 0.0


def _raw_value(raw: RawContent | Mapping[str, Any], *names: str) -> Any:
    if isinstance(raw, RawContent):
        for name in names:
            if hasattr(raw, name):
                value = getattr(raw, name)
                if value is not None:
                    return value
        return None
    for name in names:
        if raw.get(name) is not None:
            return raw[name]
    return None


def normalize_content(raw: RawContent | Mapping[str, Any]) -> NormalizedContent:
    """provider별 필드를 canonical URL·content hash 기준으로 통일한다."""
    provider = _clean_text(_raw_value(raw, "provider"))
    content_type = _clean_text(_raw_value(raw, "content_type", "type")).lower()
    if not provider or content_type not in {"news", "social"}:
        raise ValueError("content requires provider and content_type news/social")
    ticker_value = _raw_value(raw, "ticker", "symbol")
    ticker = str(ticker_value).upper().strip() if ticker_value else None
    fetched_raw = _raw_value(raw, "fetched_at", "collected_at", "first_seen_at")
    if fetched_raw is None:
        raise ValueError("content fetched_at is required")
    fetched_at = parse_datetime(str(fetched_raw)).isoformat()
    published_raw = _raw_value(raw, "published_at", "occurred_at")
    published_at = parse_datetime(str(published_raw or fetched_at)).isoformat()
    if published_at > fetched_at:
        raise ValueError("content published_at cannot be after fetched_at")
    title = _clean_text(_raw_value(raw, "title", "headline"))
    content = _clean_text(_raw_value(raw, "content", "text", "description", "raw"))
    if not content:
        raise ValueError("content body is required")
    canonical_url = canonicalize_url(str(_raw_value(raw, "canonical_url", "url") or "")) or None
    content_hash = _sha({"title": title, "content": content})
    supplied_id = _clean_text(_raw_value(raw, "item_id"))
    item_id = supplied_id or f"content_{content_hash[:24]}"
    sentiment_raw = _raw_value(raw, "sentiment")
    sentiment = _simple_sentiment(f"{title} {content}") if sentiment_raw is None else float(sentiment_raw)
    if not math.isfinite(sentiment) or not -1.0 <= sentiment <= 1.0:
        raise ValueError("content sentiment must be finite and between -1 and 1")
    return NormalizedContent(
        item_id=item_id,
        provider=provider,
        content_type=content_type,
        ticker=ticker,
        published_at=published_at,
        fetched_at=fetched_at,
        canonical_url=canonical_url,
        content_hash=content_hash,
        title=title,
        content=content,
        author=_clean_text(_raw_value(raw, "author")) or None,
        source=_clean_text(_raw_value(raw, "source")) or None,
        sentiment=sentiment,
    )


def normalize_contents(records: Sequence[RawContent | Mapping[str, Any]]) -> tuple[NormalizedContent, ...]:
    """동일 URL 또는 동일 본문은 한 번만 사건 입력으로 남긴다."""
    unique: list[NormalizedContent] = []
    seen_urls: set[str] = set()
    seen_hashes: set[str] = set()
    for record in records:
        item = normalize_content(record)
        if (item.canonical_url and item.canonical_url in seen_urls) or item.content_hash in seen_hashes:
            continue
        unique.append(item)
        if item.canonical_url:
            seen_urls.add(item.canonical_url)
        seen_hashes.add(item.content_hash)
    return tuple(sorted(unique, key=lambda item: (item.published_at, item.item_id)))


def _event_type(item: NormalizedContent) -> str:
    text = f"{item.title} {item.content}".lower()
    for event_type, keywords in _EVENT_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return event_type
    if item.content_type == "social":
        return "social_spike"
    return "general_news"


def _direction(items: Sequence[NormalizedContent]) -> float:
    values = [item.sentiment for item in items]
    return max(-1.0, min(1.0, sum(values) / len(values))) if values else 0.0


def cluster_contents(
    records: Sequence[NormalizedContent],
    *,
    similarity_threshold: float = 0.32,
    max_gap_days: int = 7,
) -> tuple[tuple[NormalizedContent, ...], ...]:
    """겹치는 핵심어와 사건 유형으로 여러 기사를 하나의 사건 cluster로 묶는다."""
    if not 0.0 < similarity_threshold <= 1.0:
        raise ValueError("similarity_threshold must be in (0, 1]")
    if max_gap_days < 0:
        raise ValueError("max_gap_days must be non-negative")
    clusters: list[list[NormalizedContent]] = []
    signatures: list[set[str]] = []
    for item in sorted(records, key=lambda value: (value.published_at, value.item_id)):
        item_tokens = _tokens(f"{item.title} {item.content}")
        item_type = _event_type(item)
        item_time = parse_datetime(item.published_at)
        selected: list[int] = []
        for index, cluster in enumerate(clusters):
            representative = cluster[0]
            if representative.ticker != item.ticker or _event_type(representative) != item_type:
                continue
            representative_time = parse_datetime(representative.published_at)
            if abs((item_time - representative_time).total_seconds()) > max_gap_days * 86400:
                continue
            if _jaccard(item_tokens, signatures[index]) >= similarity_threshold:
                selected.append(index)
                break
        if selected:
            index = selected[0]
            clusters[index].append(item)
            signatures[index] |= item_tokens
        else:
            clusters.append([item])
            signatures.append(set(item_tokens))
    return tuple(tuple(cluster) for cluster in clusters)


def extract_events(
    records: Sequence[RawContent | Mapping[str, Any] | NormalizedContent],
    *,
    as_of_at: str,
    similarity_threshold: float = 0.32,
) -> tuple[Event, ...]:
    """cutoff 이후에 수집된 원문을 배제하고 cluster별 구조화 사건을 만든다."""
    as_of = parse_datetime(as_of_at)
    normalized = tuple(
        item if isinstance(item, NormalizedContent) else normalize_content(item)
        for item in records
    )
    available = tuple(
        item for item in normalized
        if parse_datetime(item.fetched_at) <= as_of
        and parse_datetime(item.published_at) <= as_of
    )
    events: list[Event] = []
    for cluster in cluster_contents(available, similarity_threshold=similarity_threshold):
        representative = cluster[0]
        occurred_at = min(item.published_at for item in cluster)
        available_at = max(item.fetched_at for item in cluster)
        first_seen_at = min(item.fetched_at for item in cluster)
        source_count = len(cluster)
        providers = {item.provider for item in cluster}
        source_diversity = len(providers) / source_count
        text = " ".join(f"{item.title} {item.content}" for item in cluster).lower()
        importance = min(
            1.0,
            0.35
            + 0.10 * min(4, source_count - 1)
            + 0.15 * sum(keyword in text for keyword in (
                "earnings", "guidance", "regulator", "lawsuit", "offering", "contract",
            )),
        )
        sentiment = _direction(cluster)
        novelty = min(1.0, 1.0 / max(1.0, source_count / max(1, len(providers))))
        controversy = min(1.0, max(0.0, 1.0 - abs(sentiment)) * (0.5 + 0.5 * source_diversity))
        identity = {
            "ticker": representative.ticker,
            "event_type": _event_type(representative),
            "occurred_at": occurred_at,
            "evidence_ids": sorted(item.item_id for item in cluster),
        }
        events.append(Event(
            event_id=f"event_{_sha(identity)[:24]}",
            ticker=representative.ticker,
            event_type=_event_type(representative),
            occurred_at=occurred_at,
            available_at=available_at,
            first_seen_at=first_seen_at,
            importance=importance,
            direction=sentiment,
            confidence=min(1.0, 0.45 + 0.10 * len(providers) + 0.05 * min(source_count, 5)),
            novelty=novelty,
            controversy=controversy,
            source_count=source_count,
            source_diversity=source_diversity,
            sentiment=sentiment,
            evidence_ids=tuple(sorted(item.item_id for item in cluster)),
            metadata={
                "providers": sorted(providers),
                "content_types": sorted({item.content_type for item in cluster}),
                "social_is_supplementary": any(item.content_type == "social" for item in cluster),
            },
        ))
    return tuple(sorted(events, key=lambda event: (event.occurred_at, event.event_id)))


def summarize_event_features(
    events: Sequence[Event],
    *,
    ticker: str,
    as_of_at: str,
    feature_version: str = "event-intelligence-v1",
    window_days: int = 7,
) -> EventFeatureSnapshot:
    """원문을 저장하지 않고 사건 수·속도·심리만 학습용 snapshot으로 보존한다."""
    if window_days < 1 or window_days > 90:
        raise ValueError("window_days must be between 1 and 90")
    as_of = parse_datetime(as_of_at)
    normalized_ticker = str(ticker).upper().strip()
    selected = tuple(
        event for event in events
        if event.ticker == normalized_ticker and parse_datetime(event.available_at) <= as_of
        and as_of - parse_datetime(event.occurred_at) <= timedelta(days=window_days)
    )
    news = tuple(event for event in selected if event.metadata.get("social_is_supplementary") is not True)
    social = tuple(event for event in selected if event.metadata.get("social_is_supplementary") is True)
    all_sources = {source for event in selected for source in event.metadata.get("providers", ())}
    source_diversity = (
        sum(event.source_diversity for event in selected) / len(selected) if selected else 0.0
    )
    available_at = max((event.available_at for event in selected), default=as_of.isoformat())
    return EventFeatureSnapshot(
        ticker=normalized_ticker,
        as_of_at=as_of.isoformat(),
        available_at=available_at,
        news_sentiment=(sum(event.sentiment for event in news) / len(news) if news else 0.0),
        social_sentiment=(sum(event.sentiment for event in social) / len(social) if social else 0.0),
        news_velocity=len(news) / window_days,
        social_velocity=len(social) / window_days,
        mention_velocity=len(selected) / window_days,
        novelty=(sum(event.novelty for event in selected) / len(selected) if selected else 0.0),
        controversy=(sum(event.controversy for event in selected) / len(selected) if selected else 0.0),
        source_diversity=max(source_diversity, min(1.0, len(all_sources) / max(1, len(selected)))),
        event_count=len(selected),
        high_impact_event_count=sum(event.importance >= 0.75 for event in selected),
        event_importance=(sum(event.importance for event in selected) / len(selected) if selected else 0.0),
        source_ids=tuple(sorted(event.event_id for event in selected)),
        provenance={
            "window_days": window_days,
            "event_count": len(selected),
            "raw_content_persisted": False,
            "social_is_supplementary": True,
        },
        feature_version=feature_version,
    )


__all__ = [
    "NormalizedContent",
    "RawContent",
    "cluster_contents",
    "extract_events",
    "normalize_content",
    "normalize_contents",
    "summarize_event_features",
]
