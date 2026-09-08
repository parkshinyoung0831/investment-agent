"""서브레딧 스트림 수집 유스케이스.

## 왜 종목별 검색이 아닌가

Reddit은 새 글 스트림을 한 번 받으면 여러 종목이 함께 들어온다. 종목마다 검색하면
호출 수가 종목 수만큼 늘고, 관심종목 밖에서 벌어지는 일은 영영 못 본다.

## 언급이 없어도 게시물은 저장한다

추출 규칙은 앞으로 바뀐다. 그때 규칙만 다시 돌릴 수 있으려면 원문이 남아 있어야
한다. 언급이 없다고 버리면 규칙을 고쳐도 과거를 다시 못 본다.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Callable, Mapping, Sequence

from investment_agent.intelligence.domain.models import (
    CollectionRun,
    EntityMention,
    SocialPostRecord,
)
from investment_agent.intelligence.repository import IntelligenceRepository
from investment_agent.intelligence.application.retention import RETENTION_DAYS, is_within_retention
from investment_agent.intelligence.domain import extract
from investment_agent.intelligence.domain import social_normalize as normalize
from investment_agent.platform.clock import ensure_aware, utc_now
from investment_agent.intelligence.domain.contracts import (
    SocialCredentialsMissing,
    SocialQuotaExhausted,
)
from investment_agent.platform.logging import get_logger, log_fields

log = get_logger(__name__)

DOMAIN = "social"
PROVIDER = "reddit"

FetchPosts = Callable[[str], Sequence[Mapping[str, object]]]



def tracked_tickers() -> frozenset[str]:
    """언급으로 인정할 종목 집합. universe가 모르는 심볼은 언급이 아니다."""
    from investment_agent.data.universe.watchlists.db import active_members

    return frozenset(
        str(row["ticker"]).upper() for row in active_members() if row.get("ticker")
    )


def _mentions(record: SocialPostRecord, tracked: frozenset[str] | set[str]) -> list[EntityMention]:
    text = f"{record.title or ''}\n{record.body or ''}"
    observed = record.posted_at or record.first_seen_at
    mentions = []
    for match in extract.find_tickers(text, tracked=tracked):
        identity = f"social|{record.post_id}|{match.ticker}|{match.match_kind}"
        mentions.append(
            EntityMention(
                mention_id=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                source_kind="social",
                source_id=record.post_id,
                ticker=match.ticker,
                match_kind=match.match_kind,
                confidence=match.confidence,
                observed_at=observed,
                first_seen_at=record.first_seen_at,
            )
        )
    return mentions


def collect_social(
    *,
    repository: IntelligenceRepository,
    fetch: FetchPosts,
    channels: Sequence[str],
    tracked: frozenset[str] | set[str],
    now: datetime | None = None,
    retention_days: int = RETENTION_DAYS,
) -> CollectionRun:
    """서브레딧별 새 글을 가져와 저장하고 언급을 추출한다."""
    moment = ensure_aware(now or utc_now())
    run = CollectionRun(
        run_id=f"social-{uuid.uuid4().hex}",
        kind="collect",
        domain=DOMAIN,
        provider=PROVIDER,
        started_at=moment,
    )
    failures = 0
    missing_credentials = False
    capped = False

    for channel in channels:
        name = str(channel).strip()
        if not name:
            continue
        try:
            payloads = list(fetch(name))
        except SocialCredentialsMissing:
            missing_credentials = True
            break
        except SocialQuotaExhausted:
            # cap 소진은 provider 오류가 아니다 — 남은 채널을 마저 돌면 전부 같은
            # 이유로 재실패하며 예약을 반복 소모한다. 다음 실행에서 재개한다.
            capped = True
            break
        except Exception as error:
            failures += 1
            log.warning(
                "social fetch failed",
                extra=log_fields(channel=name, error_type=type(error).__name__),
            )
            continue

        records: list[SocialPostRecord] = []
        for payload in payloads:
            record = normalize.to_record(payload, channel=name, now=moment)
            if record is None:
                run.unparsed_count += 1
                continue
            observed = record.posted_at or record.first_seen_at
            if not is_within_retention(observed, now=moment, retention_days=retention_days):
                continue
            records.append(record)

        if not records:
            continue
        result = repository.store_social(records)
        run.stored_count += result.stored
        run.duplicate_count += result.duplicates
        mentions = [m for record in records for m in _mentions(record, tracked)]
        if mentions:
            repository.store_mentions(mentions)

    run.finished_at = ensure_aware(utc_now() if now is None else now)
    if missing_credentials:
        run.status = "skipped"
        run.error_kind = "no_credentials"
        run.message = "Reddit credentials are not configured"
    elif capped:
        run.status = "capped"
        run.error_kind = "quota_exhausted"
        run.message = "reddit daily cap reached; resuming next run"
    elif failures:
        run.status = "partial"
        run.error_kind = "provider_error"
        run.message = f"{failures} channel(s) failed"
    repository.record_run(run)
    log.info(
        "social collection finished",
        extra=log_fields(
            status=run.status, stored=run.stored_count, duplicates=run.duplicate_count
        ),
    )
    return run


__all__ = [
    "DOMAIN",
    "PROVIDER",
    "SocialCredentialsMissing",
    "SocialQuotaExhausted",
    "collect_social",
    "tracked_tickers",
]
