"""TradingAgents 역할 그래프에 LLM 런타임의 point-in-time 근거를 연결한다."""
from __future__ import annotations

import os
from typing import Any

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


class TradingAgentsRunner:
    """분석가 5명 → Bull/Bear 토론 → Trader → Risk 3자 토론 → Portfolio Manager를 로컬로 실행한다."""

    version = "0.7.0-local-graph-macro-h20"

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
            curr_date = parse_datetime(bundle.as_of_at).date().isoformat()

            news_fetchers = {"yfinance": get_news_yfinance, "alpha_vantage": _get_news_alpha_vantage}

            def fetch_news_evidence() -> str:
                return runtime.fetch_external_news(
                    bundle.ticker, curr_date, curr_date,
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

            result = orchestrator.run_local_graph(
                client,
                ticker=bundle.ticker,
                curr_date=curr_date,
                fetch_market_evidence=lambda: runtime._verified_market(bundle.ticker, curr_date),
                fetch_fundamentals_evidence=lambda: runtime._fundamentals(bundle.ticker, curr_date),
                fetch_news_evidence=fetch_news_evidence,
                fetch_sentiment_evidence=fetch_sentiment_evidence,
                fetch_macro_evidence=lambda: runtime._macro("", curr_date),
            )
            manifests = runtime._deduplicate_external_manifests(runtime._EXTERNAL_MANIFESTS.get())
            return {**result, "_external_evidence_manifest": manifests}
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
