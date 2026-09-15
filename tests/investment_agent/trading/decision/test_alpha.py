"""ALPHA: IC×σ×z 기대수익, 논지의 거부권·소폭 조정·검증 전 신규 금지. 사고팔기 단어는 입력이 아니다."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.research.features.factors import FactorScore
from investment_agent.trading.decision.alpha import (
    THESIS_BROKEN,
    THESIS_NEGATIVE,
    THESIS_NEUTRAL,
    THESIS_POSITIVE,
    AlphaPlan,
    AlphaPolicy,
    ThesisView,
    expected_return_signals,
)
from investment_agent.trading.portfolio.optimizer import CONSTRAINT_BLOCK_INCREASE, CONSTRAINT_FORCE_EXIT

AS_OF = datetime(2026, 9, 15, 21, 0, tzinfo=timezone.utc)
POLICY = AlphaPolicy(candidate_count=3)


def _scores(**composites) -> dict[str, FactorScore]:
    return {ticker: FactorScore(ticker, {"quality": 0.8}, value, True, None) for ticker, value in composites.items()}


def _view(ticker: str, signal: str, expected: float, probability: float, *, days_ago: int = 3,
          confidence: float = 0.8) -> ThesisView:
    return ThesisView(ticker, AS_OF - timedelta(days=days_ago), signal, expected, probability, confidence)


def _by_symbol(plan: AlphaPlan):
    return {signal.symbol: signal for signal in plan.signals}


class ThesisStateTest(unittest.TestCase):
    """행동 단어와 수치가 엇갈리면 수치를 따른다."""

    def test_exit_without_a_bearish_outlook_is_not_a_broken_thesis(self):
        self.assertEqual(_view("A", "exit", 0.02, 0.3).thesis_state, THESIS_NEGATIVE)
        self.assertEqual(_view("A", "exit", -0.02, 0.3).thesis_state, THESIS_BROKEN)

    def test_buy_words_without_a_bullish_outlook_are_neutral(self):
        self.assertEqual(_view("A", "open", -0.01, 0.6).thesis_state, THESIS_NEUTRAL)
        self.assertEqual(_view("A", "increase", 0.02, 0.6).thesis_state, THESIS_POSITIVE)

    def test_hold_with_a_bearish_outlook_is_negative(self):
        self.assertEqual(_view("A", "hold", -0.03, 0.4).thesis_state, THESIS_NEGATIVE)

    def test_explicit_thesis_fields_win_over_the_legacy_action_word(self):
        def explicit(thesis, hard_constraint="none", *, expected=0.02, probability=0.6):
            return ThesisView("A", AS_OF, "watch", expected, probability, 0.7, None, thesis, hard_constraint)

        self.assertEqual(explicit("positive").thesis_state, THESIS_POSITIVE)
        self.assertEqual(explicit("positive", expected=-0.01, probability=0.4).thesis_state, THESIS_NEUTRAL)
        self.assertEqual(explicit("negative").thesis_state, THESIS_NEGATIVE)
        self.assertEqual(explicit("neutral", "block_new_buy").thesis_state, THESIS_NEGATIVE)
        # 극단 상황의 hard constraint는 수치와 무관하게 논지 붕괴다.
        self.assertEqual(explicit("positive", "force_exit").thesis_state, THESIS_BROKEN)
        self.assertEqual(explicit("neutral", "exclude").thesis_state, THESIS_BROKEN)

    def test_views_outside_the_thesis_contract_are_ignored(self):
        base = {"ticker": "A", "as_of_at": AS_OF.isoformat(), "signal": "open",
                "expected_excess_return": 0.02, "probability_up": 0.6, "confidence": 0.7}
        self.assertIsNone(ThesisView.from_proposal({**base, "thesis": "bullish"}))
        self.assertIsNone(ThesisView.from_proposal({**base, "hard_constraint": "sell_now"}))
        view = ThesisView.from_proposal({**base, "thesis": "negative", "hard_constraint": "none", "key_risks": ["fraud probe"]})
        self.assertEqual((view.thesis_state, view.key_risks), (THESIS_NEGATIVE, ("fraud probe",)))

    def test_incomplete_rows_are_not_views(self):
        self.assertIsNone(ThesisView.from_proposal({"ticker": "A", "as_of_at": AS_OF.isoformat(), "signal": "open"}))
        view = ThesisView.from_proposal({"ticker": "a", "as_of_at": AS_OF.isoformat(), "signal": "open",
                                         "expected_excess_return": 0.02, "probability_up": 0.6, "confidence": 0.7},
                                        model_artifact_id="artifact-1")
        self.assertEqual((view.ticker, view.model_artifact_id), ("A", "artifact-1"))


class ExpectedReturnSignalsTest(unittest.TestCase):
    def setUp(self):
        self.scores = _scores(TOP=0.9, MID=0.6, LOW=0.2, BOTTOM=0.1, TAIL=0.05)
        self.sigma = {name: 0.08 for name in self.scores}
        self.verified = {name: _view(name, "open", 0.02, 0.6) for name in self.scores}

    def _plan(self, *, held=(), views=None, policy=POLICY, scores=None, sigma=None):
        return expected_return_signals(scores or self.scores, sigma_by_symbol=sigma or self.sigma, held_symbols=list(held),
                                       views=self.verified if views is None else views, as_of_at=AS_OF, policy=policy)

    def test_expected_return_is_ic_times_sigma_times_z_and_orders_by_score(self):
        plan = self._plan(views={}, policy=AlphaPolicy(candidate_count=5, llm_tilt_weight=0.0,
                                                        require_verified_entry=False))
        signals = _by_symbol(plan)
        self.assertGreater(signals["TOP"].expected_return, signals["MID"].expected_return)
        self.assertAlmostEqual(signals["LOW"].expected_return, 0.0, places=12)  # 다섯 중 가운데 순위는 z=0
        self.assertAlmostEqual(signals["TOP"].expected_return, 0.04 * 0.08 * 2.0537489, places=6)  # 백분위 0.98 절단
        self.assertTrue(all(signal.constraint is None for signal in plan.signals))

    def test_only_the_candidates_and_holdings_enter_the_optimizer(self):
        plan = self._plan(held=["TAIL"])
        self.assertEqual(sorted(_by_symbol(plan)), ["LOW", "MID", "TAIL", "TOP"])

    def test_unverified_new_names_cannot_be_bought(self):
        top = _by_symbol(plan := self._plan(views={}))["TOP"]
        self.assertEqual(top.constraint, CONSTRAINT_BLOCK_INCREASE)
        self.assertLessEqual(top.expected_return, 0.0)
        self.assertEqual(plan.reasons["TOP"], "UNVERIFIED_ENTRY_BLOCKED")

    def test_expired_view_does_not_verify(self):
        plan = self._plan(views={"TOP": _view("TOP", "open", 0.02, 0.6, days_ago=40)})
        self.assertEqual(plan.reasons["TOP"], "UNVERIFIED_ENTRY_BLOCKED")

    def test_broken_thesis_forces_a_held_name_out_even_with_top_factor_score(self):
        plan = self._plan(held=["TOP"], views={**self.verified, "TOP": _view("TOP", "exit", -0.03, 0.3)})
        top = _by_symbol(plan)["TOP"]
        self.assertEqual(top.constraint, CONSTRAINT_FORCE_EXIT)
        self.assertLess(top.expected_return, 0.0)
        self.assertEqual(plan.forced_exits, ("TOP",))

    def test_negative_thesis_blocks_increase_but_does_not_force_a_sale(self):
        plan = self._plan(held=["TOP"], views={**self.verified, "TOP": _view("TOP", "reduce", 0.01, 0.55)})
        top = _by_symbol(plan)["TOP"]
        self.assertEqual(top.constraint, CONSTRAINT_BLOCK_INCREASE)
        self.assertEqual(plan.reasons["TOP"], "THESIS_VETO")

    def test_bullish_thesis_cannot_make_a_weak_factor_name_attractive(self):
        plan = self._plan(held=["BOTTOM"], views={"BOTTOM": _view("BOTTOM", "open", 0.20, 0.9, confidence=1.0)})
        self.assertLess(_by_symbol(plan)["BOTTOM"].expected_return, 0.0)

    def test_agreeing_thesis_tilts_only_partly_and_within_one_sigma(self):
        before = _by_symbol(self._plan(held=["TOP"], views={}))["TOP"].expected_return
        after = _by_symbol(self._plan(held=["TOP"], views={"TOP": _view("TOP", "hold", 0.50, 0.9, confidence=1.0)}))[
            "TOP"].expected_return
        # 논지의 +50%는 1σ(8%)로 잘리고 그 25%만 반영된다.
        self.assertAlmostEqual(after, before + 0.25 * (0.08 - before))

    def test_held_name_that_fails_the_quality_gate_can_only_shrink(self):
        scores = {**self.scores, "HELD": FactorScore("HELD", {"quality": 0.1}, 0.95, False, "quality_below_floor")}
        plan = self._plan(scores=scores, sigma={**self.sigma, "HELD": 0.08}, held=["HELD"],
                          views={"HELD": _view("HELD", "open", 0.05, 0.7)})
        held = _by_symbol(plan)["HELD"]
        self.assertEqual(held.constraint, CONSTRAINT_BLOCK_INCREASE)
        self.assertLessEqual(held.expected_return, 0.0)

    def test_champion_ml_moves_the_factor_prior_by_its_oos_confidence(self):
        policy = AlphaPolicy(candidate_count=5, llm_tilt_weight=0.0, require_verified_entry=False)
        plain = _by_symbol(self._plan(views={}, policy=policy))
        blended = expected_return_signals(
            self.scores, sigma_by_symbol=self.sigma, held_symbols=[], views={}, as_of_at=AS_OF, policy=policy,
            ml_expected_returns={"LOW": 0.05, "TOP": 0.50}, ml_confidence=0.3,
        )
        signals = _by_symbol(blended)
        # LOW의 factor 사전값은 0(가운데 순위), ML +5%의 30%가 반영된다.
        self.assertAlmostEqual(signals["LOW"].expected_return, 0.3 * 0.05, places=9)
        # ML 예측도 ±1σ(8%)로 잘린다.
        self.assertAlmostEqual(signals["TOP"].expected_return, 0.7 * plain["TOP"].expected_return + 0.3 * 0.08, places=9)
        self.assertEqual(blended.reasons["LOW"], "FACTOR_ML_BASE")
        self.assertAlmostEqual(blended.detail["LOW"]["ml_share"], 0.3)
        # 예측이 없는 종목은 factor 사전값 그대로다.
        self.assertAlmostEqual(signals["MID"].expected_return, plain["MID"].expected_return)

    def test_ml_switched_off_for_ablation_leaves_the_factor_prior(self):
        policy = AlphaPolicy(candidate_count=5, llm_tilt_weight=0.0, require_verified_entry=False, use_ml=False)
        plain = _by_symbol(self._plan(views={}, policy=policy))
        blended = _by_symbol(expected_return_signals(
            self.scores, sigma_by_symbol=self.sigma, held_symbols=[], views={}, as_of_at=AS_OF, policy=policy,
            ml_expected_returns={"LOW": 0.05}, ml_confidence=0.8,
        ))
        self.assertEqual(blended["LOW"].expected_return, plain["LOW"].expected_return)

    def test_confidence_is_the_agreement_of_the_sources_not_the_llm_self_report(self):
        policy = AlphaPolicy(candidate_count=5, llm_tilt_weight=0.0, require_verified_entry=False)
        plan = expected_return_signals(
            self.scores, sigma_by_symbol=self.sigma, held_symbols=[], as_of_at=AS_OF, policy=policy,
            views={"TOP": _view("TOP", "open", 0.02, 0.6, confidence=0.1)},
            ml_expected_returns={"TOP": 0.02, "MID": -0.20}, ml_confidence=0.1,
        )
        signals = _by_symbol(plan)
        # TOP: factor·ML·논지 모두 상승 → 1.0 (LLM이 적은 0.1은 쓰지 않는다)
        self.assertEqual(signals["TOP"].confidence, 1.0)
        # MID: factor는 상승, ML은 하락. 최종값과 같은 방향은 둘 중 하나다.
        self.assertEqual(signals["MID"].confidence, 0.5)

    def test_thesis_switched_off_for_ablation_does_not_block_unverified_entries(self):
        plan = self._plan(views={}, policy=AlphaPolicy(candidate_count=3, use_thesis=False))
        self.assertIsNone(_by_symbol(plan)["TOP"].constraint)
        self.assertEqual(plan.reasons["TOP"], "FACTOR_BASE")

    def test_held_name_without_inputs_is_fixed_not_sold(self):
        plan = self._plan(held=["UNKNOWN"], views={})
        self.assertEqual(plan.fixed_symbols, ("UNKNOWN",))
        self.assertNotIn("UNKNOWN", _by_symbol(plan))


if __name__ == "__main__":
    unittest.main()
