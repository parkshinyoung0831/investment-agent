"""구조화 판단 계층의 계약.

이 계층은 **비중을 정하지 않는다.** 그 경계가 무너지면 LLM이 실행 권한을 갖게 되므로
(`SYSTEM_UPGRADE_MASTER.md` §4.2) 마지막 테스트가 import 방향으로 그것을 고정한다.
"""
from __future__ import annotations

import unittest
from unittest import mock

from investment_agent.platform.serialization import ContractError
from investment_agent.trading.decision.judgment import (
    Answer,
    DeterministicJudge,
    JudgmentResult,
    Question,
    QuestionSet,
    question_set,
    registered_names,
)
from investment_agent.trading.decision.judgment.contracts import KIND_BOOLEAN, KIND_CHOICE
from investment_agent.trading.decision.judgment.router import (
    REASON_HELD_POSITION,
    REASON_LOW_CONFIDENCE,
    REASON_NO_JUDGMENT,
    REASON_SIGNAL_DISAGREEMENT,
    REASON_SKIPPED,
    decide_escalation,
    escalation_summary,
)


class AnswerTest(unittest.TestCase):
    def test_confidence_is_the_margin_not_the_top_probability(self):
        """보기가 많으면 최빈 확률이 낮아진다. 그것을 신뢰도로 쓰면 확신을 과소평가한다."""
        answer = Answer.from_distribution("q", {"a": 0.40, "b": 0.35, "c": 0.25})
        self.assertEqual("a", answer.value)
        self.assertAlmostEqual(0.05, answer.confidence, places=6)

    def test_a_coin_flip_has_no_confidence(self):
        answer = Answer.from_distribution("q", {"yes": 0.5, "no": 0.5})
        self.assertEqual(0.0, answer.confidence)

    def test_a_certain_answer_has_full_confidence(self):
        answer = Answer.from_distribution("q", {"yes": 1.0, "no": 0.0})
        self.assertEqual(1.0, answer.confidence)

    def test_a_distribution_that_does_not_sum_to_one_is_rejected(self):
        """합이 1이 아니면 확률이 아니다. 정규화해 주면 provider의 버그가 숨는다."""
        with self.assertRaises(ContractError):
            Answer("q", "yes", {"yes": 0.6, "no": 0.6}, 0.1)

    def test_choosing_a_value_outside_the_distribution_is_rejected(self):
        with self.assertRaises(ContractError):
            Answer("q", "maybe", {"yes": 0.5, "no": 0.5}, 0.0)


class QuestionSetTest(unittest.TestCase):
    def test_the_key_carries_the_version(self):
        """버전이 없으면 질문이 바뀐 뒤의 답을 이전 답과 같은 표에서 채점하게 된다."""
        self.assertEqual("fundamental-v1", question_set("fundamental").key)

    def test_a_boolean_question_takes_no_choices(self):
        with self.assertRaises(ContractError):
            Question("q", KIND_BOOLEAN, "정말?", choices=("yes", "no"))

    def test_a_choice_question_needs_at_least_two_options(self):
        with self.assertRaises(ContractError):
            Question("q", KIND_CHOICE, "어느 쪽?", choices=("only",))

    def test_duplicate_question_ids_are_rejected(self):
        question = Question("dup", KIND_BOOLEAN, "?")
        with self.assertRaises(ContractError):
            QuestionSet(name="x", version=1, questions=(question, question))

    def test_an_unknown_set_fails_instead_of_returning_nothing(self):
        """조용히 빈 묶음을 돌려주면 '질문이 없어서' 모든 종목이 escalate된다."""
        with self.assertRaises(KeyError):
            question_set("does_not_exist")

    def test_the_registry_is_not_empty(self):
        """레지스트리가 비면 아래 검사들이 공허하게 통과한다."""
        self.assertGreaterEqual(len(registered_names()), 3)


class DeterministicJudgeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.judge = DeterministicJudge()

    def test_it_costs_nothing(self):
        """Level 0의 존재 이유다. 토큰을 쓰면 싼 단계가 아니다."""
        result = self.judge.evaluate(None, question_set("router"),
                                     features={"event_high_impact_count": 1})
        self.assertEqual(0, result.input_tokens)
        self.assertEqual(0, result.output_tokens)

    def test_missing_features_leave_the_question_unanswered(self):
        """모르는 것을 0.5로 적으면 '반반이라고 판단했다'와 구별되지 않는다."""
        result = self.judge.evaluate(None, question_set("router"), features={})
        self.assertEqual(("deep_reasoning_required",), result.unanswered)
        self.assertEqual((), result.answers)

    def test_a_new_event_demands_deep_reasoning(self):
        result = self.judge.evaluate(None, question_set("router"),
                                     features={"event_high_impact_count": 3})
        self.assertEqual("yes", result.answer("deep_reasoning_required").value)

    def test_aligned_signals_do_not_demand_deep_reasoning(self):
        result = self.judge.evaluate(
            None, question_set("router"),
            features={"event_high_impact_count": 0, "momentum_12_1": 0.3,
                      "revision_breadth_30d": 0.5},
        )
        self.assertEqual("no", result.answer("deep_reasoning_required").value)

    def test_interest_coverage_below_one_is_a_strong_deterioration_signal(self):
        result = self.judge.evaluate(
            None, question_set("fundamental"),
            features={"quality_interest_coverage_ttm": 0.5},
        )
        answer = result.answer("balance_sheet_deteriorating")
        self.assertEqual("yes", answer.value)
        self.assertGreater(answer.probability, 0.8)

    def test_rules_never_claim_certainty(self):
        """결정론 규칙도 미래를 모른다. 1.0을 주면 뒤의 채점이 늘 최악으로 벌점을 받는다."""
        for features in (
            {"quality_interest_coverage_ttm": 0.1},
            {"quality_debt_to_equity": 99.0},
            {"event_high_impact_count": 5},
        ):
            with self.subTest(features=features):
                for name in ("router", "fundamental"):
                    for answer in self.judge.evaluate(
                        None, question_set(name), features=features,
                    ).answers:
                        self.assertLess(answer.probability, 1.0)

    def test_every_rule_method_matches_a_real_question_id(self):
        """메서드 이름이 어긋나면 그 질문은 조용히 답 없음이 된다."""
        known = {
            question.question_id
            for name in registered_names()
            for question in question_set(name).questions
        }
        rules = {
            name[len("_answer_"):]
            for name in dir(DeterministicJudge)
            if name.startswith("_answer_")
        }
        self.assertTrue(rules, "규칙이 하나도 없으면 이 검사는 공허하다")
        self.assertEqual(set(), rules - known, "질문 레지스트리에 없는 규칙이 있다")


class EscalationRouterTest(unittest.TestCase):
    @staticmethod
    def _judgment(value: str, confidence: float) -> JudgmentResult:
        probability = 0.5 + confidence / 2.0
        distribution = ({"yes": probability, "no": 1.0 - probability} if value == "yes"
                        else {"no": probability, "yes": 1.0 - probability})
        return JudgmentResult(
            provider="test", model="t", question_set_key="router-v1",
            answers=(Answer.from_distribution("deep_reasoning_required", distribution),),
        )

    def test_a_held_position_is_always_reviewed(self):
        """돈이 이미 들어간 종목의 판단을 아끼는 것은 절감이 아니라 위험이다."""
        decision = decide_escalation("AAPL", judgment=self._judgment("no", 0.9), is_held=True)
        self.assertTrue(decision.escalate)
        self.assertEqual(REASON_HELD_POSITION, decision.reason)

    def test_disagreeing_signals_escalate(self):
        decision = decide_escalation(
            "MSFT", judgment=self._judgment("no", 0.9),
            factor_direction=1.0, ml_direction=-1.0,
        )
        self.assertTrue(decision.escalate)
        self.assertEqual(REASON_SIGNAL_DISAGREEMENT, decision.reason)

    def test_no_judgment_escalates(self):
        """fail-open. 게이트가 조용히 닫혀 분석이 빠지는 것이 더 나쁘다."""
        decision = decide_escalation("NVDA", judgment=None)
        self.assertTrue(decision.escalate)
        self.assertEqual(REASON_NO_JUDGMENT, decision.reason)

    def test_a_low_confidence_skip_is_not_trusted(self):
        decision = decide_escalation("NVDA", judgment=self._judgment("no", 0.1))
        self.assertTrue(decision.escalate)
        self.assertEqual(REASON_LOW_CONFIDENCE, decision.reason)

    def test_a_confident_no_skips_the_expensive_path(self):
        decision = decide_escalation("NVDA", judgment=self._judgment("no", 0.9))
        self.assertFalse(decision.escalate)
        self.assertEqual(REASON_SKIPPED, decision.reason)

    def test_summary_reports_the_escalation_rate(self):
        decisions = [
            decide_escalation("A", judgment=self._judgment("no", 0.9)),
            decide_escalation("B", judgment=self._judgment("yes", 0.9)),
            decide_escalation("C", judgment=None),
        ]
        summary = escalation_summary(decisions)
        self.assertEqual(3, summary["scanned"])
        self.assertEqual(2, summary["escalated"])
        self.assertEqual(1, summary["skipped"])
        self.assertAlmostEqual(2 / 3, summary["escalation_rate"], places=4)

    def test_an_empty_run_is_not_a_zero_rate(self):
        """아무것도 안 본 것과 전부 건너뛴 것은 다르다."""
        self.assertEqual({"scanned": 0}, escalation_summary([]))


