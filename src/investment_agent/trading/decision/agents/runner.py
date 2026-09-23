"""TradingAgents 역할 그래프에 LLM 런타임의 point-in-time 근거를 연결한다."""
from __future__ import annotations

import hashlib
import os
from datetime import timedelta
from typing import Any, Callable

from investment_agent.platform.logging import get_logger
from investment_agent.trading.contracts import parse_datetime
from investment_agent.research.adapters.trading import EvidenceBundle
from investment_agent.trading.decision.agents import orchestrator
from investment_agent.trading.decision.llm import runtime
from investment_agent.trading.decision.llm.client import OpenAICompatibleClient
from investment_agent.trading.decision.llm.news_source import validate_news_vendor_config
from investment_agent.trading.decision.llm.social_source import (
    fetch_finnhub_sentiment,
    fetch_reddit_posts,
    fetch_stocktwits_messages as _social_fetch_stocktwits,
)
from investment_agent.trading.decision.llm.vendor.alpha_vantage_news import (
    get_news as _get_news_alpha_vantage,
)
from investment_agent.trading.decision.llm.vendor.reddit import (
    fetch_reddit_posts as _vendor_fetch_reddit,
)
from investment_agent.trading.decision.llm.vendor.stocktwits import (
    fetch_stocktwits_messages as _vendor_fetch_stocktwits,
)
from investment_agent.trading.decision.llm.vendor.yfinance_news import get_news_yfinance


log = get_logger(__name__)
NEWS_LOOKBACK_DAYS = 7
# 외부(뉴스·소셜) 원문은 기본적으로 실행 메모리에서만 쓴다(`runtime._persist_external_raw`와 같은 규칙).
_EXTERNAL_ANALYST_DOMAINS = frozenset({"news", "sentiment"})


def _recorded(sink: dict[str, dict[str, Any]], domain: str, fetch: Callable[[], str]) -> Callable[[], str]:
    """분석가가 실제로 받은 입력을 남긴다 — 분석가 단계를 같은 입력으로 다시 돌려 비교하려면 필요하다.

    내부 근거는 원문을, 외부 원문은 보존 설정이 켜졌을 때만 원문을 남기고 평소에는 해시와 길이만 남긴다.
    """
    def run() -> str:
        text = fetch()
        record: dict[str, Any] = {
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "chars": len(text),
        }
        if domain not in _EXTERNAL_ANALYST_DOMAINS or os.environ.get(
            "AI_INVESTOR_SAVE_EXTERNAL_RAW", "false"
        ).lower() == "true":
            record["text"] = text
        sink[domain] = record
        return text

    return run


