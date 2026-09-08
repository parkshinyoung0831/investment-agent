"""관심종목 뉴스 수집 유스케이스.

## fetch를 주입받는다

provider 호출을 이 모듈이 직접 하면 테스트가 네트워크를 타야 한다. 무엇을 가져올지는
`sources/`가 알고, 언제 어떻게 저장할지는 여기가 안다.

## 한 종목의 실패가 나머지를 멈추지 않는다

provider는 종목 하나에서 자주 실패한다. 거기서 배치를 멈추면 그날 수집이 통째로
빈다. 실패는 세어서 실행 기록에 남기고 나머지를 계속한다.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Callable, Mapping, Sequence

from investment_agent.intelligence.domain.models import (
    CollectionRun,
    EntityMention,
    NewsArticleRecord,
)
from investment_agent.intelligence.repository import IntelligenceRepository
from investment_agent.intelligence.application.retention import RETENTION_DAYS, is_within_retention
from investment_agent.intelligence.domain import news_normalize as normalize
from investment_agent.intelligence.infrastructure.sources.news.yfinance import NewsQuotaExhausted
from investment_agent.platform.clock import ensure_aware, utc_now
from investment_agent.platform.logging import get_logger, log_fields

log = get_logger(__name__)

PROVIDER = "yfinance"
DOMAIN = "news"

FetchNews = Callable[[str], Sequence[Mapping[str, object]]]


def watchlist_tickers() -> list[str]:
    """수집 대상 종목. universe가 tracked 종목의 단일 기준이다.

    CLI와 하네스 잡이 같은 함수를 쓰도록 여기 둔다 — 각자 자기 목록을 만들면
    두 경로가 서로 다른 종목을 수집하게 된다.
    """
    from investment_agent.data.universe.watchlists.db import active_members

    return [str(row["ticker"]).upper() for row in active_members() if row.get("ticker")]


def _mention(record: NewsArticleRecord, ticker: str) -> EntityMention:
    """조회해서 받은 기사의 언급. 등급은 결정론적이다."""
    identity = f"news|{record.article_id}|{ticker}|queried"
    return EntityMention(
        mention_id=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        source_kind="news",
        source_id=record.article_id,
        ticker=ticker,
        match_kind="queried",
        confidence=1.0,
        observed_at=record.published_at or record.first_seen_at,
        first_seen_at=record.first_seen_at,
    )


def collect_news(
    *,
    repository: IntelligenceRepository,
    fetch: FetchNews,
    tickers: Sequence[str],
    now: datetime | None = None,
    retention_days: int = RETENTION_DAYS,
) -> CollectionRun:
    """관심종목별로 뉴스를 가져와 저장하고 실행 기록을 남긴다."""
    moment = ensure_aware(now or utc_now())
    run = CollectionRun(
        run_id=f"news-{uuid.uuid4().hex}",
        kind="collect",
        domain=DOMAIN,
        provider=PROVIDER,
        started_at=moment,
    )
    failures = 0
    capped = False
    for ticker in tickers:
        symbol = str(ticker).strip().upper()
        if not symbol:
            continue
        try:
            payloads = list(fetch(symbol))
        except NewsQuotaExhausted:
            # cap 소진은 provider 오류가 아니다 — 남은 종목을 마저 돌면 전부 같은
            # 이유로 재실패하며 예약을 반복 소모한다. 다음 실행에서 재개한다.
            capped = True
            break
        except Exception as error:  # provider는 종목 하나에서 자주 실패한다
            failures += 1
            log.warning(
                "news fetch failed",
                extra=log_fields(ticker=symbol, error_type=type(error).__name__),
            )
            continue

        records: list[NewsArticleRecord] = []
        for payload in payloads:
            record = normalize.to_record(payload, provider=PROVIDER, now=moment)
            if record is None:
                run.unparsed_count += 1
                continue
            observed = record.published_at or record.first_seen_at
            if not is_within_retention(observed, now=moment, retention_days=retention_days):
                continue
            records.append(record)

        if not records:
            continue
        result = repository.store_news(records)
        run.stored_count += result.stored
        run.duplicate_count += result.duplicates
        repository.store_mentions([_mention(record, symbol) for record in records])

    run.finished_at = ensure_aware(utc_now() if now is None else now)
    if capped:
        run.status = "capped"
        run.error_kind = "quota_exhausted"
        run.message = "yfinance daily cap reached; resuming next run"
    elif failures:
        run.status = "partial"
        run.error_kind = "provider_error"
        run.message = f"{failures} ticker(s) failed"
    repository.record_run(run)
    log.info(
        "news collection finished",
        extra=log_fields(
            stored=run.stored_count,
            duplicates=run.duplicate_count,
            unparsed=run.unparsed_count,
            failures=failures,
        ),
    )
    return run


__all__ = ["DOMAIN", "PROVIDER", "collect_news", "watchlist_tickers"]
