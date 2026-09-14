"""글로벌 사건이 검증을 거쳐 민감한 보유 종목의 재분석으로만 이어지는지."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from investment_agent.operations.commands.event_reanalysis import run_event_reanalysis
from investment_agent.research.features.event_intelligence import extract_events
from investment_agent.trading.decision.candidate_ranker import PriorityCandidate
from investment_agent.trading.decision.event_impact import global_event_priorities, market_confirms, tag_themes

AS_OF = datetime(2026, 9, 16, 22, tzinfo=timezone.utc)
EVENT_AT = datetime(2026, 9, 14, 23, tzinfo=timezone.utc)


def _proxy_rows(*, event_day_move: float) -> list[dict]:
    """조용한 20일 뒤 사건 다음 거래일(9/15)에 지정한 만큼 움직인 대표 ETF."""
    rows, value = [], 100.0
    start = date(2026, 8, 15)
    for offset in range(31):
        day = start + timedelta(days=offset)
        value *= 1.0 + (0.002 if offset % 2 else -0.002)
        rows.append({"trade_date": day.isoformat(), "close": value})
    value *= 1.0 + event_day_move
    rows.append({"trade_date": "2026-09-15", "close": value})
    return rows


def _event(*, providers=("reuters", "bloomberg"), importance=0.9, themes=("energy_oil",)):
    return {"event_id": "event_1", "ticker": None, "available_at": EVENT_AT.isoformat(), "importance": importance,
            "metadata": {"providers": list(providers), "themes": list(themes)}}


class ThemeTaggingTest(unittest.TestCase):
    def test_keywords_map_to_themes_without_partial_word_matches(self):
        self.assertEqual(tag_themes("OPEC agrees to cut crude output"), ("energy_oil",))
        self.assertEqual(tag_themes("Warner Bros reports"), ())  # "war"가 단어 일부로 걸리지 않는다

    def test_extracted_global_events_carry_theme_names(self):
        rows = [{"provider": provider, "content_type": "news", "ticker": None, "fetched_at": EVENT_AT.isoformat(),
                 "published_at": (EVENT_AT - timedelta(hours=1)).isoformat(), "title": "OPEC cuts crude output",
                 "content": f"Oil prices jump after OPEC decision, {provider} reports",
                 "url": f"https://{provider}.example/opec", "item_id": f"{provider}-opec"}
                for provider in ("reuters", "bloomberg")]
        events = extract_events(rows, as_of_at=AS_OF.isoformat())
        self.assertTrue(events)
        self.assertIn("energy_oil", events[0].metadata["themes"])


class GlobalEventPriorityTest(unittest.TestCase):
    def _run(self, event, *, move=0.03, sensitivity=1.0, last=None):
        return global_event_priorities(
            [event], held_tickers=["XOM", "AAPL"], last_analyzed_at=last or {},
            sensitivities={"XLE": {"XOM": sensitivity, "AAPL": 0.1}},
            proxy_rows={"XLE": _proxy_rows(event_day_move=move)}, as_of_at=AS_OF,
        )

    def test_verified_event_prioritizes_only_sensitive_holdings(self):
        result = self._run(_event())
        self.assertEqual([item.ticker for item in result], ["XOM"])
        self.assertEqual(result[0].tier, 0)
        self.assertEqual(result[0].reason, "held_global_event:energy_oil")

    def test_single_source_rumour_is_ignored(self):
        self.assertEqual(self._run(_event(providers=("blog",))), ())

    def test_event_the_market_did_not_react_to_is_ignored(self):
        self.assertFalse(market_confirms(_proxy_rows(event_day_move=0.0005), available_at=EVENT_AT))
        self.assertEqual(self._run(_event(), move=0.0005), ())

    def test_holding_already_reanalyzed_after_the_event_is_not_repeated(self):
        self.assertEqual(self._run(_event(), last={"XOM": EVENT_AT + timedelta(hours=2)}), ())

    def test_low_importance_is_ignored(self):
        self.assertEqual(self._run(_event(importance=0.4)), ())


class _Repository:
    def __init__(self, priorities):
        self.priorities = priorities

    def event_reanalysis_priorities(self, *, as_of_at):
        return self.priorities


class RunEventReanalysisTest(unittest.TestCase):
    def test_only_the_top_priorities_are_analyzed_in_one_run(self):
        calls = []
        priorities = tuple(PriorityCandidate(f"T{index}", 0, "held_new_filing", 1.0) for index in range(5))
        result = run_event_reanalysis(now=AS_OF, repository=_Repository(priorities),
                                      analyze=lambda argv: calls.append(argv) or 0,
                                      refresh=lambda now: {}, max_tickers=2)
        self.assertEqual(len(calls), 1)
        self.assertEqual([calls[0][index + 1] for index, value in enumerate(calls[0]) if value == "--ticker"], ["T0", "T1"])
        self.assertEqual(result["pending"], 5)

    def test_nothing_new_means_no_llm_call(self):
        calls = []
        run_event_reanalysis(now=AS_OF, repository=_Repository(()), analyze=lambda argv: calls.append(argv) or 0,
                             refresh=lambda now: {})
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