class TradingAgentsRunner:
    """분석가 5명 → Bull/Bear 토론 → Trader → Risk 3자 토론 → Portfolio Manager를 로컬로 실행한다."""

    # engine의 구조화 호출(strict json_schema)까지 판단 결과를 바꾸는 변경이면 이 값을 올린다 — 판단 기록의 engine_version이다.
    version = "0.8.1-local-graph-shared-macro-h20-news7d-strict"

    def __init__(self) -> None:
        # 한 분석 회차(이 runner의 수명) 안에서 같은 거시 근거의 요약을 공유한다. 회차가 끝나면 사라진다.
        self._macro_reports: dict[str, str] = {}

    def run(self, bundle: EvidenceBundle, *, memory_text: str) -> dict[str, Any]:
        manifests_token = runtime._EXTERNAL_MANIFESTS.set([])
        cache_token = runtime._EXTERNAL_CACHE.set({})
        call_count_token = runtime._EXTERNAL_CALL_COUNT.set(0)
        bundle_token = runtime._ACTIVE_BUNDLE.set(bundle)
        try:
            runtime._external_call_limit()
            # 재생성 가능한 로컬 캐시는 live 근거를 사용할 수 있는 실행에서만 연다.
            # historical replay는 캐시 조회뿐 아니라 파일 접근 자체도 하지 않는다.
            if (
                runtime._external_block_reason(bundle) is None
                and os.environ.get("AI_INVESTOR_LOCAL_NEWS_CACHE_ENABLED", "true").lower()
                == "true"
            ):
                try:
                    runtime.LocalEvidenceCache().cleanup()
                except (runtime.LocalEvidenceCacheError, OSError, RuntimeError) as exc:
                    log.warning("local news/social retention cleanup failed: %s", exc)

            requested_vendor = validate_news_vendor_config(
                os.environ.get("AI_INVESTOR_TRADINGAGENTS_NEWS_VENDOR", "yfinance")
            )
            client = OpenAICompatibleClient.from_env()
            point = parse_datetime(bundle.as_of_at)
            curr_date = point.date().isoformat()
            news_start = (point - timedelta(days=NEWS_LOOKBACK_DAYS)).date().isoformat()

            news_fetchers = {"yfinance": get_news_yfinance, "alpha_vantage": _get_news_alpha_vantage}

            def fetch_news_evidence() -> str:
                return runtime.fetch_external_news(
                    bundle.ticker, news_start, curr_date,
                    requested_vendor=requested_vendor, get_bundle=runtime._bundle,
                    external_fetch=runtime._external_fetch, record_external=runtime._record_external,
                    upstream_fetcher=news_fetchers.get(requested_vendor),
                )

            def fetch_sentiment_evidence() -> str:
                return "\n\n".join((
                    _social_fetch_stocktwits(
                        bundle.ticker, external_fetch=runtime._external_fetch,
                        record_external=runtime._record_external,
                        upstream_fetcher=_vendor_fetch_stocktwits,
                    ),
                    fetch_reddit_posts(
                        bundle.ticker, external_fetch=runtime._external_fetch,
                        record_external=runtime._record_external,
                        upstream_fetcher=_vendor_fetch_reddit,
                    ),
                    fetch_finnhub_sentiment(
                        bundle.ticker, external_fetch=runtime._external_fetch,
                        record_external=runtime._record_external,
                    ),
                ))

            analyst_inputs: dict[str, dict[str, Any]] = {}
            result = orchestrator.run_local_graph(
                client,
                ticker=bundle.ticker,
                curr_date=curr_date,
                fetch_market_evidence=_recorded(analyst_inputs, "market", lambda: runtime._verified_market(bundle.ticker, curr_date)),
                fetch_fundamentals_evidence=_recorded(analyst_inputs, "fundamentals", lambda: runtime._fundamentals(bundle.ticker, curr_date)),
                fetch_news_evidence=_recorded(analyst_inputs, "news", fetch_news_evidence),
                fetch_sentiment_evidence=_recorded(analyst_inputs, "sentiment", fetch_sentiment_evidence),
                fetch_macro_evidence=_recorded(analyst_inputs, "macro", lambda: runtime._macro("", curr_date)),
                macro_report_cache=self._macro_reports,
            )
            manifests = runtime._deduplicate_external_manifests(runtime._EXTERNAL_MANIFESTS.get())
            # 역할 호출은 이 client로 나간다. 사용량을 넘기지 않으면 종목당 비용이 구조화 호출 1건만 남는다.
            return {**result, "_external_evidence_manifest": manifests, "_analyst_inputs": analyst_inputs,
                    "_role_usage": client.usage}
        except Exception as exc:
            manifests = runtime._deduplicate_external_manifests(runtime._EXTERNAL_MANIFESTS.get())
            raise runtime.TradingAgentsRunError(
                f"{type(exc).__name__}: {exc}", external_evidence=manifests,
            ) from exc
        finally:
            runtime._EXTERNAL_CALL_COUNT.reset(call_count_token)
            runtime._EXTERNAL_MANIFESTS.reset(manifests_token)
            runtime._EXTERNAL_CACHE.reset(cache_token)
            runtime._ACTIVE_BUNDLE.reset(bundle_token)
