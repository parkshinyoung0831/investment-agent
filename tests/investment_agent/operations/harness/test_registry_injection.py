"""주입한 adapters가 registry 전체를 설명하는지 본다.

`build_registry(adapters=...)`는 job마다 주입받은 handler를 꽂는데, intelligence
job만 수집 함수를 직접 들고 있었다. 그래서 adapters를 통째로 가짜로 넘긴
호출에도 진짜 news·social provider가 섞여 들어가, 그 테스트가 Supabase로 HTTPS를
열었다. 그 실패는 `_intelligence_stage`가 `skipped`로 삼키므로 테스트는 통과했고,
남는 것은 자격증명이 있는 기계에서만 이따금 붉어지는 실행뿐이었다.

`.env`가 없는 기계에서는 진짜 수집기가 네트워크 전에 `KeyError`로 죽는다 —
그래서 "밖으로 나가는 연결이 있는가"로 묻는 검사는 이 결함을 앞에 두고도
조용히 통과한다. 여기서는 대신 계약을 직접 묻는다: 주입한 것이 불렸는가.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from investment_agent.operations.commands.investment_harness import build_registry
from investment_agent.operations.harness.contracts import HarnessMode, StageOutcome
from investment_agent.operations.harness.runtime import HarnessScheduler
from investment_agent.operations.harness.state import JsonStateStore

_STAGE_ADAPTERS = (
    "analysis", "select_signal", "portfolio", "execution_intent", "approval_request",
    "approval_worker", "risk_snapshot", "reconcile", "watch", "build_valuations",
    "build_features", "build_labels", "build_training_samples", "build_events",
    "evaluate_decisions", "notify_investment", "notify_trades",
)

#: 수집 단계는 stage handler와 서명이 다르다 — context가 아니라 database_path 하나를 받는다.
_COLLECTOR_ADAPTERS = ("collect_news", "collect_social", "prune_intelligence")


class RegistryInjectionTest(unittest.TestCase):
    def _tick_with_fakes(self) -> set[str]:
        """가짜 adapters로 한 tick 돌리고, 실제로 불린 adapter 이름을 돌려준다."""
        called: set[str] = set()

        def stage(name):
            def handler(_context):
                called.add(name)
                return StageOutcome.succeeded()
            return handler

        def collector(name):
            def step(_database_path=None):
                called.add(name)
                return {}
            return step

        adapters = SimpleNamespace(
            **{name: stage(name) for name in _STAGE_ADAPTERS},
            **{name: collector(name) for name in _COLLECTOR_ADAPTERS},
        )
        start = datetime(2026, 8, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp:
            scheduler = HarnessScheduler(
                registry=build_registry(interval_seconds=60, adapters=adapters),
                store=JsonStateStore(Path(temp) / "state.json"),
                mode=HarnessMode.ANALYSIS_ONLY,
                environ={"TRADING_KILL_SWITCH": "off"},
            )
            scheduler.start(now=start)
            scheduler.tick(now=start)
        return called

    def test_intelligence_collection_runs_the_injected_steps(self):
        """하나라도 안 불리면 그 자리에 진짜 provider가 들어와 있다는 뜻이다."""
        called = self._tick_with_fakes()
        self.assertEqual(set(_COLLECTOR_ADAPTERS), called & set(_COLLECTOR_ADAPTERS))

    def test_the_tick_actually_exercises_the_registry(self):
        """아무것도 안 불리는 tick이면 위 검사는 공허하게 통과한다."""
        self.assertIn("analysis", self._tick_with_fakes())
