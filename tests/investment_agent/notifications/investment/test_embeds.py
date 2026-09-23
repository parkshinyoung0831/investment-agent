"""자동매매 보고서 embed 조립 — 순수 함수라 DB·네트워크 없이 검증한다."""
from __future__ import annotations

import unittest

from investment_agent.notifications.investment import embeds
from investment_agent.notifications.investment.palette import COLOR_DANGER, COLOR_NEUTRAL, COLOR_WARNING

# DESIGN-system.md의 방향색. rail에 절대 나오면 안 된다(§2.4).
_DIRECTION_COLORS = {0x05B169, 0xCF202F}


def _proposal(**overrides):
    row = {
        "proposal_id": "proposal_abc",
        "run_id": "run_abc",
        "as_of_at": "2026-09-03T00:00:00+00:00",
        "weights": {"AAPL": 0.06, "MSFT": 0.04, "CASH": 0.90},
        "confidence": 1.0,
        "reasoning": ["고정 문구"],
        "metadata": {
            "factor_snapshot_as_of": "2026-09-02",
            "system_policy": {"version": "system-target-v5"},
            "market_regime": {"risk_state": "NORMAL"},
            "alpha_reasons": {"AAPL": "THESIS_CONFIRMED_TILT", "NVDA": "UNVERIFIED_ENTRY_BLOCKED",
                              "AMD": "UNVERIFIED_ENTRY_BLOCKED", "UNH": "THESIS_VETO"},
            "short_history_excluded": ["BE"],
        },
    }
    row.update(overrides)
    return row


def _risk(**overrides):
    row = {
        "is_approved": True,
        "violations": [],
        "metrics": {"portfolio_volatility": 0.14, "portfolio_beta": 0.92, "turnover": 0.10,
                    "discretionary_turnover": 0.10,
                    "policy_limits": {"min_cash_weight": 0.05, "max_turnover": 0.25}},
    }
    row.update(overrides)
    return row


def _run(**overrides):
    row = {"run_id": "run_abc", "status": "partial", "candidate_tickers": ["AAPL", "MSFT", "NVDA"],
           "failure_reason": None}
    row.update(overrides)
    return row


def _decision(**final_overrides):
    final = {
        "thesis": "positive", "hard_constraint": "none", "signal": "open",
        "probability_up": 0.61, "confidence": 0.72, "expected_excess_return": 0.031, "target_weight": 0.06,
        "key_risks": ["중국 매출 둔화"], "reasoning": ["서비스 마진 개선", "밸류에이션 부담은 낮음"],
        "evidence_ids": ["EV-MARKET-1", "EV-FUND-2"], "missing_data": [],
    }
    final.update(final_overrides)
    return {"case_key": "case_a", "ticker": "AAPL", "as_of_at": "2026-09-03T00:00:00+00:00",
            "status": "completed", "final_decision": final}


def _flatten(embed):
    parts = [str(embed.get("title", "")), str(embed.get("description", ""))]
    parts += [f"{field['name']} {field['value']}" for field in embed["fields"]]
    parts.append(str(embed.get("footer", {}).get("text", "")))
    return " ".join(parts)


def _field(embed, prefix):
    return next((item["value"] for item in embed["fields"] if item["name"].startswith(prefix)), None)