class JudgmentLayerBoundaryTest(unittest.TestCase):
    """판단 계층은 비중·주문에 닿지 않는다 (`SYSTEM_UPGRADE_MASTER.md` §4.2, 절대 불변)."""

    _FORBIDDEN = ("optimizer", "risk.gate", "execution", "portfolio_weights", "brokers")

    def test_the_layer_does_not_import_weights_or_execution(self):
        import pathlib

        package = pathlib.Path("src/investment_agent/trading/decision/judgment")
        modules = sorted(package.glob("*.py"))
        self.assertGreaterEqual(len(modules), 4, "모듈을 못 찾으면 이 검사는 공허하다")
        offenders: list[str] = []
        for module in modules:
            text = module.read_text(encoding="utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped.startswith(("import ", "from ")):
                    continue
                for forbidden in self._FORBIDDEN:
                    if forbidden in stripped:
                        offenders.append(f"{module.name}: {stripped}")
        self.assertEqual([], offenders, "판단 계층이 비중·주문 계층을 import한다")


class TypeSafeAdapterTest(unittest.TestCase):
    """Jev 어댑터 — 키가 없으면 호출하지 않고, 벤더 어휘를 밖으로 내보내지 않는다."""

    def test_it_refuses_to_send_an_unauthenticated_request(self):
        from investment_agent.trading.decision.judgment.typesafe import (
            TypeSafeConfigError,
            TypeSafeJudge,
        )

        judge = TypeSafeJudge(api_key="")
        with self.assertRaises(TypeSafeConfigError):
            judge.evaluate("state", question_set("router"))

    def test_the_model_version_is_pinned_not_floating(self):
        """`jev-latest`를 쓰면 어제 답과 오늘 답이 다른 모델에서 나와 채점이 무의미해진다."""
        from investment_agent.trading.decision.judgment.typesafe import DEFAULT_MODEL

        self.assertNotIn("latest", DEFAULT_MODEL)

    def test_a_boolean_probability_becomes_a_two_sided_distribution(self):
        from investment_agent.trading.decision.judgment.typesafe import TypeSafeJudge

        judge = TypeSafeJudge(api_key="k")
        body = {"answers": {"deep_reasoning_required": {"probability": 0.8}},
                "usage": {"input_tokens": 120}}
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = body
        with mock.patch.object(__import__("httpx").Client, "post", return_value=response):
            result = judge.evaluate("state", question_set("router"))
        answer = result.answer("deep_reasoning_required")
        self.assertEqual("yes", answer.value)
        self.assertAlmostEqual(0.8, answer.probability, places=6)
        self.assertEqual(120, result.input_tokens)
        self.assertIsNone(result.output_tokens, "출력 과금 없음을 0으로 적지 않는다")

    def test_an_option_outside_the_question_is_rejected(self):
        """provider가 우리가 주지 않은 보기를 만들어 내면 답이 아니라 오염이다."""
        from investment_agent.trading.decision.judgment.typesafe import TypeSafeJudge

        judge = TypeSafeJudge(api_key="k")
        body = {"answers": {"event_direction": {"distribution": {"sideways": 1.0}},
                            "material_news_present": {"probability": 0.5}}}
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = body
        with mock.patch.object(__import__("httpx").Client, "post", return_value=response):
            with self.assertRaises(ContractError):
                judge.evaluate("state", question_set("event"))

    def test_a_missing_answer_is_counted_not_dropped(self):
        from investment_agent.trading.decision.judgment.typesafe import TypeSafeJudge

        judge = TypeSafeJudge(api_key="k")
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"answers": {}}
        with mock.patch.object(__import__("httpx").Client, "post", return_value=response):
            result = judge.evaluate("state", question_set("router"))
        self.assertEqual(("deep_reasoning_required",), result.unanswered)
        self.assertFalse(result.is_complete)


if __name__ == "__main__":
    unittest.main()
