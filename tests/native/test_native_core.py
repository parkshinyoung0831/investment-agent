"""네이티브 계약·파이프라인의 네트워크 없는 회귀 테스트."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import numpy as np

from investment_agent.trading.contracts import EvidenceBundle, EvidenceItem
from investment_agent.execution.orders.tca import build_tca_report
from investment_agent.trading.performance import build_attribution_report, make_trade_outcome
from investment_agent.execution.orders.market_state import MarketState
from investment_agent.trading.decision.contracts import Event, ExpectedReturnSignal
from investment_agent.research.features.event_intelligence import (
    RawContent,
    extract_events,
    normalize_contents,
    summarize_event_features,
)
from investment_agent.trading.decision.pipeline import run_intelligence
from investment_agent.trading.decision.fast_ranker import FastRankFeatures, rank_fast_candidates
from investment_agent.trading.decision.regime import build_market_regime
from investment_agent.research.evaluation.challenger import ChallengerPolicy, compare_challenger
from investment_agent.research.contracts import FeatureRecord, LabelRecord
from investment_agent.research.datasets import build_research_dataset
from investment_agent.research.training.baseline import train_baseline_dataset


AS_OF = "2026-08-27T09:00:00+00:00"


def _evidence(evidence_id: str, domain: str, payload: dict) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        domain=domain,
        source="test",
        observed_at=AS_OF,
        available_at=AS_OF,
        timing_status="known",
        payload=payload,
    )


def _bundle() -> EvidenceBundle:
    return EvidenceBundle(
        ticker="AAPL",
        as_of_at=AS_OF,
        source_kind="historical_replay",
        evidence=(
            _evidence("market-1", "market", {
                "return_20d": 0.10,
                "volume_ratio_20d": 2.0,
                "rsi14": 65.0,
                "macd_spread_pct": 0.01,
            }),
            _evidence("fundamental-1", "fundamentals", {
                "revenue_growth_yoy": 0.20,
                "operating_margin": 0.20,
                "estimate_revision": 0.10,
            }),
            _evidence("macro-1", "macro", {"macro_score": -0.40}),
        ),
    )


class NativeCoreTests(unittest.TestCase):
    def test_event_normalization_dedupes_content_and_extracts_pit_cluster(self) -> None:
        first = RawContent(
            provider="finnhub",
            content_type="news",
            ticker="AAPL",
            fetched_at="2026-08-27T08:05:00+00:00",
            published_at="2026-08-27T08:00:00+00:00",
            title="AAPL earnings beat revenue growth",
            content="AAPL reports earnings beat revenue growth strong",
            url="https://example.com/a",
        )
        duplicate = RawContent(
            provider="other-news",
            content_type="news",
            ticker="AAPL",
            fetched_at="2026-08-27T08:06:00+00:00",
            published_at="2026-08-27T08:01:00+00:00",
            title=first.title,
            content=first.content,
            url="https://another.example/a",
        )
        related = RawContent(
            provider="reuters",
            content_type="news",
            ticker="AAPL",
            fetched_at="2026-08-27T08:07:00+00:00",
            published_at="2026-08-27T08:02:00+00:00",
            title="AAPL earnings beat revenue growth record",
            content="AAPL earnings beat revenue growth record profit",
            url="https://example.com/b",
        )
        self.assertEqual(len(normalize_contents((first, duplicate))), 1)
        events = extract_events((first, related), as_of_at=AS_OF)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].source_count, 2)
        self.assertLess(events[0].first_seen_at, events[0].available_at)
        future = RawContent(
            provider="future",
            content_type="news",
            ticker="AAPL",
            fetched_at="2026-08-27T10:00:00+00:00",
            published_at="2026-08-27T10:00:00+00:00",
            title="future earnings",
            content="future earnings beat",
        )
        self.assertEqual(len(extract_events((first, future), as_of_at=AS_OF)), 1)
        features = summarize_event_features(events, ticker="AAPL", as_of_at=AS_OF)
        self.assertEqual(features.event_count, 1)
        self.assertGreater(features.news_velocity, 0.0)

    def test_market_regime_and_fast_ranker_are_deterministic_numeric_layers(self) -> None:
        regime = build_market_regime(
            AS_OF,
            benchmark_return=-0.05,
            breadth=0.20,
            volatility=0.55,
            liquidity=0.10,
            drawdown=0.25,
            event_risk=0.90,
        )
        self.assertEqual(regime.risk_state, "CRISIS")
        features = (
            FastRankFeatures("AAPL", last_analyzed_at=AS_OF, momentum=0.20, news_velocity=1.0),
            FastRankFeatures("MSFT", last_analyzed_at=AS_OF, momentum=0.05),
            FastRankFeatures("NVDA", last_analyzed_at=AS_OF, momentum=0.30, volume_anomaly=2.0),
        )
        ranks = rank_fast_candidates(features, as_of_at=AS_OF, limit=2)
        self.assertEqual(len(ranks), 2)
        self.assertEqual(ranks[0].score_purpose, "deep_analysis_priority")
        self.assertGreaterEqual(ranks[0].score, ranks[1].score)

    def test_desks_debate_and_fusion_share_structured_contract(self) -> None:
        high_event = Event(
            event_id="event-high",
            ticker="AAPL",
            event_type="litigation",
            occurred_at="2026-08-27T08:00:00+00:00",
            available_at="2026-08-27T08:10:00+00:00",
            first_seen_at="2026-08-27T08:05:00+00:00",
            importance=0.90,
            direction=-1.0,
            confidence=0.90,
            novelty=0.80,
            controversy=0.50,
            source_count=1,
            source_diversity=1.0,
            sentiment=-1.0,
            evidence_ids=("event-evidence",),
        )
        result = run_intelligence(
            bundle=_bundle(),
            events=(high_event,),
            regime_inputs={"event_risk": 0.90},
        )
        self.assertEqual({signal.domain for signal in result.desk_signals}, {
            "market", "fundamental", "macro", "event",
        })
        self.assertIsNotNone(result.debate_signal)
        self.assertEqual(result.signal.ticker, "AAPL")
        self.assertIn("event-evidence", result.signal.evidence_ids)
        self.assertGreater(result.fusion.direction_dispersion, 0.0)

    def test_market_state_is_ram_only_latest_and_freshness_checked(self) -> None:
        state = MarketState()
        state.update(
            ticker="AAPL", bid=99.0, ask=101.0, last=100.0,
            volume=1000.0, recent_volume=900.0, volatility=0.02,
            session="regular", observed_at=AS_OF,
        )
        self.assertTrue(state.is_fresh("AAPL", as_of_at="2026-08-27T09:00:10+00:00"))
        self.assertFalse(state.is_fresh("AAPL", as_of_at="2026-08-27T09:01:00+00:00"))
        with self.assertRaises(ValueError):
            state.update(ticker="AAPL", last=99.0, observed_at="2026-08-27T08:59:00+00:00")
        quote = state.get("AAPL")
        self.assertIsNotNone(quote)
        self.assertEqual(quote.mid, 100.0)
        snapshot = quote.to_snapshot_row(
            purpose="pre_order",
            source_kind="paper",
            captured_at="2026-08-27T09:00:11+00:00",
        )
        self.assertEqual(snapshot["purpose"], "pre_order")
        self.assertEqual(len(snapshot["snapshot_hash"]), 64)

    def test_research_dataset_has_pit_manifest_and_ridge_artifact(self) -> None:
        features = []
        labels = []
        for index in range(6):
            as_of = datetime(2026, 8, 1 + index, tzinfo=timezone.utc)
            end = as_of + timedelta(days=5)
            features.append(FeatureRecord(
                ticker="AAPL",
                as_of_at=as_of.isoformat(),
                available_at=as_of.isoformat(),
                feature_version="test-features-v1",
                features={"momentum": float(index), "quality": 1.0},
            ))
            labels.append(LabelRecord(
                ticker="AAPL",
                as_of_at=as_of.isoformat(),
                forward_end_at=end.isoformat(),
                label_available_at=end.isoformat(),
                feature_version="test-features-v1",
                label_definition="forward_5d",
                label=float(index) / 10.0,
            ))
        dataset = build_research_dataset(
            features,
            labels,
            feature_version="test-features-v1",
            label_definition="forward_5d",
            label_cutoff_at="2026-08-20T00:00:00+00:00",
        )
        self.assertEqual(len(dataset.rows), 6)
        self.assertLess(dataset.manifest.train_period[1], dataset.manifest.validation_period[0])
        result = train_baseline_dataset(
            dataset,
            model_kind="ridge",
            train_split=(0, 3),
            validation_split=(3, 4),
            test_split=(4, 6),
            parameters={"alpha": 0.1},
        )
        self.assertEqual(result.artifact.model_kind, "ridge")
        self.assertEqual(result.artifact.out_of_sample.sample_count, 2)

    def test_tca_attribution_and_challenger_are_safe_contracts(self) -> None:
        tca = build_tca_report(
            ticker="AAPL", side="buy", decision_price=100.0,
            arrival_price=100.1, fill_price=100.2, quantity=10.0,
            bid=99.9, ask=100.1, mid=100.0, fees=1.0,
            submitted_at="2026-08-27T09:00:00+00:00",
            filled_at="2026-08-27T09:00:02+00:00",
        )
        self.assertAlmostEqual(tca.time_to_fill, 2.0)
        self.assertAlmostEqual(tca.implementation_shortfall, tca.slippage + tca.delay_cost + tca.fees)
        outcome = make_trade_outcome(
            ticker="AAPL", side="buy", entry_at=AS_OF,
            exit_at="2026-08-30T09:00:00+00:00", quantity=2.0,
            entry_price=100.0, exit_price=110.0, fees=1.0,
            execution_slippage=0.5,
        )
        report = build_attribution_report(
            total_pnl=outcome.net_pnl,
            components={"market_effect": 5.0, "selection_alpha": 10.0},
            ticker="AAPL", outcome_id=outcome.outcome_id,
            created_at="2026-08-30T10:00:00+00:00",
        )
        component_total = sum(getattr(report, name) for name in (
            "market_effect", "selection_alpha", "allocation_effect", "timing_effect",
            "risk_overlay_effect", "execution_slippage", "fees", "residual",
        ))
        self.assertAlmostEqual(component_total, outcome.net_pnl)
        comparison = compare_challenger(
            challenger_id="challenger-v2", champion_id="champion-v1",
            challenger={"oos_excess_return": 0.03, "oos_sharpe": 1.2, "max_drawdown": -0.10, "turnover": 1.0},
            champion={"oos_excess_return": 0.01, "oos_sharpe": 1.0, "max_drawdown": -0.10, "turnover": 1.0},
            shadow_days=30, paper_days=30,
            policy=ChallengerPolicy(minimum_shadow_days=20, minimum_paper_days=30),
        )
        self.assertTrue(comparison.eligible_for_manual_review)
        self.assertFalse(comparison.auto_promoted)


if __name__ == "__main__":
    unittest.main()