class PortfolioEmbedTest(unittest.TestCase):
    def test_the_first_lines_say_exposure_cash_budget_and_verdict(self):
        embed = embeds.portfolio_embed(proposal=_proposal(), risk=_risk(), run=_run())
        self.assertIn("주식 **10.0%** · 현금 **90.0%** (최소 현금 5.0% · 시장 NORMAL)", embed["description"])
        self.assertIn("RiskGate **승인** · 변동성 0.14", embed["description"])

    def test_rail_is_neutral_when_approved_warning_when_rejected_danger_on_failure(self):
        self.assertEqual(COLOR_NEUTRAL, embeds.portfolio_embed(proposal=_proposal(), risk=_risk(), run=_run())["color"])
        rejected = embeds.portfolio_embed(
            proposal=_proposal(), run=_run(),
            risk=_risk(is_approved=False, violations=["portfolio beta exceeds 1.5", "turnover above policy"]))
        self.assertEqual(COLOR_WARNING, rejected["color"])
        self.assertIn("beta exceeds", _field(rejected, "⚖️"))
        failed = embeds.portfolio_embed(proposal=_proposal(), risk=_risk(), run=_run(failure_reason="covariance"))
        self.assertEqual(COLOR_DANGER, failed["color"])

    def test_high_cash_is_explained_from_the_ledger(self):
        reasons = _field(embeds.portfolio_embed(proposal=_proposal(), risk=_risk(), run=_run()), "💵")
        self.assertIn("논지 검증 전이라 신규 편입을 막은 후보 **2**", reasons)
        self.assertIn("논지가 부정이라 늘리지 않은 종목 **1**", reasons)
        self.assertIn("가격 이력이 짧아 제외한 신규 후보 **1** (BE)", reasons)
        self.assertNotIn("turnover 한도", reasons)

    def test_a_rebalance_that_used_the_whole_turnover_limit_says_so(self):
        risk = _risk(metrics={**_risk()["metrics"], "discretionary_turnover": 0.25})
        self.assertIn("turnover 한도 25%까지", _field(embeds.portfolio_embed(proposal=_proposal(), risk=risk, run=_run()), "💵"))

    def test_cash_at_its_budget_needs_no_explanation(self):
        proposal = _proposal(weights={"AAPL": 0.5, "MSFT": 0.46, "CASH": 0.04})
        self.assertIsNone(_field(embeds.portfolio_embed(proposal=proposal, risk=_risk(), run=_run()), "💵"))

    def test_holdings_scope_and_engine_are_visible_without_claiming_rl(self):
        text = _flatten(embeds.portfolio_embed(proposal=_proposal(), risk=_risk(), run=_run()))
        self.assertIn("`AAPL` 6.0%", text)
        self.assertIn("후보 3종목", text)
        self.assertIn("system-target-v5", text)
        self.assertIn("RiskGate", text)
        self.assertNotIn("강화학습", text)
        self.assertNotIn("고정 문구", text)  # 매번 같은 reasoning 문구는 싣지 않는다

    def test_metrics_missing_or_null_are_left_out_not_zeroed(self):
        risk = _risk(metrics={"portfolio_volatility": None, "portfolio_beta": 0.07})
        text = _flatten(embeds.portfolio_embed(proposal=_proposal(), risk=risk, run=_run()))
        self.assertIn("베타 0.07", text)
        self.assertNotIn("None", text)
        self.assertNotIn("변동성 0.00", text)

    def test_each_weight_change_has_its_reason(self):
        proposal = _proposal(weights={"AAPL": 0.0, "MSFT": 0.08, "CASH": 0.92}, metadata={"trade_reasons": {
            "AAPL": {"code": "ALPHA_DECAY", "current_weight": 0.1, "target_weight": 0.0,
                     "constraint": "block_increase", "expected_return_capped": False},
            "MSFT": {"code": "ALPHA_OPPORTUNITY", "current_weight": 0.0, "target_weight": 0.08,
                     "constraint": None, "expected_return_capped": True},
        }})
        changes = _field(embeds.portfolio_embed(proposal=proposal, risk=_risk(), run=_run()), "🔁")
        self.assertIn("`AAPL` 10.0% → 0.0% · 전망 약화", changes)
        self.assertIn("확대 금지", changes)
        self.assertIn("과대 기대수익 상한 적용", changes)

    def test_no_changes_means_no_empty_change_field(self):
        embed = embeds.portfolio_embed(proposal={"weights": {"CASH": 1.0}}, risk={"is_approved": True}, run={})
        self.assertIsNone(_field(embed, "🔁"))


class CandidateEmbedTest(unittest.TestCase):
    def test_title_is_the_thesis_and_direction_never_colours_the_rail(self):
        for thesis in ("positive", "neutral", "negative"):
            embed = embeds.candidate_embed(decision=_decision(thesis=thesis))
            self.assertNotIn(embed["color"], _DIRECTION_COLORS)
            self.assertEqual(COLOR_NEUTRAL, embed["color"])
        self.assertEqual("AAPL · 논지 긍정", embeds.candidate_embed(decision=_decision())["title"])

    def test_a_hard_constraint_is_a_warning_in_the_title_and_rail(self):
        embed = embeds.candidate_embed(decision=_decision(thesis="negative", hard_constraint="force_exit"))
        self.assertEqual("AAPL · 논지 부정 · 강제 청산", embed["title"])
        self.assertEqual(COLOR_WARNING, embed["color"])

    def test_old_records_without_a_thesis_read_the_signal_word(self):
        decision = _decision(signal="reduce")
        decision["final_decision"].pop("thesis")
        self.assertEqual("AAPL · 논지 부정", embeds.candidate_embed(decision=decision)["title"])

    def test_llm_numbers_are_labelled_as_llm_estimates_and_the_weight_is_never_shown(self):
        text = _flatten(embeds.candidate_embed(decision=_decision()))
        self.assertIn("LLM 추정: 20거래일 SPY 대비 **+3.10%**", text)
        self.assertNotIn("목표 비중", text)

    def test_risks_reasoning_and_missing_evidence_are_shown(self):
        embed = embeds.candidate_embed(decision=_decision(missing_data=["gurus: 매핑된 보유 근거 없음"]))
        self.assertIn("중국 매출 둔화", _field(embed, "⚠️"))
        self.assertIn("서비스 마진 개선", _field(embed, "🧭"))
        self.assertIn("gurus", _field(embed, "🔗"))
        self.assertNotIn("None", _flatten(embeds.candidate_embed(decision=_decision(key_risks=None))))

    def test_evidence_ids_are_stripped_from_sentences_and_long_lines_are_cut(self):
        reasoning = ["마진이 개선된다 (EV-FUND-1a2b; EV-SEG-3c4d).", "가" * 400]
        text = _field(embeds.candidate_embed(decision=_decision(reasoning=reasoning)), "🧭")
        self.assertIn("• 마진이 개선된다.", text)
        self.assertNotIn("EV-FUND", text)
        self.assertLess(max(len(line) for line in text.splitlines()), 170)

    def test_a_flipped_direction_is_called_out(self):
        embed = embeds.candidate_embed(decision=_decision(thesis="negative", previous_signal="increase"))
        self.assertIn("직전 판단 논지 긍정 → **방향 변경**", embed["description"])


def _order(**overrides):
    row = {"client_order_id": "order_1", "intent_id": "intent_1", "approval_id": "approval_1", "ticker": "AAPL",
           "side": "buy", "quantity": 12, "reference_price": 230.5, "status": "filled"}
    row.update(overrides)
    return row


_FILLS = [{"quantity": 8, "price": 230.0, "commission": 0.5}, {"quantity": 4, "price": 233.0, "commission": 0.3}]


class TradeEmbedTest(unittest.TestCase):
    def test_both_sides_use_the_neutral_rail(self):
        for side in ("buy", "sell"):
            self.assertEqual(COLOR_NEUTRAL, embeds.trade_embed(order=_order(side=side), fills=[], execution_mode="paper")["color"])

    def test_execution_mode_and_average_fill_are_visible(self):
        text = _flatten(embeds.trade_embed(order=_order(), fills=_FILLS, execution_mode="live"))
        self.assertIn("**live**", text)
        self.assertIn("체결 **12주** · 평균 **231.00**", text)

    def test_execution_cost_against_the_arrival_price_has_the_right_sign(self):
        buy = _field(embeds.trade_embed(order=_order(arrival_price=230.0), fills=_FILLS, execution_mode="live"), "✅")
        self.assertIn("실행 비용 **+43.5bp**", buy)  # 230에 도착해 231에 샀다 — 비용
        sell = _field(embeds.trade_embed(order=_order(side="sell", arrival_price=230.0), fills=_FILLS,
                                         execution_mode="live"), "✅")
        self.assertIn("실행 비용 **-43.5bp**", sell)  # 230에 도착해 231에 팔았다 — 이득

    def test_an_unfilled_order_says_so_instead_of_showing_a_zero_price(self):
        text = _flatten(embeds.trade_embed(order=_order(status="submitted"), fills=[], execution_mode="live"))
        self.assertNotIn("0.00", text.replace("230.50", ""))
        self.assertIn("아직 체결 없음", text)
        self.assertIn("approval_1", text)


if __name__ == "__main__":
    unittest.main()
